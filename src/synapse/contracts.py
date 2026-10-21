"""Interface contracts between the three workstreams (see docs/contracts.md).

Change a model here only by team agreement: the ingestion pipeline, the agent, the policy layer,
the Joule A2A bridge and the UI all serialize these exact shapes.
"""
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CASE_ID_PATTERN = r"^[A-Z0-9]{4,20}-[0-9]{1,6}$"

# Mirrors Policy-WriteGating in Cedar. Cedar is authoritative; these are for UI copy and tests.
AUTO_EXECUTE_MIN_CONFIDENCE = 0.90
AUTO_EXECUTE_MAX_IMPACT_USD = 5_000.0


def make_case_id(document_number: str, item_id: str | int) -> str:
    """`{document_number}-{item_id}`; S/4 item numbers are normalised ("00010" -> "10")."""
    return f"{document_number.upper()}-{int(item_id)}"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _AwareTimestamp(_Model):
    @field_validator("timestamp", "ts", "created_at", "updated_at", check_fields=False)
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v


# --- Contract 1: case payload (ingestion -> SQS FIFO -> agent; persisted in DynamoDB) -----------

class ProcessType(StrEnum):
    ASN_DELAY = "ASN_DELAY"
    STOCK_BELOW_SAFETY = "STOCK_BELOW_SAFETY"
    SUPPLIER_COMPLIANCE_ALERT = "SUPPLIER_COMPLIANCE_ALERT"
    USER_REQUEST = "USER_REQUEST"


class PayloadSource(StrEnum):
    ODATA_POLLER = "ODATA_POLLER"
    CARRIER_WEBHOOK = "CARRIER_WEBHOOK"
    JOULE_A2A = "JOULE_A2A"
    MANUAL = "MANUAL"


class CaseStatus(StrEnum):
    NEW = "NEW"
    ANALYZING = "ANALYZING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NO_ACTION_NEEDED = "NO_ACTION_NEEDED"  # exception detected, but stock stays above safety stock


class CaseMessage(_AwareTimestamp):
    """SQS FIFO message body. MessageGroupId = case_id, MessageDeduplicationId = case_id + timestamp."""
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    process_type: ProcessType
    payload_source: PayloadSource
    timestamp: datetime
    raw_payload: dict[str, Any]


# --- Agent output and policy ------------------------------------------------------------------

class GateOutcome(StrEnum):
    PASS = "PASS"
    HOLD = "HOLD"
    BLOCK = "BLOCK"


class ActionType(StrEnum):
    RESCHEDULE_PO_LINE = "RESCHEDULE_PO_LINE"
    CREATE_PURCHASE_ORDER = "CREATE_PURCHASE_ORDER"
    CREATE_STOCK_TRANSFER = "CREATE_STOCK_TRANSFER"
    NOTIFY_ONLY = "NOTIFY_ONLY"


class RejectedAlternative(_Model):
    description: str
    reason: str
    compliance_outcome: GateOutcome | None = None
    financial_impact_usd: float | None = None


class ActionProposal(_Model):
    """What the agent wants to do. `financial_impact_usd` is the incremental cost versus the
    original plan (price premium x qty, or freight for a transfer) — not the gross order value."""
    action_type: ActionType
    plant: str
    material: str
    quantity: float = Field(gt=0)
    unit: str
    delivery_date: date
    supplier: str | None = None
    supplying_plant: str | None = None
    reference_document: str | None = None  # PO for RESCHEDULE_PO_LINE, "PO-item-scheduleline"
    option_id: str | None = None  # the computed sourcing option this proposal executes
    financial_impact_usd: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    compliance_outcome: GateOutcome | None = None
    rationale: str
    alternatives: list[RejectedAlternative] = []

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        t = self.action_type
        if t is ActionType.CREATE_PURCHASE_ORDER and not self.supplier:
            raise ValueError("CREATE_PURCHASE_ORDER requires supplier")
        if t is ActionType.CREATE_STOCK_TRANSFER and (not self.supplying_plant or self.supplying_plant == self.plant):
            raise ValueError("CREATE_STOCK_TRANSFER requires a supplying_plant different from plant")
        if t is ActionType.RESCHEDULE_PO_LINE and not self.reference_document:
            raise ValueError("RESCHEDULE_PO_LINE requires reference_document")
        if t is ActionType.CREATE_PURCHASE_ORDER and self.compliance_outcome is None:
            raise ValueError("sourcing from a supplier requires a compliance_outcome from the gate")
        return self


class PolicyAction(StrEnum):
    READ = "sap:read"
    RESCHEDULE_PO_LINE = "sap:reschedule_po_line"
    CREATE_PURCHASE_ORDER = "sap:create_purchase_order"
    CREATE_STOCK_TRANSFER = "sap:create_stock_transfer"
    DELETE = "sap:delete"


class PolicyContext(_Model):
    confidence: float = Field(ge=0, le=1)
    financial_impact_usd: float = Field(ge=0)
    compliance_outcome: GateOutcome | None = None


class PolicyRequest(_Model):
    """Input to the Cedar evaluation (principal, action, resource, context)."""
    principal: str
    action: PolicyAction
    resource: str  # OData entity set, e.g. "A_PurchaseOrder"
    context: PolicyContext


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"        # execute autonomously
    ESCALATE = "ESCALATE"  # not auto-permitted; a human may approve via Joule / UI
    DENY = "DENY"          # forbidden outright (delete, BLOCKed supplier); no approval path


class PolicyDecision(_Model):
    effect: PolicyEffect
    policy_ids: list[str]
    reasons: list[str]


# --- Case record (DynamoDB Cases table) and live trace (SSE) ----------------------------------

class CaseRecord(_AwareTimestamp):
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    process_type: ProcessType
    payload_source: PayloadSource
    status: CaseStatus
    created_at: datetime
    updated_at: datetime
    plant: str | None = None
    material: str | None = None
    summary: str = ""
    proposal: ActionProposal | None = None
    policy: PolicyDecision | None = None
    approver: str | None = None
    sap_document: str | None = None


class TraceKind(StrEnum):
    PLAN = "PLAN"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    REASONING = "REASONING"
    POLICY = "POLICY"
    APPROVAL = "APPROVAL"
    ACTION = "ACTION"
    ERROR = "ERROR"
    DONE = "DONE"


class TraceEvent(_AwareTimestamp):
    """One SSE `data:` frame. `seq` is per case and strictly increasing — the replay mode
    re-emits recorded events in seq order."""
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    seq: int = Field(ge=0)
    ts: datetime
    kind: TraceKind
    title: str
    detail: dict[str, Any] = {}


# --- Contract 2: MCP tool names (agent <-> SAP integration) ------------------------------------

class McpTool(StrEnum):
    FIND_SAP_SERVICES = "sap_mcp:find_sap_services"
    GET_METADATA = "sap_mcp:get_metadata"
    READ_ENTITY = "sap_mcp:read_entity"
    CREATE_ENTITY = "sap_mcp:create_entity"
    UPDATE_ENTITY = "sap_mcp:update_entity"


# --- Contract 3: A2A context (Joule <-> agent) -------------------------------------------------

class A2AContext(_Model):
    """Carried in the A2A v0.3 `message/send` data part. The user's JWT travels in the HTTP
    Authorization header, never in the message body (bodies get logged and traced)."""
    session_id: str
    user_utterance: str
    context_payload: dict[str, Any] = {}
