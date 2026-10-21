from datetime import date, timedelta

import pytest

from synapse.domain.compliance import evaluate, outcome

TODAY = date(2026, 10, 31)


def profile(**kw):
    base = {"Supplier": "0000100001", "CertificateType": "FSC-FM", "CertificateValidTo": date(2027, 6, 1),
            "RiskBand": "LOW", "RiskScoredAt": TODAY - timedelta(days=3), "DeforestationAlert": False,
            "GeolocationProvided": True, "DeclaredAnnualCapacity": 100_000, "YtdDeliveredQty": 50_000}
    return base | kw


def failed(checks):
    return {c.code for c in checks if not c.passed}


def test_clean_supplier_passes():
    checks = evaluate(profile(), 1_000, TODAY)
    assert outcome(checks) == "PASS"
    assert not failed(checks)


def test_missing_profile_blocks():
    assert outcome(evaluate(None, 100, TODAY)) == "BLOCK"


@pytest.mark.parametrize("change, code, expected", [
    ({"DeforestationAlert": True}, "NO_DEFORESTATION_ALERT", "BLOCK"),
    ({"RiskBand": "HIGH"}, "RISK_BAND", "BLOCK"),
    ({"RiskBand": None}, "RISK_BAND", "HOLD"),
    ({"CertificateValidTo": TODAY - timedelta(days=1)}, "CERT_VALID", "HOLD"),
    ({"CertificateValidTo": None}, "CERT_VALID", "HOLD"),
    ({"GeolocationProvided": False}, "GEOLOCATION", "HOLD"),
    ({"RiskScoredAt": TODAY - timedelta(days=31)}, "RISK_FRESH", "HOLD"),
    ({"RiskScoredAt": None}, "RISK_FRESH", "HOLD"),
    ({"YtdDeliveredQty": 109_500}, "VOLUME_PLAUSIBLE", "HOLD"),
    ({"DeclaredAnnualCapacity": 0}, "VOLUME_PLAUSIBLE", "HOLD"),
])
def test_single_failures(change, code, expected):
    checks = evaluate(profile(**change), 1_000, TODAY)
    assert failed(checks) == {code}
    assert outcome(checks) == expected


def test_certificate_valid_on_expiry_day():
    assert outcome(evaluate(profile(CertificateValidTo=TODAY), 1_000, TODAY)) == "PASS"


def test_capacity_tolerance_boundary():
    # 109_000 + 1_000 == 110% of 100_000 -> still plausible
    assert outcome(evaluate(profile(YtdDeliveredQty=109_000), 1_000, TODAY)) == "PASS"


def test_block_wins_over_hold():
    checks = evaluate(profile(DeforestationAlert=True, CertificateValidTo=None), 1_000, TODAY)
    assert outcome(checks) == "BLOCK"
