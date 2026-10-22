"""Case and trace persistence. On AWS these are the DynamoDB tables `SynapseSupplyCases` and
`SynapseSupplyTrace` (`synapse.aws_store`); the in-memory implementations serve local runs and tests
with the same interfaces, and act as the fallback when DynamoDB is unreachable."""
from collections.abc import Callable
from typing import Protocol

from synapse.contracts import CaseRecord, TraceEvent

# Called with a case's final record and full trace, e.g. to write an audit file to S3.
Archive = Callable[[CaseRecord, list[TraceEvent]], None]


class CaseRepository(Protocol):
    def get(self, case_id: str) -> CaseRecord | None: ...
    def put(self, record: CaseRecord) -> None: ...
    def list(self) -> list[CaseRecord]: ...
    def clear(self) -> None: ...


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self._items: dict[str, CaseRecord] = {}

    def get(self, case_id: str) -> CaseRecord | None:
        record = self._items.get(case_id)
        return record.model_copy(deep=True) if record else None

    def put(self, record: CaseRecord) -> None:
        self._items[record.case_id] = record.model_copy(deep=True)

    def list(self) -> list[CaseRecord]:
        return sorted((r.model_copy(deep=True) for r in self._items.values()), key=lambda r: r.created_at)

    def clear(self) -> None:
        self._items.clear()


class TraceStore(Protocol):
    def append(self, event: TraceEvent) -> None: ...
    def events(self, case_id: str) -> list[TraceEvent]: ...
    def clear(self) -> None: ...


class InMemoryTraceStore:
    def __init__(self) -> None:
        self._events: dict[str, list[TraceEvent]] = {}

    def append(self, event: TraceEvent) -> None:
        self._events.setdefault(event.case_id, []).append(event)

    def events(self, case_id: str) -> list[TraceEvent]:
        return list(self._events.get(case_id, []))

    def clear(self) -> None:
        self._events.clear()
