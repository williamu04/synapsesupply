"""Case lifecycle: receive -> triage -> plan -> policy -> execute | escalate -> approve | reject.

Planning runs the LLM agent (Strands) when a model is configured. If the model is unreachable,
raises, or finishes without a decision, the deterministic autopilot completes the case through the
same tools — the trace records the switch, so a degraded run is never silent.
"""
from collections.abc import Callable
from datetime import UTC, date, datetime

from strands import Agent
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import MessageAddedEvent
from strands.models import Model, ModelRouter

from synapse.contracts import (
    ActionType,
    CaseMessage,
    CaseRecord,
    CaseStatus,
    PolicyAction,
    PolicyContext,
    PolicyEffect,
    PolicyRequest,
    ProcessType,
    TraceEvent,
    TraceKind,
)
from synapse.domain.delays import DelayPredictor
from synapse.erp import ErpClient
from synapse.policy.engine import PolicyEngine

from . import autopilot
from .cases import CaseRepository
from .config import Settings
from .models import retry_strategy
from .prompts import SOP_FILES, system_prompt
from .scenarios import new_request_case_id  # noqa: F401 — re-export
from .toolkit import CaseToolkit, execute
from .trace import Sink, Tracer
from .triage import triage

ErpFactory = Callable[[Callable[[str], None]], ErpClient]  # receives the failover callback
_POLICY_ACTION = {
    ActionType.CREATE_PURCHASE_ORDER: PolicyAction.CREATE_PURCHASE_ORDER,
    ActionType.CREATE_STOCK_TRANSFER: PolicyAction.CREATE_STOCK_TRANSFER,
    ActionType.RESCHEDULE_PO_LINE: PolicyAction.RESCHEDULE_PO_LINE,
}


class CaseStateError(RuntimeError):
    pass


def plain_summary(text: str) -> str:
    """Model summaries are shown in the console (plain text) and Joule (markdown): drop heading
    markers and horizontal rules so both read cleanly. Bold and lists are kept."""
    lines = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped and set(stripped) <= {"-", "*", "_"} and len(stripped) >= 3:
            continue  # horizontal rule
        lines.append(line.lstrip("#").strip() if stripped.startswith("#") else line)
    return "\n".join(lines).strip()


class _ReasoningTrace(HookProvider):
    """Streams the model's own words between tool calls into the trace (REASONING events)."""

    def __init__(self, tracer: Tracer):
        self.tracer = tracer

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(MessageAddedEvent, self._on_message)

    def _on_message(self, event: MessageAddedEvent) -> None:
        if event.message.get("role") != "assistant":
            return
        text = " ".join(b["text"].strip() for b in event.message.get("content", []) if b.get("text", "").strip())
        if text:
            self.tracer.emit(TraceKind.REASONING, "Agent", text=text[:2000])


class CaseService:
    def __init__(self, *, erp_factory: ErpFactory, policy: PolicyEngine, repo: CaseRepository,
                 business_date: Callable[[], date], settings: Settings | None = None,
                 planner_model: Callable[[], Model | ModelRouter] | None = None,
                 triage_model: Callable[[], Model] | None = None, sinks: list[Sink] | None = None,
                 delay_predictor: DelayPredictor | None = None):
        self.erp_factory, self.policy, self.repo = erp_factory, policy, repo
        self.business_date, self.settings = business_date, settings or Settings()
        self.planner_model, self.triage_model = planner_model, triage_model
        self.sinks = list(sinks or [])
        self.delay_predictor = delay_predictor
        self._tracers: dict[str, Tracer] = {}

    def trace(self, case_id: str) -> list[TraceEvent]:
        return list(self._tracer(case_id).events)

    def clear(self) -> None:
        """Forget all cases and traces (demo resets only)."""
        self.repo.clear()
        self._tracers.clear()

    # --- intake and planning --------------------------------------------------------------------

    def handle(self, msg: CaseMessage) -> CaseRecord:
        if self.repo.get(msg.case_id) is not None:
            raise CaseStateError(f"Case {msg.case_id} already exists")  # FIFO dedup should prevent this
        now = datetime.now(UTC)
        tracer = self._tracer(msg.case_id)
        record = CaseRecord(case_id=msg.case_id, process_type=msg.process_type, payload_source=msg.payload_source,
                            status=CaseStatus.ANALYZING, created_at=now, updated_at=now,
                            plant=msg.raw_payload.get("plant"), material=msg.raw_payload.get("material"))
        self.repo.put(record)
        erp = self._erp(tracer)
        tracer.emit(TraceKind.PLAN, f"Case received from {msg.payload_source.value}",
                    process_type=msg.process_type.value, sop=SOP_FILES.get(msg.process_type))

        planner, summary = "autopilot", ""
        try:
            if msg.process_type is ProcessType.USER_REQUEST and "triage" not in msg.raw_payload:
                msg = self._triage(msg, erp, tracer)
            kit = CaseToolkit(msg, erp, self.policy, tracer, self.business_date(), self.settings,
                              delay_predictor=self.delay_predictor)
            if self.planner_model is not None:
                summary = self._run_llm(kit, msg, tracer)
                planner = "llm"
            if kit.outcome is None:
                planner, summary = "autopilot", autopilot.run(kit)
        except Exception as e:  # noqa: BLE001 — fail-safe boundary: any error ends the case as FAILED, visibly
            tracer.emit(TraceKind.ERROR, "Case failed", error=f"{type(e).__name__}: {e}")
            return self._finish(record, tracer, status=CaseStatus.FAILED, summary=f"Case failed: {e}", planner=planner)

        o = kit.outcome
        record.proposal, record.policy, record.sap_document = o.proposal, o.decision, o.sap_document
        if record.plant is None and o.proposal:
            record.plant, record.material = o.proposal.plant, o.proposal.material
        return self._finish(record, tracer, status=o.status, summary=summary or o.note, planner=planner)

    def _triage(self, msg: CaseMessage, erp: ErpClient, tracer: Tracer) -> CaseMessage:
        suppliers = [p["SupplierName"] for p in erp.read("SupplierCompliance", select=["Supplier", "SupplierName"])]
        model = self.triage_model() if self.triage_model else None
        result = triage(msg.raw_payload.get("utterance", ""), suppliers=suppliers,
                        plants=self.settings.plant_names, model=model)
        tracer.emit(TraceKind.PLAN, "Request triaged", **result.model_dump(),
                    model=self.settings.triage_model_id if result.method == "model" else None)
        return msg.model_copy(update={"raw_payload": msg.raw_payload | {"triage": result.model_dump()}})

    def _run_llm(self, kit: CaseToolkit, msg: CaseMessage, tracer: Tracer) -> str:
        """Returns the model's summary, or "" when the autopilot must take over."""
        try:
            model = self.planner_model()
            agent = Agent(model=model, tools=kit.tools, system_prompt=system_prompt(msg.process_type),
                          callback_handler=None, hooks=[_ReasoningTrace(tracer)], retry_strategy=retry_strategy(model))
            result = agent(f"Handle case {msg.case_id}. Business date: {kit.today}.\n"
                           f"Case message:\n{msg.model_dump_json(indent=1)}")
            summary = plain_summary(str(result))
        except Exception as e:  # noqa: BLE001 — any model/provider failure hands over to the autopilot
            if kit.outcome is not None:  # decision made; only the summary was lost
                tracer.emit(TraceKind.ERROR, "Model failed after the decision", error=f"{type(e).__name__}: {e}")
                return f"Decision recorded ({kit.outcome.status.value}); the agent summary is unavailable."
            tracer.emit(TraceKind.ERROR, "Model unavailable — deterministic autopilot takes over",
                        error=f"{type(e).__name__}: {e}")
            return ""
        if kit.outcome is None:
            tracer.emit(TraceKind.ERROR, "Agent ended without a decision — deterministic autopilot takes over")
            return ""
        return summary

    # --- human decisions ------------------------------------------------------------------------

    def approve(self, case_id: str, approver: str) -> CaseRecord:
        record = self._awaiting(case_id)
        tracer = self._tracer(case_id)
        p = record.proposal
        decision = self.policy.decide(PolicyRequest(
            principal=f"user:{approver}", action=_POLICY_ACTION[p.action_type], resource="A_PurchaseOrder",
            context=PolicyContext(confidence=p.confidence, financial_impact_usd=p.financial_impact_usd,
                                  compliance_outcome=p.compliance_outcome)), principal=approver)
        tracer.emit(TraceKind.APPROVAL, f"Approval by {approver}: {decision.effect.value}",
                    approver=approver, policy_ids=decision.policy_ids, reasons=decision.reasons)
        record.approver, record.policy = approver, decision
        if decision.effect is not PolicyEffect.ALLOW:
            return self._finish(record, tracer, status=CaseStatus.BLOCKED,
                                summary=f"Approval by {approver} not permitted: " + "; ".join(decision.reasons))
        try:
            document = execute(self._erp(tracer), p, created_by=approver)
        except Exception as e:  # noqa: BLE001 — an approved case must end FAILED, never stuck
            tracer.emit(TraceKind.ERROR, "Execution after approval failed", error=f"{type(e).__name__}: {e}")
            return self._finish(record, tracer, status=CaseStatus.FAILED, summary=f"Approved, but S/4 failed: {e}")
        tracer.emit(TraceKind.ACTION, f"Created {p.action_type.value} {document} in S/4", sap_document=document,
                    approver=approver)
        record.sap_document = document
        return self._finish(record, tracer, status=CaseStatus.EXECUTED,
                            summary=f"Approved by {approver}; S/4 document {document} created.")

    def reject(self, case_id: str, approver: str, reason: str) -> CaseRecord:
        record = self._awaiting(case_id)
        tracer = self._tracer(case_id)
        tracer.emit(TraceKind.APPROVAL, f"Rejected by {approver}", approver=approver, reason=reason)
        record.approver = approver
        return self._finish(record, tracer, status=CaseStatus.REJECTED, summary=f"Rejected by {approver}: {reason}")

    # --- helpers --------------------------------------------------------------------------------

    def _awaiting(self, case_id: str) -> CaseRecord:
        record = self.repo.get(case_id)
        if record is None:
            raise KeyError(f"Unknown case {case_id}")
        if record.status is not CaseStatus.AWAITING_APPROVAL or record.proposal is None:
            raise CaseStateError(f"Case {case_id} is {record.status.value}, not awaiting approval")
        return record

    def _tracer(self, case_id: str) -> Tracer:
        if case_id not in self._tracers:
            self._tracers[case_id] = Tracer(case_id, self.sinks)
        return self._tracers[case_id]

    def _erp(self, tracer: Tracer) -> ErpClient:
        return self.erp_factory(lambda reason: tracer.emit(
            TraceKind.ERROR, "DEGRADED: S/4 unreachable — switched to local mock ERP", reason=reason))

    def _finish(self, record: CaseRecord, tracer: Tracer, *, status: CaseStatus, summary: str,
                planner: str | None = None) -> CaseRecord:
        record.status, record.summary, record.updated_at = status, summary, datetime.now(UTC)
        self.repo.put(record)
        tracer.emit(TraceKind.DONE, status.value, summary=summary, planner=planner, sap_document=record.sap_document)
        return record
