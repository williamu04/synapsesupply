"""Shared case history on AWS: DynamoDB for cases and trace events, S3 for the audit archive.

The API on Cloud Foundry and the agent on AgentCore Runtime read and write the same tables, so a
case handled in one is visible (and approvable) in the other, and the console streams its trace.

Every store is wrapped in a fallback to memory: writes go to both, reads prefer DynamoDB and fall
back to memory when it is unreachable. A DynamoDB outage therefore degrades sharing between
processes, never the demo itself.

Enabled per variable: SYNAPSE_CASES_TABLE, SYNAPSE_TRACE_TABLE, SYNAPSE_AUDIT_BUCKET (region from
AWS_REGION, default ap-southeast-2).
"""
import json
import logging
import os
import threading
import time

from synapse.agent.cases import (
    Archive,
    CaseRepository,
    InMemoryCaseRepository,
    InMemoryTraceStore,
    TraceStore,
)
from synapse.contracts import CaseRecord, TraceEvent

log = logging.getLogger(__name__)
_REGION_DEFAULT = "ap-southeast-2"


def _client(service: str):
    import boto3
    from botocore.config import Config
    return boto3.client(service, region_name=os.environ.get("AWS_REGION") or _REGION_DEFAULT,
                        config=Config(retries={"total_max_attempts": 2, "mode": "standard"},
                                      connect_timeout=3, read_timeout=5))


def _delete_all(client, table: str, key: list[str]) -> None:
    for page in client.get_paginator("scan").paginate(TableName=table, ProjectionExpression=", ".join(key)):
        items = page.get("Items", [])
        for i in range(0, len(items), 25):
            client.batch_write_item(RequestItems={table: [{"DeleteRequest": {"Key": item}} for item in items[i:i + 25]]})


class DynamoCaseRepository:
    """Table: partition key `case_id` (S); the record is stored as JSON in `record`."""

    def __init__(self, table: str, client=None):
        self.table, self.client = table, client or _client("dynamodb")

    def get(self, case_id: str) -> CaseRecord | None:
        item = self.client.get_item(TableName=self.table, Key={"case_id": {"S": case_id}},
                                    ConsistentRead=True).get("Item")
        return CaseRecord.model_validate_json(item["record"]["S"]) if item else None

    def put(self, record: CaseRecord) -> None:
        self.client.put_item(TableName=self.table, Item={
            "case_id": {"S": record.case_id}, "status": {"S": record.status.value},
            "updated_at": {"S": record.updated_at.isoformat()}, "record": {"S": record.model_dump_json()}})

    def list(self) -> list[CaseRecord]:
        records = [CaseRecord.model_validate_json(item["record"]["S"])
                   for page in self.client.get_paginator("scan").paginate(TableName=self.table, ConsistentRead=True)
                   for item in page.get("Items", [])]
        return sorted(records, key=lambda r: r.created_at)

    def clear(self) -> None:
        _delete_all(self.client, self.table, ["case_id"])


class DynamoTraceStore:
    """Table: partition key `case_id` (S), sort key `seq` (N); the event is JSON in `event`."""

    def __init__(self, table: str, client=None):
        self.table, self.client = table, client or _client("dynamodb")

    def append(self, event: TraceEvent) -> None:
        self.client.put_item(TableName=self.table, Item={
            "case_id": {"S": event.case_id}, "seq": {"N": str(event.seq)}, "event": {"S": event.model_dump_json()}})

    def events(self, case_id: str) -> list[TraceEvent]:
        pages = self.client.get_paginator("query").paginate(
            TableName=self.table, KeyConditionExpression="case_id = :c",
            ExpressionAttributeValues={":c": {"S": case_id}}, ConsistentRead=True)
        return [TraceEvent.model_validate_json(item["event"]["S"]) for page in pages for item in page.get("Items", [])]

    def clear(self) -> None:
        _delete_all(self.client, self.table, ["case_id", "seq"])


class S3Archive:
    """Writes `cases/<yyyy>/<mm>/<dd>/<case_id>.json` (final record + full trace) to a versioned
    bucket, so every final state of a case (escalated, then approved) is kept as its own version."""

    def __init__(self, bucket: str, client=None):
        self.bucket, self.client = bucket, client or _client("s3")

    @staticmethod
    def key(record: CaseRecord) -> str:
        return f"cases/{record.created_at:%Y/%m/%d}/{record.case_id}.json"

    def __call__(self, record: CaseRecord, events: list[TraceEvent]) -> None:
        body = json.dumps({"record": record.model_dump(mode="json"),
                           "trace": [e.model_dump(mode="json") for e in events]}, indent=1)
        self.client.put_object(Bucket=self.bucket, Key=self.key(record), Body=body.encode(),
                               ContentType="application/json", ServerSideEncryption="AES256")


class _Degraded:
    """Logs a failing store at most once a minute instead of on every call."""

    def __init__(self, name: str):
        self.name, self._last, self._lock = name, 0.0, threading.Lock()

    def note(self, error: Exception) -> None:
        with self._lock:
            if time.monotonic() - self._last < 60:
                return
            self._last = time.monotonic()
        log.warning("%s unreachable (%s): using local memory", self.name, type(error).__name__)


class FallbackCaseRepository:
    def __init__(self, primary: CaseRepository, fallback: CaseRepository | None = None):
        self.primary, self.fallback = primary, fallback or InMemoryCaseRepository()
        self._degraded = _Degraded("DynamoDB case table")

    def get(self, case_id: str) -> CaseRecord | None:
        try:
            if (record := self.primary.get(case_id)) is not None:
                return record
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)
        return self.fallback.get(case_id)

    def put(self, record: CaseRecord) -> None:
        self.fallback.put(record)
        try:
            self.primary.put(record)
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)

    def list(self) -> list[CaseRecord]:
        merged = {r.case_id: r for r in self.fallback.list()}
        try:
            merged |= {r.case_id: r for r in self.primary.list()}
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)
        return sorted(merged.values(), key=lambda r: r.created_at)

    def clear(self) -> None:
        self.fallback.clear()
        try:
            self.primary.clear()
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)


class FallbackTraceStore:
    def __init__(self, primary: TraceStore, fallback: TraceStore | None = None):
        self.primary, self.fallback = primary, fallback or InMemoryTraceStore()
        self._degraded = _Degraded("DynamoDB trace table")

    def append(self, event: TraceEvent) -> None:
        self.fallback.append(event)
        try:
            self.primary.append(event)
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)

    def events(self, case_id: str) -> list[TraceEvent]:
        local = self.fallback.events(case_id)
        try:
            shared = self.primary.events(case_id)
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)
            return local
        return shared if len(shared) >= len(local) else local

    def clear(self) -> None:
        self.fallback.clear()
        try:
            self.primary.clear()
        except Exception as e:  # noqa: BLE001
            self._degraded.note(e)


def stores_from_env() -> tuple[CaseRepository, TraceStore, Archive | None]:
    """In memory unless the variables are set; each AWS store falls back to memory."""
    cases, trace, bucket = (os.environ.get(n) for n in
                            ("SYNAPSE_CASES_TABLE", "SYNAPSE_TRACE_TABLE", "SYNAPSE_AUDIT_BUCKET"))
    repo: CaseRepository = FallbackCaseRepository(DynamoCaseRepository(cases)) if cases else InMemoryCaseRepository()
    store: TraceStore = FallbackTraceStore(DynamoTraceStore(trace)) if trace else InMemoryTraceStore()
    return repo, store, (S3Archive(bucket) if bucket else None)
