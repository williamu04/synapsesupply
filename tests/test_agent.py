"""End-to-end case handling with the deterministic planner (no model), plus tool guardrails."""
import httpx
import pytest
from agent_helpers import TODAY, build_service, kinds, message, scenario, writes

from synapse.agent.service import CaseStateError
from synapse.agent.toolkit import CaseToolkit, ToolError
from synapse.agent.trace import Tracer
from synapse.contracts import ActionType, CaseStatus, GateOutcome, PolicyEffect, TraceKind
from synapse.erp import ErpClient
from synapse.policy.engine import PolicyEngine


def test_sc01_escalates_compliant_transfer_then_approval_executes(client):
    service = build_service(client)
    record = service.handle(message(scenario(client, "SC-01")))
    assert record.status is CaseStatus.AWAITING_APPROVAL
    p = record.proposal
    assert (p.action_type, p.option_id, p.supplying_plant, p.quantity) == (
        ActionType.CREATE_STOCK_TRANSFER, "STO:1200", "1200", 920)
    assert p.financial_impact_usd == 8_280 and p.confidence == 0.97
    assert record.policy.effect is PolicyEffect.ESCALATE
    rejected = {a.description: a for a in p.alternatives}
    assert rejected["PO:0000100003"].compliance_outcome is GateOutcome.BLOCK
    assert rejected["PO:0000100005"].compliance_outcome is GateOutcome.HOLD
    assert writes(client) == []  # nothing happens in S/4 before a human approves

    done = service.approve(record.case_id, "Planner Dewi")
    assert done.status is CaseStatus.EXECUTED and done.approver == "Planner Dewi"
    [w] = writes(client)
    assert w["op"] == "CREATE" and w["payload"]["PurchaseOrderType"] == "UB" and w["payload"]["SupplyingPlant"] == "1200"
    assert w["key"]["PurchaseOrder"] == done.sap_document
    with pytest.raises(CaseStateError):
        service.approve(record.case_id, "Planner Dewi")


def test_sc01_rejection_changes_nothing(client):
    service = build_service(client)
    record = service.handle(message(scenario(client, "SC-01")))
    rejected = service.reject(record.case_id, "Planner Dewi", "Prefer to slow down line 2 instead")
    assert rejected.status is CaseStatus.REJECTED and writes(client) == []
    assert service.trace(record.case_id)[-2].kind is TraceKind.APPROVAL


def test_sc02_executes_autonomously(client):
    record = build_service(client).handle(message(scenario(client, "SC-02")))
    assert record.status is CaseStatus.EXECUTED and record.policy.effect is PolicyEffect.ALLOW
    assert (record.proposal.supplier, record.proposal.quantity, record.proposal.financial_impact_usd) == (
        "0000100004", 430, 2_150)
    [w] = writes(client)
    assert w["payload"]["Supplier"] == "0000100004" and w["key"]["PurchaseOrder"] == record.sap_document


def test_sc03_request_for_blocked_supplier_is_denied(client):
    service = build_service(client)
    record = service.handle(message(scenario(client, "SC-03")))
    assert record.status is CaseStatus.BLOCKED and record.policy.effect is PolicyEffect.DENY
    assert record.policy.policy_ids == ["Policy-ComplianceBlock"]
    assert "Best compliant alternative" in record.summary and writes(client) == []
    triage = next(e for e in service.trace(record.case_id) if e.title == "Request triaged")
    assert triage.detail["supplier_name"] == "Siak Agro Wood"


def test_delay_absorbed_by_stock_needs_no_action(client):
    sc = scenario(client, "SC-01", apply=False)  # baseline: same case, ASN not delayed
    record = build_service(client).handle(message(sc))
    assert record.status is CaseStatus.NO_ACTION_NEEDED and record.proposal is None and writes(client) == []


def test_trace_is_ordered_and_complete(client):
    service = build_service(client)
    record = service.handle(message(scenario(client, "SC-02")))
    events = service.trace(record.case_id)
    assert [e.seq for e in events] == list(range(len(events)))
    k = kinds(events)
    assert k[0] is TraceKind.PLAN and k[-1] is TraceKind.DONE
    assert k.index(TraceKind.POLICY) < k.index(TraceKind.ACTION)
    assert k.count(TraceKind.TOOL_CALL) == k.count(TraceKind.TOOL_RESULT) == 5  # 4 agent tools + RPT-1
    assert [e.title for e in events if e.kind is TraceKind.TOOL_CALL].count("predict_delivery_delay") == 1
    assert events[-1].detail["planner"] == "autopilot"


def test_duplicate_case_is_rejected(client):
    service = build_service(client)
    sc = scenario(client, "SC-02")
    service.handle(message(sc))
    with pytest.raises(CaseStateError):
        service.handle(message(sc))


def test_erp_outage_without_fallback_fails_the_case_visibly(client):
    sc = scenario(client, "SC-02")
    client.post("/admin/faults", json={"error_rate": 1.0})
    service = build_service(client)
    record = service.handle(message(sc))
    assert record.status is CaseStatus.FAILED and "503" in record.summary
    errors = [e for e in service.trace(record.case_id) if e.kind is TraceKind.ERROR]
    assert errors and errors[0].title == "get_case_details: ERP error"


def test_failover_to_mock_erp_lowers_confidence_and_hands_over_to_a_human(client):
    def boom(request):
        raise httpx.ConnectError("refused", request=request)
    primary = httpx.Client(base_url="http://s4.invalid", transport=httpx.MockTransport(boom))
    service = build_service(client, erp_factory=lambda cb: ErpClient(primary, fallback=client, on_failover=cb))
    record = service.handle(message(scenario(client, "SC-02")))
    # Same plan as SC-02, but on degraded data the agent may not act alone
    assert record.proposal.option_id == "PO:0000100004" and record.proposal.confidence == 0.87
    assert record.status is CaseStatus.AWAITING_APPROVAL and writes(client) == []
    assert any(e.title.startswith("DEGRADED") for e in service.trace(record.case_id))


# --- tool guardrails -------------------------------------------------------------------------------

@pytest.fixture
def kit(client) -> CaseToolkit:
    sc = scenario(client, "SC-01")
    return CaseToolkit(message(sc), ErpClient(client), PolicyEngine(), Tracer(sc["case_id"]), TODAY)


def test_submit_requires_a_computed_option(kit):
    with pytest.raises(ToolError, match="find_sourcing_options first"):
        kit.submit_action("PO:0000100004", 920, "made up")


def test_submit_respects_max_quantity_and_only_once(kit):
    kit.get_case_details()
    kit.find_sourcing_options("1100", "WC-ACACIA", 920, "2026-11-02")
    with pytest.raises(ToolError, match="at most"):
        kit.submit_action("STO:1200", 1_600, "too much")
    kit.submit_action("STO:1200", 920, "ok")
    with pytest.raises(ToolError, match="already decided"):
        kit.submit_action("STO:1200", 920, "again")


def test_cannot_close_a_case_that_breaches_safety_stock(kit):
    kit.get_case_details()
    kit.analyze_stock_position("1100", "WC-ACACIA")
    with pytest.raises(ToolError, match="Cannot close"):
        kit.close_without_action("looks fine to me")


def test_supplier_lookup_by_name(kit):
    assert kit.check_supplier_compliance("siak agro", 100)["outcome"] == "BLOCK"
    with pytest.raises(ToolError, match="ambiguous"):
        kit.check_supplier_compliance("a", 100)
    with pytest.raises(ToolError, match="unknown"):
        kit.check_supplier_compliance("Nonexistent Timber", 100)


def test_bad_needed_by_date(kit):
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        kit.find_sourcing_options("1100", "WC-ACACIA", 100, "next tuesday")


def test_analysis_reports_inventory_position_against_reorder_point(kit):
    a = kit.analyze_stock_position("1100", "WC-ACACIA")
    assert a["inventory_position"] == pytest.approx(a["on_hand_unrestricted"] + a["open_inbound"])
    assert a["on_hand_unrestricted"] < a["reorder_point"] < a["inventory_position"]  # covered by open POs
    assert a["below_reorder_point"] is False
