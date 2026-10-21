"""Deterministic planner: the SOPs executed as code, through the same traced tools as the LLM.

Uses:
  * fail-safe — if the model is unreachable or ends without a decision, the case still gets handled
    (and the trace says so);
  * oracle — evals compare the LLM's decision against this one on every scenario.
"""
from datetime import timedelta

from synapse.contracts import ProcessType
from synapse.domain.options import PASSING

from .toolkit import CaseToolkit, round_up


def run(kit: CaseToolkit) -> str:
    details = kit.get_case_details()
    if kit.case.process_type is ProcessType.ASN_DELAY:
        return _asn_delay(kit, details)
    if kit.case.process_type is ProcessType.USER_REQUEST:
        return _user_request(kit, details)
    raise ValueError(f"autopilot has no SOP for {kit.case.process_type.value}")


def _reason(option: dict, chosen: dict, needed_by: str) -> str:
    if option["compliance"] == "BLOCK":
        return "BLOCK: " + "; ".join(option["compliance_findings"])
    if not option["arrives_in_time"]:
        return f"arrives {option['earliest_arrival']}, after needed-by {needed_by}"
    if option["compliance"] == "HOLD":
        return "HOLD: " + "; ".join(option["compliance_findings"])
    if not option["covers_quantity"]:
        return f"can supply at most {option['max_quantity']}"
    return (f"higher incremental cost ${option['incremental_cost_for_quantity']:,.0f} vs "
            f"${chosen['incremental_cost_for_quantity']:,.0f}")


def _asn_delay(kit: CaseToolkit, d: dict) -> str:
    a = kit.analyze_stock_position(d["plant"], d["material"])
    if a["first_breach_day"] is None:
        kit.close_without_action(f"Projected minimum {a['projected_minimum']} {a['unit']} stays above safety stock "
                                 f"{a['safety_stock']} {a['unit']}; the {d['delay_days']}-day delay is absorbed.")
        return f"No action needed: stock stays above safety stock despite the {d['delay_days']}-day delay."

    quantity = round_up(a["shortfall"])
    found = kit.find_sourcing_options(d["plant"], d["material"], quantity, a["first_breach_day"])
    options = found["options"]
    delayed_supplier = f"PO:{d['supplier']}" if d.get("carrier_notice") else None

    def usable(o: dict, allowed: tuple) -> bool:
        return (o["arrives_in_time"] and o["compliance"] in allowed and o["covers_quantity"]
                and o["option_id"] != delayed_supplier)

    chosen = (next((o for o in options if usable(o, PASSING)), None)
              or next((o for o in options if usable(o, ("HOLD",))), None)
              or next((o for o in options if o["compliance"] != "BLOCK" and o["option_id"] != delayed_supplier), None))
    if chosen is None:
        kit.close_without_action("No sourcing option exists that is not BLOCKED; planner must intervene.")
        return "No permissible sourcing option exists; escalated to the planner without an ERP change."

    rejected = [{"option_id": o["option_id"], "reason": "delayed supplier with an active disruption"
                 if o["option_id"] == delayed_supplier else _reason(o, chosen, found["needed_by"])}
                for o in options if o is not chosen]
    result = kit.submit_action(
        chosen["option_id"], quantity,
        f"Stock of {d['material']} at plant {d['plant']} falls to {a['projected_minimum']} {a['unit']} "
        f"(safety stock {a['safety_stock']}) after a {d['delay_days']}-day delay. {chosen['source_name']} "
        f"delivers {quantity:g} {a['unit']} by {chosen['earliest_arrival']}, the earliest compliant option, "
        f"at an incremental ${chosen['incremental_cost_for_quantity']:,.0f}.",
        rejected)
    return _summary(d, a, chosen, quantity, result)


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _summary(d: dict, a: dict, chosen: dict, quantity: float, r: dict) -> str:
    head = (f"{d['supplier_name']}'s delivery for PO {d['purchase_order']} slipped {_days(d['delay_days'])}; "
            f"{d['material']} at plant {d['plant']} would fall to {a['projected_minimum']} {a['unit']} on "
            f"{a['first_breach_day']} (safety stock {a['safety_stock']}).")
    plan = (f"Plan: {chosen['option_id']} ({chosen['source_name']}), {quantity:g} {a['unit']} arriving "
            f"{chosen['earliest_arrival']}, incremental cost ${r['financial_impact_usd']:,.0f}.")
    outcome = {"ALLOW": f"Executed autonomously: S/4 document {r['sap_document']}.",
               "ESCALATE": "Waiting for planner approval in SAP Joule: " + "; ".join(r["reasons"]) + ".",
               "DENY": "Blocked by policy: " + "; ".join(r["reasons"]) + "."}[r["decision"]]
    return f"{head} {plan} {outcome}"


def _user_request(kit: CaseToolkit, d: dict) -> str:
    t = d.get("triage") or {}
    if t.get("intent") != "PURCHASE_REQUEST" or not (t.get("plant") and t.get("material") and t.get("quantity")):
        kit.close_without_action("Request is not a complete purchase request; answered without ERP changes.")
        return "I could not identify a complete purchase request (plant, material and quantity); nothing was ordered."

    plant, material, quantity = t["plant"], t["material"], float(t["quantity"])
    requested = None
    if t.get("supplier_name"):
        requested = kit.check_supplier_compliance(t["supplier_name"], quantity)
    a = kit.analyze_stock_position(plant, material)
    needed_by = a["first_breach_day"] or str(kit.today + timedelta(days=7))
    found = kit.find_sourcing_options(plant, material, quantity, str(needed_by))
    options = found["options"]
    best = next((o for o in options if o["compliance"] in PASSING and o["covers_quantity"]), None)
    alt = (f" Best compliant alternative: {best['option_id']} ({best['source_name']}), arriving "
           f"{best['earliest_arrival']}, incremental ${best['incremental_cost_for_quantity']:,.0f}." if best else "")

    wanted = next((o for o in options if requested and o["option_id"] == f"PO:{requested['supplier']}"), None)
    if wanted is None:
        kit.close_without_action("Requested supplier has no purchasing info record for this plant and material.")
        return f"The requested supplier cannot supply {material} to plant {plant} (no info record).{alt}"

    result = kit.submit_action(wanted["option_id"], quantity, f"Buyer request: {d['utterance']}",
                               [{"option_id": o["option_id"], "reason": "not requested by the buyer"}
                                for o in options if o is not wanted])
    name = requested["supplier_name"]
    if result["decision"] == "ALLOW":
        return f"Ordered {quantity:g} from {name}: S/4 purchase order {result['sap_document']}."
    verb = "Blocked" if result["decision"] == "DENY" else "Sent for approval"
    return f"{verb}: {quantity:g} from {name} — " + "; ".join(result["reasons"]) + "." + alt
