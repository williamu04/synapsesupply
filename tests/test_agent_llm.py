"""The real Strands agent loop, driven by a scripted model: proves tool wiring, the policy gate on
model decisions, recovery from bad tool calls, and the autopilot fallback."""
from agent_helpers import build_service, kinds, message, scenario, writes
from scripted_model import FailingModel, ScriptedModel, tool_results

from synapse.contracts import CaseStatus, PolicyEffect, TraceKind

SC02_PLAN = [
    [("get_case_details", {})],
    [("analyze_stock_position", {"plant": "1100", "material": "LOG-EUCA"})],
    [("find_sourcing_options", {"plant": "1100", "material": "LOG-EUCA", "quantity": 430, "needed_by": "2026-11-01"})],
    [("submit_action", {"option_id": "PO:0000100004", "quantity": 430,
                        "rationale": "Only compliant supplier arriving by 1 Nov.",
                        "rejected_alternatives": [{"option_id": "PO:0000100002", "reason": "arrives too late"}]})],
    "Ordered 430 m3 of eucalyptus logs from Jambi Pulpwood Estate; arrives 1 Nov.",
]


def test_llm_happy_path_executes_through_policy(client):
    model = ScriptedModel(list(SC02_PLAN))
    service = build_service(client, planner_model=model)
    record = service.handle(message(scenario(client, "SC-02")))
    assert record.status is CaseStatus.EXECUTED
    assert record.summary.startswith("Ordered 430 m3")
    events = service.trace(record.case_id)
    assert events[-1].detail["planner"] == "llm"
    assert TraceKind.REASONING in kinds(events)
    assert record.proposal.alternatives[0].description == "PO:0000100002"
    assert len(writes(client)) == 1
    assert {s["name"] for s in model.tool_specs} == {
        "get_case_details", "analyze_stock_position", "find_sourcing_options", "check_supplier_compliance",
        "submit_action", "close_without_action"}


def test_policy_stops_a_model_that_picks_a_blocked_supplier(client):
    model = ScriptedModel([
        [("get_case_details", {})],
        [("analyze_stock_position", {"plant": "1100", "material": "WC-ACACIA"})],
        [("find_sourcing_options", {"plant": "1100", "material": "WC-ACACIA", "quantity": 920,
                                    "needed_by": "2026-11-02"})],
        [("submit_action", {"option_id": "PO:0000100003", "quantity": 920, "rationale": "Cheapest and fastest."})],
        "Ordered from Siak Agro Wood.",
    ])
    record = build_service(client, planner_model=model).handle(message(scenario(client, "SC-01")))
    assert record.status is CaseStatus.BLOCKED and record.policy.effect is PolicyEffect.DENY
    assert writes(client) == []


def test_model_recovers_from_an_invented_option(client):
    def after_error(messages):
        errors = [r for r in tool_results(messages) if "text" in r and "Unknown option_id" in r["text"]]
        assert errors, "the tool error must reach the model"
        return [("submit_action", {"option_id": "PO:0000100004", "quantity": 430, "rationale": "Valid option."})]

    model = ScriptedModel([
        *SC02_PLAN[:3],
        [("submit_action", {"option_id": "PO:9999999999", "quantity": 430, "rationale": "Invented."})],
        after_error,
        "Done.",
    ])
    record = build_service(client, planner_model=model).handle(message(scenario(client, "SC-02")))
    assert record.status is CaseStatus.EXECUTED and record.proposal.option_id == "PO:0000100004"


def test_second_submission_is_refused(client):
    model = ScriptedModel([
        *SC02_PLAN[:4],
        [("submit_action", {"option_id": "PO:0000100004", "quantity": 430, "rationale": "Again."})],
        "Done.",
    ])
    record = build_service(client, planner_model=model).handle(message(scenario(client, "SC-02")))
    assert record.status is CaseStatus.EXECUTED and len(writes(client)) == 1


def test_model_without_decision_hands_over_to_autopilot(client):
    model = ScriptedModel([[("get_case_details", {})], "I think everything is fine."])
    service = build_service(client, planner_model=model)
    record = service.handle(message(scenario(client, "SC-01")))
    assert record.status is CaseStatus.AWAITING_APPROVAL  # autopilot's decision
    events = service.trace(record.case_id)
    assert any(e.title.startswith("Agent ended without a decision") for e in events)
    assert events[-1].detail["planner"] == "autopilot"


def test_unreachable_model_hands_over_to_autopilot(client):
    service = build_service(client, planner_model=FailingModel())
    record = service.handle(message(scenario(client, "SC-02")))
    assert record.status is CaseStatus.EXECUTED
    assert any(e.title.startswith("Model unavailable") for e in service.trace(record.case_id))


def test_model_summary_is_made_plain(client):
    model = ScriptedModel([*SC02_PLAN[:4], "---\n\n## ✅ Case summary\n\n**Ordered** 430 m3.\n\n---"])
    record = build_service(client, planner_model=model).handle(message(scenario(client, "SC-02")))
    assert record.summary == "✅ Case summary\n\n**Ordered** 430 m3."


def test_tool_results_state_the_currency(client):
    model = ScriptedModel(list(SC02_PLAN))
    service = build_service(client, planner_model=model)
    record = service.handle(message(scenario(client, "SC-02")))
    results = {e.title: e.detail for e in service.trace(record.case_id) if e.kind.value == "TOOL_RESULT"}
    assert results["get_case_details"]["currency"] == "USD"
    assert results["find_sourcing_options"]["currency"] == "USD"
    assert results["submit_action"]["currency"] == "USD"


def test_compliance_reasons_come_from_the_gate_not_the_model(client):
    model = ScriptedModel([
        [("get_case_details", {})],
        [("analyze_stock_position", {"plant": "1100", "material": "WC-ACACIA"})],
        [("find_sourcing_options", {"plant": "1100", "material": "WC-ACACIA", "quantity": 920,
                                    "needed_by": "2026-11-02"})],
        [("submit_action", {"option_id": "STO:1200", "quantity": 920, "rationale": "Transfer.",
                            "rejected_alternatives": [{"option_id": "PO:0000100005",
                                                       "reason": "PEFC expired 20 October 2026"}]})],
        "Done.",
    ])
    record = build_service(client, planner_model=model).handle(message(scenario(client, "SC-01")))
    [alt] = record.proposal.alternatives
    assert alt.reason == "HOLD: PEFC expired 2026-10-11" and "20 October" not in alt.reason
