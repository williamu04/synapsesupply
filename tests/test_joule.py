import base64
import json
from pathlib import Path

import httpx
import pytest
import yaml
from agent_helpers import build_service
from fastapi.testclient import TestClient

from synapse.api.app import DemoControl, create_api
from synapse.joule.bridge import SynapseApi, claimed_user, handle, parse, render_pending
from synapse.joule.server import create_app

JOULE_DIR = Path(__file__).parents[1] / "joule"


def jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"Bearer {enc({'alg': 'RS256'})}.{enc(claims)}.signature"


@pytest.fixture
def api(client) -> SynapseApi:
    return SynapseApi(TestClient(create_api(build_service(client), demo=DemoControl(client))),
                      console_url="https://synapse.example/console")


# --- parsing ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, kind, case_id, reason", [
    ("approve 4500000091-10", "APPROVE", "4500000091-10", None),
    ("Please approve case 4500000091-10", "APPROVE", "4500000091-10", None),
    ("reject 4500000091-10 because we slow down line 2", "REJECT", "4500000091-10", "we slow down line 2"),
    ("Reject case 4500000091-10: too expensive", "REJECT", "4500000091-10", "too expensive"),
    ("reject 4500000091-10", "REJECT", "4500000091-10", None),
    ("status of 4500000091-10?", "STATUS", "4500000091-10", None),
    ("req261031090000-1", "STATUS", "REQ261031090000-1", None),
    ("What needs my approval?", "PENDING", None, None),
    ("show pending approvals", "PENDING", None, None),
    ("Order 1,300 t of chips from Siak Agro Wood", "REQUEST", None, None),
    ("Order chips for Riau-1, pending approval is fine", "REQUEST", None, None),
])
def test_parse(text, kind, case_id, reason):
    cmd = parse(text)
    assert (cmd.kind, cmd.case_id, cmd.reason) == (kind, case_id, reason)


def test_claimed_user_from_forwarded_token():
    assert claimed_user({"authorization": jwt({"user_name": "dewi@mill.example"})}) == "dewi@mill.example"
    assert claimed_user({"authorization": jwt({"sub": "P000123"})}) == "P000123"
    assert claimed_user({"authorization": "Bearer not-a-jwt"}) is None
    assert claimed_user({"authorization": "Bearer a.%%%.c"}) is None
    assert claimed_user({}) is None


# --- chat flows against the real API ------------------------------------------------------------

def test_planner_sees_and_approves_an_escalated_case(api):
    api.client.post("/demo/scenarios/SC-01/run?wait=true")
    pending = handle("What needs my approval?", "dewi", api)
    assert "1 case waiting" in pending and "4500000091-10" in pending and "$8,280" in pending

    status = handle("status of 4500000091-10", "dewi", api)
    assert "Needs your approval" in status and "Reply **approve 4500000091-10**" in status
    assert "Stock transfer of 920 t from plant 1200 to plant 1100" in status
    assert "(https://synapse.example/console/?case=4500000091-10)" in status

    approved = handle("approve 4500000091-10", "dewi", api)
    assert "Executed" in approved and "joule:dewi" in approved and "SAP document" in approved
    assert "not waiting for a decision" in handle("approve 4500000091-10", "dewi", api)
    assert handle("what needs my approval", None, api) == "✅ Nothing is waiting for your approval."


def test_rejection_needs_a_reason(api):
    api.client.post("/demo/scenarios/SC-01/run?wait=true")
    assert "Please give a reason" in handle("reject 4500000091-10", "dewi", api)
    rejected = handle("reject 4500000091-10 because we will slow down line 2", "dewi", api)
    assert "Rejected" in rejected and "joule:dewi" in rejected


def test_buyer_request_for_blocked_supplier(api):
    reply = handle("Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood", "buyer01", api)
    assert reply.startswith("**⛔ Blocked by policy**")
    assert "DENY" in reply and "EUDR" in reply and "Best compliant alternative" in reply


def test_unknown_case(api):
    assert "can't find case **4599999999-10**" in handle("approve 4599999999-10", "dewi", api)


def test_api_unreachable_is_a_readable_reply():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)
    api = SynapseApi(httpx.Client(base_url="http://api.invalid", transport=httpx.MockTransport(boom)))
    assert "not reachable" in handle("what needs my approval?", "dewi", api)


def test_pending_without_console_link():
    assert render_pending([]) == "✅ Nothing is waiting for your approval."


# --- A2A protocol, as Joule calls it --------------------------------------------------------------

def test_a2a_agent_card_and_message_send(api):
    api.client.post("/demo/scenarios/SC-01/run?wait=true")
    a2a = TestClient(create_app(api, url="https://joule-agent.example"))
    card = a2a.get("/.well-known/agent-card.json").json()
    assert card["name"] == "SynapseSupply" and card["url"] == "https://joule-agent.example"
    assert {s["id"] for s in card["skills"]} == {"source", "approve"}

    r = a2a.post("/", headers={"authorization": jwt({"user_name": "dewi"})}, json={
        "jsonrpc": "2.0", "id": "1", "method": "message/send",
        "params": {"message": {"kind": "message", "role": "user", "messageId": "m-1",
                               "parts": [{"kind": "text", "text": "approve 4500000091-10"}]}}})
    task = r.json()["result"]
    assert task["status"]["state"] == "completed"
    text = task["artifacts"][0]["parts"][0]["text"]  # the path the Joule function reads
    assert "Executed" in text and "joule:dewi" in text
    assert a2a.get("/health").json() == {"status": "ok"}


# --- capability files ---------------------------------------------------------------------------

def test_capability_files_are_consistent():
    da = yaml.safe_load((JOULE_DIR / "da.sapdas.yaml").read_text())
    folder = JOULE_DIR / da["capabilities"][0]["folder"]
    cap = yaml.safe_load((folder / "capability.sapdas.yaml").read_text())
    aliases = set(cap["system_aliases"])
    functions = {p.stem for p in (folder / "functions").glob("*.yaml")}
    for scenario in (folder / "scenarios").glob("*.yaml"):
        target = yaml.safe_load(scenario.read_text())["target"]
        assert target["type"] == "function" and target["name"] in functions, scenario.name
    for fn in (folder / "functions").glob("*.yaml"):
        actions = yaml.safe_load(fn.read_text())["action_groups"][0]["actions"]
        request = next(a for a in actions if a["type"] == "agent-request")
        assert request["system_alias"] in aliases and request["agent_type"] == "remote"
        assert "artifacts[0].parts[0].text" in next(a for a in actions if a["type"] == "message")["message"]["content"]


def test_a2a_endpoint_requires_access_key(api):
    a2a = TestClient(create_app(api, url="https://joule-agent.example", access_key="a2a-secret"))
    assert a2a.get("/health").status_code == 200
    denied = a2a.get("/.well-known/agent-card.json")
    assert denied.status_code == 401 and denied.headers["www-authenticate"].startswith("Basic")
    assert a2a.get("/.well-known/agent-card.json", headers={"x-api-key": "a2a-secret"}).status_code == 200
    basic = "Basic " + base64.b64encode(b"joule:a2a-secret").decode()
    assert a2a.get("/.well-known/agent-card.json", headers={"authorization": basic}).status_code == 200
    wrong = "Basic " + base64.b64encode(b"joule:nope").decode()
    assert a2a.post("/", headers={"authorization": wrong}, json={}).status_code == 401


@pytest.mark.parametrize("text, kind, case_id", [
    ("Please check the status of case 4500000091-10 for me", "STATUS", "4500000091-10"),
    ("User: approve 4500000091-10", "APPROVE", "4500000091-10"),
    ("What needs my approval?\napprove 4500000091-10", "APPROVE", "4500000091-10"),  # newest line wins
    ("approve 4500000091-10\nstatus of 4500000095-10", "STATUS", "4500000095-10"),
    ("I want to reject the case 4500000091-10 because line 2 slows down", "REJECT", "4500000091-10"),
    ("Order 1,300 t of chips; is 4500000091-10 related?", "REQUEST", None),
])
def test_parse_wrapped_messages(text, kind, case_id):
    cmd = parse(text)
    assert (cmd.kind, cmd.case_id) == (kind, case_id)


def test_denied_request_is_not_shown_as_an_action():
    from synapse.joule.bridge import render_case
    reply = render_case({"case_id": "REQ1-1", "status": "BLOCKED", "summary": "Denied.",
                         "proposal": {"action_type": "CREATE_PURCHASE_ORDER", "quantity": 1300, "unit": "TO",
                                      "material": "WC-ACACIA", "supplier": "0000100003", "plant": "1100",
                                      "delivery_date": "2026-11-01", "financial_impact_usd": 0, "confidence": 0.97,
                                      "compliance_outcome": "BLOCK", "alternatives": [
                                          {"description": "STO:1200", "reason": "x" * 200}]},
                         "policy": {"effect": "DENY", "reasons": ["BLOCKED"]}})
    assert "**Requested (not executed):**" in reply and "**Action:**" not in reply
    assert "x" * 71 not in reply and "…" in reply


@pytest.mark.parametrize("raw, expected", [
    ('"approve 4500000091-10"', "approve 4500000091-10"),          # what Joule actually sends
    ('{"user_request": "status of X-1"}', "status of X-1"),
    ("approve 4500000091-10", "approve 4500000091-10"),
    ('{"other": 1}', '{"other": 1}'),
    ("42", "42"),
])
def test_unwrap_joule_text(raw, expected):
    from synapse.joule.server import unwrap
    assert unwrap(raw) == expected


def test_a2a_with_joule_quoted_text(api):
    api.client.post("/demo/scenarios/SC-01/run?wait=true")
    a2a = TestClient(create_app(api, url="https://joule-agent.example"))
    r = a2a.post("/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": {
        "kind": "message", "role": "user", "messageId": "m-q", "metadata": {"user-language": "en"},
        "parts": [{"kind": "text", "text": '"approve 4500000091-10"'}]}}})
    assert "Executed" in r.json()["result"]["artifacts"][0]["parts"][0]["text"]


def test_reply_carries_button_data(api):
    from synapse.joule.bridge import respond
    api.client.post("/demo/scenarios/SC-01/run?wait=true")
    pending = respond("What needs my approval?", "dewi", api)
    assert pending.data == {"case_id": "4500000091-10", "status": "AWAITING_APPROVAL", "awaiting_approval": True}
    done = respond("approve 4500000091-10", "dewi", api)
    assert done.data["awaiting_approval"] is False and done.data["status"] == "EXECUTED"
    assert respond("approve 4599999999-10", "dewi", api).data["case_id"] is None


def test_a2a_artifact_has_text_then_data(api):
    api.client.post("/demo/scenarios/SC-01/run?wait=true")
    a2a = TestClient(create_app(api, url="https://joule-agent.example"))
    r = a2a.post("/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": {
        "kind": "message", "role": "user", "messageId": "m-d", "parts": [{"kind": "text", "text": '"status of 4500000091-10"'}]}}})
    parts = r.json()["result"]["artifacts"][0]["parts"]
    assert parts[0]["kind"] == "text" and parts[1]["kind"] == "data"
    assert parts[1]["data"]["awaiting_approval"] is True and parts[1]["data"]["case_id"] == "4500000091-10"


def test_quick_reply_buttons_send_commands_the_agent_understands():
    fn = yaml.safe_load((JOULE_DIR / "synapse_capability" / "functions" / "ask_synapse.yaml").read_text())
    quick = next(a for g in fn["action_groups"] for a in g["actions"] if a["type"] == "message"
                 and a["message"]["type"] == "quickReplies")
    for button in quick["message"]["content"]["buttons"]:
        value = button["value"].replace("<? apiResponse.body.artifacts[0].parts[1].data.case_id ?>", "4500000091-10")
        assert parse(value).kind in ("APPROVE", "STATUS") and parse(value).case_id == "4500000091-10"
