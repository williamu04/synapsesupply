import json

import boto3
import pytest
from agent_helpers import TODAY, message, scenario
from moto import mock_aws

from synapse.agent.service import CaseService
from synapse.aws_store import (
    DynamoCaseRepository,
    DynamoTraceStore,
    FallbackCaseRepository,
    FallbackTraceStore,
    S3Archive,
    stores_from_env,
)
from synapse.contracts import CaseStatus, TraceKind
from synapse.erp import ErpClient
from synapse.policy.engine import PolicyEngine

REGION = "ap-southeast-2"


@pytest.fixture
def aws(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_REGION", REGION)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(TableName="Cases", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}])
        ddb.create_table(TableName="Trace", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"},
                                               {"AttributeName": "seq", "AttributeType": "N"}],
                         KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"},
                                    {"AttributeName": "seq", "KeyType": "RANGE"}])
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="audit", CreateBucketConfiguration={"LocationConstraint": REGION})
        s3.put_bucket_versioning(Bucket="audit", VersioningConfiguration={"Status": "Enabled"})
        yield ddb, s3


_POLICY = PolicyEngine()


def _service(client, policy=_POLICY) -> CaseService:
    """A separate process' view: its own memory fallback, the shared tables and bucket."""
    return CaseService(erp_factory=lambda cb: ErpClient(client, on_failover=cb), policy=policy,
                       repo=FallbackCaseRepository(DynamoCaseRepository("Cases")),
                       trace_store=FallbackTraceStore(DynamoTraceStore("Trace")),
                       archive=S3Archive("audit"), business_date=lambda: TODAY)


def test_case_handled_in_one_process_is_approved_in_another(aws, client):
    _, s3 = aws
    agentcore, api = _service(client), _service(client)
    sc = scenario(client, "SC-01")
    record = agentcore.handle(message(sc))
    assert record.status is CaseStatus.AWAITING_APPROVAL

    assert [r.case_id for r in api.repo.list()] == [record.case_id]   # the other process sees it
    assert api.repo.get(record.case_id).status is CaseStatus.AWAITING_APPROVAL
    approved = api.approve(record.case_id, "planner:dewi")
    assert approved.status is CaseStatus.EXECUTED

    events = agentcore.trace(record.case_id)               # the first process sees the approval
    assert [e.seq for e in events] == list(range(len(events)))   # one sequence, no gaps or repeats
    assert [e.kind for e in events][-3:] == [TraceKind.APPROVAL, TraceKind.ACTION, TraceKind.DONE]
    assert agentcore.repo.get(record.case_id).status is CaseStatus.EXECUTED

    key = S3Archive.key(record)
    versions = s3.list_object_versions(Bucket="audit", Prefix=key)["Versions"]
    assert len(versions) == 2                              # escalated, then executed
    latest = json.loads(s3.get_object(Bucket="audit", Key=key)["Body"].read())
    assert latest["record"]["status"] == "EXECUTED" and latest["trace"][-1]["kind"] == "DONE"


def test_reset_clears_shared_tables(aws, client):
    a, b = _service(client), _service(client)
    a.handle(message(scenario(client, "SC-01")))
    b.clear()
    assert a.repo.primary.list() == [] and a.trace_store.primary.events("4500000091-10") == []


class Broken:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("DynamoDB unreachable")
        return fail


def test_unreachable_dynamodb_falls_back_to_memory(client):
    service = CaseService(erp_factory=lambda cb: ErpClient(client, on_failover=cb), policy=PolicyEngine(),
                          repo=FallbackCaseRepository(Broken()), trace_store=FallbackTraceStore(Broken()),
                          archive=Broken().put_object, business_date=lambda: TODAY)
    record = service.handle(message(scenario(client, "SC-01")))
    assert record.status is CaseStatus.AWAITING_APPROVAL
    assert service.repo.get(record.case_id).status is CaseStatus.AWAITING_APPROVAL
    assert service.approve(record.case_id, "planner:dewi").status is CaseStatus.EXECUTED
    assert service.trace(record.case_id)[-1].kind is TraceKind.DONE


def test_stores_from_env(monkeypatch):
    for name in ("SYNAPSE_CASES_TABLE", "SYNAPSE_TRACE_TABLE", "SYNAPSE_AUDIT_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    repo, trace, archive = stores_from_env()
    assert type(repo).__name__ == "InMemoryCaseRepository" and archive is None
    monkeypatch.setenv("SYNAPSE_CASES_TABLE", "Cases")
    monkeypatch.setenv("SYNAPSE_TRACE_TABLE", "Trace")
    monkeypatch.setenv("SYNAPSE_AUDIT_BUCKET", "audit")
    repo, trace, archive = stores_from_env()
    assert isinstance(repo, FallbackCaseRepository) and isinstance(trace, FallbackTraceStore)
    assert isinstance(archive, S3Archive)
