import json
import time

import pytest
from agent_helpers import build_service, message, scenario
from fastapi.testclient import TestClient

from synapse.agent.trace import JsonlRecorder
from synapse.api.app import DemoControl, create_api


def make_api(client, **kw) -> TestClient:
    service = kw.pop("service", None) or build_service(client)
    return TestClient(create_api(service, demo=kw.pop("demo", DemoControl(client)), **kw))


def frames(text: str) -> list[dict]:
    """Parse an SSE body into [{id, event, data}]; keep-alive comments are dropped."""
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            out.append(fields | {"data": json.loads(fields["data"])})
    return out


def sse(api: TestClient, url: str, **headers) -> list[dict]:
    with api.stream("GET", url, headers=headers) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        return frames("".join(r.iter_text()))


def wait_for(api: TestClient, case_id: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = api.get(f"/cases/{case_id}").json()
        if body["status"] not in ("NEW", "ANALYZING"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"case {case_id} did not finish")


@pytest.fixture
def api(client) -> TestClient:
    return make_api(client)


def test_health(api):
    assert api.get("/health").json() == {"status": "ok", "demo": True, "queued": 0}


def test_case_inline_and_duplicate(api, client):
    msg = message(scenario(client, "SC-02"))
    r = api.post("/cases?wait=true", content=msg.model_dump_json(), headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.json()["status"] == "EXECUTED"
    dup = api.post("/cases", content=msg.model_dump_json(), headers={"content-type": "application/json"})
    assert dup.status_code == 409
    assert [c["case_id"] for c in api.get("/cases").json()] == [msg.case_id]


def test_case_runs_in_background_worker(api, client):
    msg = message(scenario(client, "SC-02"))
    r = api.post("/cases", content=msg.model_dump_json(), headers={"content-type": "application/json"})
    assert r.status_code == 202 and r.json() == {"case_id": msg.case_id, "status": "NEW"}
    assert wait_for(api, msg.case_id)["status"] == "EXECUTED"


def test_invalid_case_message_is_rejected(api):
    assert api.post("/cases", json={"case_id": "nope"}).status_code == 422


def test_sse_replays_trace_and_resumes_from_last_event_id(api, client):
    case_id = api.post("/cases?wait=true", content=message(scenario(client, "SC-02")).model_dump_json(),
                       headers={"content-type": "application/json"}).json()["case_id"]
    events = sse(api, f"/cases/{case_id}/events")
    assert [int(f["id"]) for f in events] == list(range(len(events)))
    assert events[0]["event"] == "PLAN" and events[-1]["event"] == "DONE"
    assert events[-1]["data"]["title"] == "EXECUTED"
    assert api.get(f"/cases/{case_id}/trace").json() == [f["data"] for f in events]
    resumed = sse(api, f"/cases/{case_id}/events", **{"last-event-id": "5"})
    assert [int(f["id"]) for f in resumed] == list(range(6, len(events)))


def test_sse_follows_a_running_case_to_the_end(api, client):
    msg = message(scenario(client, "SC-02"))
    api.post("/cases", content=msg.model_dump_json(), headers={"content-type": "application/json"})
    events = sse(api, f"/cases/{msg.case_id}/events")
    assert events[-1]["event"] == "DONE" and events[-1]["data"]["title"] == "EXECUTED"


def test_approval_flow_over_http(api):
    record = api.post("/demo/scenarios/SC-01/run?wait=true").json()
    case_id = record["case_id"]
    assert record["status"] == "AWAITING_APPROVAL"
    assert record["policy"]["effect"] == "ESCALATE"
    replay = sse(api, f"/cases/{case_id}/events?follow=false")  # not final: replay only
    assert replay[-1]["data"]["title"] == "AWAITING_APPROVAL"

    approved = api.post(f"/cases/{case_id}/approve", json={"approver": "Planner Dewi"})
    assert approved.status_code == 200 and approved.json()["status"] == "EXECUTED"
    assert approved.json()["sap_document"]
    assert api.post(f"/cases/{case_id}/approve", json={"approver": "Planner Dewi"}).status_code == 409
    assert api.post("/cases/4599999999-10/approve", json={"approver": "x"}).status_code == 404
    assert sse(api, f"/cases/{case_id}/events")[-1]["data"]["title"] == "EXECUTED"


def test_rejection_over_http(api):
    case_id = api.post("/demo/scenarios/SC-01/run?wait=true").json()["case_id"]
    r = api.post(f"/cases/{case_id}/reject", json={"approver": "Planner Dewi", "reason": "Slow line 2 instead"})
    assert r.json()["status"] == "REJECTED"
    assert api.post(f"/cases/{case_id}/reject", json={"approver": "x", "reason": ""}).status_code == 422


def test_joule_request(api):
    r = api.post("/requests?wait=true", json={
        "utterance": "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood", "user": "buyer01"})
    body = r.json()
    assert body["status"] == "BLOCKED" and body["case_id"].startswith("REQ")
    assert body["policy"]["policy_ids"] == ["Policy-ComplianceBlock"]


def test_unknown_case(api):
    assert api.get("/cases/4599999999-10").status_code == 404
    assert api.get("/cases/4599999999-10/events").status_code == 404


def test_demo_reset_clears_cases_and_erp(api, client):
    api.post("/demo/scenarios/SC-02/run?wait=true")
    assert api.get("/cases").json() and client.get("/admin/audit").json()["writes"]
    assert api.post("/demo/reset").status_code == 200
    assert api.get("/cases").json() == [] and client.get("/admin/audit").json()["writes"] == []
    assert len(api.get("/demo/scenarios").json()) == 3
    assert api.post("/demo/scenarios/SC-99/run").status_code == 404


def test_demo_routes_need_the_mock(client):
    api = make_api(client, demo=None)
    assert api.get("/demo/scenarios").status_code == 404
    assert api.get("/health").json()["demo"] is False


def test_api_key(client):
    api = make_api(client, api_key="s3cret")
    assert api.get("/health").status_code == 200
    assert api.get("/cases").status_code == 401
    assert api.get("/cases", headers={"x-api-key": "wrong"}).status_code == 401
    assert api.get("/cases", headers={"x-api-key": "s3cret"}).status_code == 200
    assert api.get("/cases?api_key=s3cret").status_code == 200  # EventSource cannot set headers


def test_cors_and_console(client, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>SynapseSupply</title>")
    api = make_api(client, cors_origins=["https://console.example"], ui_dir=tmp_path)
    r = api.options("/cases", headers={"origin": "https://console.example", "access-control-request-method": "GET"})
    assert r.headers["access-control-allow-origin"] == "https://console.example"
    assert "SynapseSupply" in api.get("/console/").text


def test_recording_replay(client, tmp_path):
    service = build_service(client)
    service.sinks.append(JsonlRecorder(tmp_path / "sc02.jsonl"))
    service.handle(message(scenario(client, "SC-02")))
    api = make_api(client, recordings_dir=tmp_path)
    assert api.get("/recordings").json() == ["sc02"]
    events = sse(api, "/recordings/sc02?speed=50")
    assert [f["event"] for f in events][-1] == "DONE" and len(events) == len(service.trace(events[0]["data"]["case_id"]))
    assert api.get("/recordings/..%2Fsecrets").status_code == 404
    assert api.get("/recordings/missing").status_code == 404
    assert api.get("/recordings/sc02?speed=0").status_code == 422


def test_browser_basic_auth_for_console_and_api(client, tmp_path):
    import base64
    (tmp_path / "index.html").write_text("<!doctype html><title>SynapseSupply</title>")
    api = make_api(client, api_key="s3cret", ui_dir=tmp_path)
    r = api.get("/console/")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    good = {"authorization": "Basic " + base64.b64encode(b"planner:s3cret").decode()}
    bad = {"authorization": "Basic " + base64.b64encode(b"planner:wrong").decode()}
    assert "SynapseSupply" in api.get("/console/", headers=good).text
    assert api.get("/cases", headers=good).status_code == 200
    assert api.get("/cases", headers=bad).status_code == 401
    assert api.get("/cases", headers={"authorization": "Basic !!!"}).status_code == 401
    assert api.get("/health").status_code == 200


def _wait_until(fn, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (value := fn()) is not None:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_boot_scenario_is_staged_at_startup(client):
    with TestClient(create_api(build_service(client), demo=DemoControl(client), boot_scenario="SC-01")) as api:
        assert api.get("/health").status_code == 200  # startup does not wait for the case
        case = _wait_until(lambda: next((c for c in api.get("/cases").json()
                                         if c["status"] == "AWAITING_APPROVAL"), None))
        assert case["case_id"] == "4500000091-10"


def test_bad_boot_scenario_does_not_stop_startup(client):
    with TestClient(create_api(build_service(client), demo=DemoControl(client), boot_scenario="SC-99")) as api:
        assert api.get("/health").json()["status"] == "ok"
        time.sleep(0.3)
        assert api.get("/cases").json() == []


def test_shared_s4_is_served_behind_the_key(client):
    api = make_api(client, api_key="k", s4_app=client.app)
    path = "/s4/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002/A_InbDeliveryHeader('180000001')"
    assert api.get(path).status_code == 401
    assert api.get("/s4/health").status_code == 401
    client.post("/admin/scenarios/SC-01/apply")              # the API's own ERP changes ...
    remote = api.get(path, auth=("agentcore", "k"))           # ... and a remote client sees it
    assert remote.status_code == 200
    assert remote.json()["d"]["LastChangeDate"] == client.get(path.removeprefix("/s4")).json()["d"]["LastChangeDate"]
    assert api.get("/s4/health", headers={"x-api-key": "k"}).status_code == 200


def test_s4_not_exposed_by_default(client):
    assert make_api(client).get("/s4/health").status_code == 404


def test_stage_changes_the_erp_without_starting_a_case(client):
    api = make_api(client)
    r = api.post("/demo/scenarios/SC-01/stage")
    assert r.status_code == 200 and r.json()["case_id"] == "4500000091-10"
    assert api.get("/cases").json() == []                       # left to the poller
    assert "SC-01" in client.get("/admin/scenarios").json()["applied"]
