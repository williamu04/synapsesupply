"""Compact, read-only view of a case for the Joule chat surface (see docs/joule.md).

The console renders the full live trace; Joule only needs one stable, small JSON shape it can turn
into a card, a table and a projection chart. Everything here is derived from the CaseRecord and the
trace events the agent already emitted — no new persistence and no I/O.
"""
from typing import Any

from synapse.contracts import CaseRecord, TraceEvent, TraceKind

MAX_OPTIONS = 8

# Compliance outcome -> UI5 Integration Card state (Success | Warning | Error | Information).
_COMPLIANCE_STATE = {"PASS": "Success", "HOLD": "Warning", "BLOCK": "Error",
                     "NOT_APPLICABLE": "Information"}


def _tool_result(events: list[TraceEvent], name: str) -> dict | None:
    for event in reversed(events):
        if event.kind is TraceKind.TOOL_RESULT and event.title == name:
            return event.detail
    return None


def _analysis(record: CaseRecord, events: list[TraceEvent]) -> dict | None:
    candidates = [e.detail for e in events
                  if e.kind is TraceKind.TOOL_RESULT and e.title == "analyze_stock_position"]
    if not candidates:
        return None
    analysis = next((a for a in reversed(candidates)
                     if a.get("plant") == record.plant and a.get("material") == record.material), candidates[-1])
    return {
        "unit": analysis.get("unit"),
        "safety_stock": analysis.get("safety_stock"),
        "projected_minimum": analysis.get("projected_minimum"),
        "first_breach_day": analysis.get("first_breach_day"),
        "shortfall": analysis.get("shortfall"),
        "on_hand_unrestricted": analysis.get("on_hand_unrestricted"),
        # Each point repeats the safety-stock threshold so the Joule chart needs no parent-scope
        # lookup in Handlebars (`{{safety_stock}}` inside the loop).
        "projection": [{"day": p.get("day"), "closing": p.get("closing"), "receipts": p.get("receipts"),
                        "below_safety_stock": p.get("below_safety_stock"),
                        "safety_stock": analysis.get("safety_stock")}
                       for p in analysis.get("projection", [])],
    }


def _options(record: CaseRecord, events: list[TraceEvent]) -> list[dict]:
    found = _tool_result(events, "find_sourcing_options")
    if not found:
        return []
    proposal = record.proposal
    chosen = proposal.option_id if proposal else None
    # RejectedAlternative.description holds the alternative's option_id (see toolkit._submit).
    rejected = {a.description: a.reason for a in (proposal.alternatives if proposal else [])}
    out = []
    for option in found.get("options", [])[:MAX_OPTIONS]:
        option_id = option.get("option_id")
        compliance = option.get("compliance")
        out.append({
            "option_id": option_id,
            "kind": option.get("kind"),
            "source_name": option.get("source_name"),
            "earliest_arrival": option.get("earliest_arrival"),
            "arrives_in_time": option.get("arrives_in_time"),
            "incremental_cost_for_quantity": option.get("incremental_cost_for_quantity"),
            "on_time_probability": option.get("on_time_probability"),
            "compliance": compliance,
            # Precomputed so the Joule function needs no equality helpers in Handlebars.
            "compliance_state": _COMPLIANCE_STATE.get(compliance or "", "Information"),
            "chosen": option_id == chosen,
            "rejected_reason": rejected.get(option_id),
            "outcome": "Chosen" if option_id == chosen
                       else "Rejected" if option_id in rejected else "Considered",
        })
    return out


def _decision(record: CaseRecord) -> dict | None:
    proposal, policy = record.proposal, record.policy
    if proposal is None and policy is None:
        return None
    return {
        "effect": policy.effect.value if policy else None,
        "policy_ids": policy.policy_ids if policy else [],
        "reasons": policy.reasons if policy else [],
        "action_type": proposal.action_type.value if proposal else None,
        "plant": record.plant,
        "material": record.material,
        "quantity": proposal.quantity if proposal else None,
        "unit": proposal.unit if proposal else None,
        "delivery_date": proposal.delivery_date.isoformat() if proposal else None,
        "supplier": proposal.supplier if proposal else None,
        "supplying_plant": proposal.supplying_plant if proposal else None,
        "option_id": proposal.option_id if proposal else None,
        "confidence": proposal.confidence if proposal else None,
        "financial_impact_usd": proposal.financial_impact_usd if proposal else None,
        "compliance": proposal.compliance_outcome.value if proposal and proposal.compliance_outcome else None,
        "rationale": proposal.rationale if proposal else None,
    }


def case_view(record: CaseRecord, events: list[TraceEvent]) -> dict[str, Any]:
    """The JSON shape `GET /cases/{id}/view` returns and the Joule DataPart carries."""
    return {
        "case_id": record.case_id,
        "status": record.status.value,
        "process_type": record.process_type.value,
        "source": record.payload_source.value,
        "summary": record.summary,
        "approver": record.approver,
        "sap_document": record.sap_document,
        "decision": _decision(record),
        "analysis": _analysis(record, events),
        "options": _options(record, events),
    }
