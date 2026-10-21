from datetime import UTC, date, datetime

from starlette.testclient import TestClient

from synapse.agent.cases import InMemoryCaseRepository
from synapse.agent.service import CaseService
from synapse.contracts import CaseMessage, TraceKind
from synapse.erp import ErpClient
from synapse.policy.engine import PolicyEngine

TODAY = date(2026, 10, 31)
_POLICY = PolicyEngine()  # parsing + schema validation once per test session


def build_service(client: TestClient, planner_model=None, erp_factory=None, triage_model=None) -> CaseService:
    return CaseService(erp_factory=erp_factory or (lambda cb: ErpClient(client, on_failover=cb)), policy=_POLICY,
                       repo=InMemoryCaseRepository(), business_date=lambda: TODAY,
                       planner_model=(lambda: planner_model) if planner_model is not None else None,
                       triage_model=(lambda: triage_model) if triage_model is not None else None)


def scenario(client: TestClient, sid: str, apply: bool = True) -> dict:
    sc = next(s for s in client.get("/admin/scenarios").json()["scenarios"] if s["scenario_id"] == sid)
    if apply:
        assert client.post(f"/admin/scenarios/{sid}/apply").status_code == 200
    return sc


def message(sc: dict, case_id: str | None = None) -> CaseMessage:
    raw = {k: sc[k] for k in ("carrier_notice", "utterance") if sc.get(k)}
    return CaseMessage(case_id=case_id or sc["case_id"] or "REQ261031090000-1", process_type=sc["process_type"],
                       payload_source=sc["payload_source"], timestamp=datetime(2026, 10, 31, 9, tzinfo=UTC),
                       raw_payload=raw)


def writes(client: TestClient) -> list[dict]:
    return client.get("/admin/audit").json()["writes"]


def kinds(events) -> list[TraceKind]:
    return [e.kind for e in events]
