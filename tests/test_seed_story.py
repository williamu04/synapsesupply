"""The dataset must tell the demo story. If someone edits the generator and a scenario stops making
its point (e.g. the hero case no longer needs human approval), these tests fail."""
import json
from datetime import timedelta

import pytest

from synapse.contracts import AUTO_EXECUTE_MAX_IMPACT_USD, CaseMessage, make_case_id
from synapse.data.generate import DEMO_DAY, generate
from synapse.domain import compliance, inventory, supply
from synapse.mock_s4.store import Store

HORIZON = 7
SERVICE_LEVEL = 0.95


def plan_inputs(store: Store, plant: str, material: str):
    rows, d0 = store.rows, store.as_of
    demand = inventory.series_stats(supply.daily_consumption(
        rows["A_MaterialDocumentItem"], plant, material, d0 - timedelta(days=90), d0 - timedelta(days=1)))
    lead = inventory.series_stats(supply.lead_times(rows["A_PurchaseOrder"], rows["A_MaterialDocumentItem"],
                                                    plant, material))
    ss = inventory.safety_stock(inventory.z_for_service_level(SERVICE_LEVEL), lead.mean, demand.sd,
                                demand.mean, lead.sd)
    receipts = supply.expected_receipts(rows["A_PurchaseOrderItem"], rows["A_PurchaseOrderScheduleLine"],
                                        rows["A_InbDeliveryHeader"], rows["A_InbDeliveryItem"], plant, material)
    on_hand = supply.unrestricted_stock(rows["A_MatlStkInAcctMod"], plant, material)
    return ss, inventory.project_stock(on_hand, receipts, demand.mean, d0, HORIZON)


def gate(store: Store, supplier: str, qty: float) -> str:
    profile = store.get("SupplierCompliance", {"Supplier": supplier})
    return compliance.outcome(compliance.evaluate(profile, qty, store.as_of))


def info_records(store: Store, plant: str, material: str) -> list[dict]:
    return [r for r in store.rows["A_PurchasingInfoRecord"] if (r["Plant"], r["Material"]) == (plant, material)]


def scenario(seed: dict, sid: str) -> dict:
    return next(s for s in seed["scenarios"] if s["scenario_id"] == sid)


def test_committed_seed_matches_generator(seed):
    assert json.loads(json.dumps(generate(DEMO_DAY))) == seed, \
        "seed.json is stale: run `uv run python -m synapse.data.generate`"


def test_generation_is_relative_to_as_of():
    later = generate(DEMO_DAY + timedelta(days=10))
    assert later["meta"]["as_of"] == (DEMO_DAY + timedelta(days=10)).isoformat()
    # Same story, shifted: same counts and same scenario expectations
    base = generate(DEMO_DAY)
    assert {k: len(v) for k, v in later["entities"].items()} == {k: len(v) for k, v in base["entities"].items()}
    assert [s["expected"] for s in later["scenarios"]] == [s["expected"] for s in base["scenarios"]]


@pytest.mark.parametrize("plant, material", [("1100", "WC-ACACIA"), ("1100", "LOG-EUCA"), ("1200", "WC-ACACIA")])
def test_baseline_is_healthy(store, plant, material):
    ss, proj = plan_inputs(store, plant, material)
    assert inventory.first_breach(proj, ss) is None


def test_quality_inspection_stock_exists_but_is_not_available(store):
    stock = [r for r in store.rows["A_MatlStkInAcctMod"] if r["Plant"] == "1100" and r["Material"] == "WC-ACACIA"]
    assert {r["InventoryStockType"] for r in stock} == {"01", "02"}


def test_supplier_gate_outcomes(store):
    expected = {"0000100001": "PASS", "0000100002": "PASS", "0000100003": "BLOCK", "0000100004": "PASS",
                "0000100005": "HOLD"}
    assert {s: gate(store, s, 1_300) for s in expected} == expected


def test_sc01_hero_needs_compliant_transfer_and_human_approval(seed, store):
    sc = scenario(seed, "SC-01")
    store.apply_scenario("SC-01")
    ss, proj = plan_inputs(store, "1100", "WC-ACACIA")
    breach = inventory.first_breach(proj, ss)
    assert breach is not None and breach.day == store.as_of + timedelta(days=2)
    assert breach.closing < 0.5 * ss  # dramatic: well under half the safety stock
    need = inventory.shortfall(proj, ss)

    # Options that arrive by the breach day: only the transfer is compliant
    days_available = (breach.day - store.as_of).days
    fast = {r["Supplier"]: gate(store, r["Supplier"], need)
            for r in info_records(store, "1100", "WC-ACACIA") if r["MaterialPlannedDeliveryDurn"] <= days_available}
    assert fast == {"0000100003": "BLOCK", "0000100005": "HOLD"}
    cheapest = min(info_records(store, "1100", "WC-ACACIA"), key=lambda r: r["NetPriceAmount"])
    assert cheapest["Supplier"] == "0000100003"  # the tempting option is the non-compliant one

    lane = store.get("TransportLane", {"LaneId": "1200-1100-WC-ACACIA"})
    assert lane["TransitDays"] <= days_available and need <= lane["MaxDailyQty"]
    freight = need * float(lane["CostPerUnit"])
    assert freight > AUTO_EXECUTE_MAX_IMPACT_USD  # -> ESCALATE to Joule

    # Donor plant stays healthy after giving the shortfall away
    donor_ss, donor_proj = plan_inputs(store, "1200", "WC-ACACIA")
    assert min(p.closing for p in donor_proj) - need > donor_ss

    po, item = sc["case_id"].split("-")
    assert make_case_id(po, item) == sc["case_id"] and sc["expected"]["policy_effect"] == "ESCALATE"


def test_sc02_minor_delay_has_cheap_compliant_fix(seed, store):
    store.apply_scenario("SC-02")
    ss, proj = plan_inputs(store, "1100", "LOG-EUCA")
    breach = inventory.first_breach(proj, ss)
    assert breach is not None and breach.day == store.as_of + timedelta(days=1)
    need = inventory.shortfall(proj, ss)

    delayed_po = scenario(seed, "SC-02")["case_id"].split("-")[0]
    baseline_price = float(next(i for i in store.rows["A_PurchaseOrderItem"]
                                if i["PurchaseOrder"] == delayed_po)["NetPriceAmount"])
    in_time = [r for r in info_records(store, "1100", "LOG-EUCA") if r["MaterialPlannedDeliveryDurn"] <= 1]
    assert [r["Supplier"] for r in in_time] == ["0000100004"]
    assert gate(store, "0000100004", need) == "PASS"
    premium = (float(in_time[0]["NetPriceAmount"]) - baseline_price) * need
    assert 0 < premium <= AUTO_EXECUTE_MAX_IMPACT_USD  # -> ALLOW, autonomous


def test_sc03_requested_supplier_is_blocked(seed, store):
    sc = scenario(seed, "SC-03")
    assert sc["expected"]["supplier"] == "0000100003"
    assert gate(store, sc["expected"]["supplier"], 1_300) == "BLOCK"
    assert "Siak Agro Wood" in sc["utterance"]


def test_scenarios_only_touch_their_own_flow(store):
    store.apply_scenario("SC-01")
    ss, proj = plan_inputs(store, "1100", "LOG-EUCA")
    assert inventory.first_breach(proj, ss) is None


def test_scenario_case_ids_satisfy_case_contract(seed):
    for sc in seed["scenarios"]:
        if sc["case_id"]:
            CaseMessage(case_id=sc["case_id"], process_type=sc["process_type"],
                        payload_source=sc["payload_source"], timestamp="2026-10-31T09:00:00Z", raw_payload={})
