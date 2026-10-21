"""Case persistence. In AWS this is the DynamoDB `Cases` table (partition key `case_id`); the
in-memory implementation serves local runs and tests with the same interface."""
from typing import Protocol

from synapse.contracts import CaseRecord


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
