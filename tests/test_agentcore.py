"""The AgentCore Runtime entry point, served by the real bedrock-agentcore app (Starlette)."""
import pytest
from agent_helpers import build_service, message, scenario
from starlette.testclient import TestClient

pytest.importorskip("bedrock_agentcore")

from synapse.agentcore import create_app
from synapse.api.app import DemoControl


@pytest.fixture
def runtime(client) -> TestClient:
    return TestClient(create_app(build_service(client), demo=DemoControl(client)))


def invoke(runtime: TestClient, payload) -> dict:
    r = runtime.post("/invocations", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_ping(runtime):
    r = runtime.get("/ping")
    assert r.status_code == 200 and r.json()["status"] in ("Healthy", "HealthyBusy")


def test_scenario_then_approve(runtime, client):
    out = invoke(runtime, {"scenario": "SC-01"})
    assert out["case"]["status"] == "AWAITING_APPROVAL" and out["trace"][-1]["kind"] == "DONE"
    done = invoke(runtime, {"approve": "4500000091-10", "approver": "planner:dewi", "include_trace": False})
    assert done["case"]["status"] == "EXECUTED" and "trace" not in done
    assert client.get("/admin/audit").json()["writes"]
    assert invoke(runtime, {"approve": "4500000091-10"})["code"] == "conflict"


def test_case_message_and_status(runtime, client):
    msg = message(scenario(client, "SC-02"))
    out = invoke(runtime, {"case": msg.model_dump(mode="json")})
    assert out["case"]["status"] == "EXECUTED"
    assert invoke(runtime, {"status": msg.case_id})["case"]["case_id"] == msg.case_id
    assert invoke(runtime, {"case": msg.model_dump(mode="json")})["code"] == "conflict"


def test_buyer_request_and_reject_rules(runtime):
    out = invoke(runtime, {"request": "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood"})
    assert out["case"]["status"] == "BLOCKED"
    invoke(runtime, {"scenario": "SC-01"})
    assert invoke(runtime, {"reject": "4500000091-10"})["code"] == "bad_request"
    rejected = invoke(runtime, {"reject": "4500000091-10", "reason": "slow down line 2", "approver": "planner:dewi"})
    assert rejected["case"]["status"] == "REJECTED"


@pytest.mark.parametrize("payload, code", [
    ({}, "bad_request"),
    ({"request": "   "}, "bad_request"),
    ({"case": {"case_id": "nope"}}, "bad_request"),
    ({"status": "4599999999-10"}, "not_found"),
    ({"approve": "4599999999-10"}, "not_found"),
    ({"scenario": "SC-99"}, "failed"),
])
def test_errors_are_replies_not_crashes(runtime, payload, code):
    assert invoke(runtime, payload)["code"] == code


def test_scenarios_need_demo_mode(client):
    runtime = TestClient(create_app(build_service(client), demo=None))
    assert invoke(runtime, {"scenario": "SC-01"})["code"] == "not_available"
