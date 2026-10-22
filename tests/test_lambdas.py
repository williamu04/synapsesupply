import importlib.util
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import boto3
import pytest
from agent_helpers import build_service
from moto import mock_aws

from synapse.agentcore import handle_payload
from synapse.contracts import CaseMessage

ROOT = Path(__file__).resolve().parents[1] / "lambdas"
REGION = "ap-southeast-2"
NOW = datetime(2026, 10, 31, 9, tzinfo=UTC)
SINCE = date(2026, 10, 1)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"lambda_{name}", ROOT / name / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


poller, dispatcher = _load("poller"), _load("dispatcher")


def odata(client):
    """The poller's `get`, served by the in-process mock S/4."""
    return lambda path, params: client.get(path, params=params | {"$format": "json"}).json()


def test_no_delay_before_the_erp_changes(client):
    assert poller.find_delays(odata(client), SINCE) == []


def test_delayed_delivery_becomes_a_case_message(client):
    client.post("/admin/scenarios/SC-01/apply")
    [delay] = poller.find_delays(odata(client), SINCE)
    assert delay["case_id"] == "4500000091-10" and delay["delay_days"] == 3
    assert (delay["planned_date"], delay["new_date"]) == ("2026-11-01", "2026-11-04")
    message = CaseMessage.model_validate(poller.case_message(delay, NOW))   # the agent's own contract
    assert message.payload_source.value == "ODATA_POLLER" and message.raw_payload["plant"] == "1100"


@pytest.fixture
def queue(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        sqs, ddb = boto3.client("sqs", region_name=REGION), boto3.client("dynamodb", region_name=REGION)
        url = sqs.create_queue(QueueName="cases.fifo", Attributes={"FifoQueue": "true"})["QueueUrl"]
        ddb.create_table(TableName="Cases", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}])
        yield sqs, ddb, url


def test_poll_queues_once_per_case(client, queue):
    sqs, ddb, url = queue
    client.post("/admin/scenarios/SC-01/apply")
    assert poller.poll(odata(client), sqs, ddb, url, "Cases", SINCE, NOW)["queued"] == ["4500000091-10"]
    [msg] = sqs.receive_message(QueueUrl=url, AttributeNames=["MessageGroupId"])["Messages"]
    assert msg["Attributes"]["MessageGroupId"] == "4500000091-10"

    ddb.put_item(TableName="Cases", Item={"case_id": {"S": "4500000091-10"}})       # the agent took it
    assert poller.poll(odata(client), sqs, ddb, url, "Cases", SINCE, NOW) == {
        "queued": [], "already_cases": ["4500000091-10"]}


class FakeAgentCore:
    """invoke_agent_runtime, answered by the real runtime entry point."""

    def __init__(self, service):
        self.service, self.calls = service, []

    def invoke_agent_runtime(self, **kw):
        assert len(kw["runtimeSessionId"]) >= 33
        self.calls.append(kw)
        body = handle_payload(json.loads(kw["payload"]), self.service)
        return {"response": io.BytesIO(json.dumps(body, default=str).encode())}


def test_erp_change_to_escalated_case(client):
    client.post("/admin/scenarios/SC-01/apply")
    [delay] = poller.find_delays(odata(client), SINCE)
    agent = FakeAgentCore(build_service(client))
    message = json.loads(json.dumps(poller.case_message(delay, NOW)))      # as it travels through SQS
    assert dispatcher.dispatch(agent, "arn:runtime", message) == {
        "case_id": "4500000091-10", "result": "AWAITING_APPROVAL"}
    assert dispatcher.dispatch(agent, "arn:runtime", message)["result"] == "already handled"   # redelivery


def test_agent_failure_raises_for_sqs_retry():
    class Failing:
        def invoke_agent_runtime(self, **kw):
            return {"response": io.BytesIO(b'{"error": "boom", "code": "failed"}')}
    with pytest.raises(RuntimeError, match="failed"):
        dispatcher.dispatch(Failing(), "arn", {"case_id": "4500000091-10"})


def test_odata_dates():
    assert poller.odata_date("/Date(1793750400000)/") == date(2026, 11, 4)
    assert poller.odata_date(None) is None
