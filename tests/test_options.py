from datetime import date, timedelta

import pytest

from synapse.domain.options import plan_confidence, sourcing_options

TODAY = date(2026, 10, 31)


def profile(supplier, **kw):
    base = {"Supplier": supplier, "SupplierName": f"Supplier {supplier}", "CertificateType": "FSC",
            "CertificateValidTo": date(2027, 6, 1), "RiskBand": "LOW", "RiskScoredAt": TODAY - timedelta(days=2),
            "DeforestationAlert": False, "GeolocationProvided": True, "DeclaredAnnualCapacity": 100_000,
            "YtdDeliveredQty": 10_000}
    return base | kw


def info(supplier, price, lead, plant="1100", material="WC"):
    return {"Supplier": supplier, "Plant": plant, "Material": material, "NetPriceAmount": price,
            "MaterialPlannedDeliveryDurn": lead}


def options(**kw):
    args = {"plant": "1100", "material": "WC", "quantity": 900, "needed_by": TODAY + timedelta(days=2),
            "today": TODAY, "baseline_price": 64.0,
            "info_records": [info("A", 70, 3), info("B", 58, 1), info("C", 66, 2), info("X", 50, 1, plant="1200")],
            "compliance_profiles": {"A": profile("A"), "B": profile("B", DeforestationAlert=True), "C": profile("C")},
            "lanes": [{"FromPlant": "1200", "ToPlant": "1100", "Material": "WC", "TransitDays": 1,
                       "CostPerUnit": 9.0, "MaxDailyQty": 1500}],
            "donor_spare": {"1200": 7000.0}, "plant_names": {"1200": "Mill Jambi-2"}}
    return sourcing_options(**(args | kw))


def test_options_are_complete_and_sorted_best_first():
    opts = options()
    assert [o.option_id for o in opts] == ["PO:C", "STO:1200", "PO:B", "PO:A"]
    by_id = {o.option_id: o for o in opts}
    assert by_id["PO:B"].compliance == "BLOCK" and by_id["PO:B"].arrives_in_time
    assert any("DEFORESTATION" in f for f in by_id["PO:B"].compliance_findings)
    assert not by_id["PO:A"].arrives_in_time
    assert by_id["STO:1200"].compliance == "NOT_APPLICABLE" and by_id["STO:1200"].source_name == "Mill Jambi-2"
    assert by_id["PO:C"].incremental_cost(900) == 1_800  # (66 - 64) * 900


def test_cheaper_supplier_has_no_negative_impact():
    assert {o.option_id: o for o in options()}["PO:B"].incremental_cost(900) == 0


@pytest.mark.parametrize("spare, expected", [(7000.0, 1500), (800.0, 800), (-200.0, 0)])
def test_transfer_capacity_is_limited_by_lane_and_donor_spare(spare, expected):
    sto = next(o for o in options(donor_spare={"1200": spare}) if o.kind == "STOCK_TRANSFER")
    assert sto.max_quantity == expected


def test_no_transfer_without_donor_analysis():
    assert all(o.kind == "PURCHASE_ORDER" for o in options(donor_spare={}))


def test_missing_compliance_profile_blocks():
    opts = options(compliance_profiles={})
    assert {o.compliance for o in opts if o.kind == "PURCHASE_ORDER"} == {"BLOCK"}


def test_plan_confidence():
    good = {"covers_shortfall": True, "arrives_in_time": True, "demand_samples": 90, "lead_time_samples": 30,
            "erp_degraded": False}
    assert plan_confidence(**good) == 0.97
    assert plan_confidence(**good | {"erp_degraded": True}) == 0.87
    assert plan_confidence(**good | {"covers_shortfall": False}) == 0.82
    assert plan_confidence(**good | {"arrives_in_time": False, "covers_shortfall": False,
                                     "demand_samples": 5, "lead_time_samples": 2, "erp_degraded": True}) == 0.42
