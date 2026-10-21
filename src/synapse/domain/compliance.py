"""EUDR / certification gate for a sourcing option. Pure function over a SupplierCompliance row
(ZSCM_SYNAPSE_SRV field names, Python-typed values).

BLOCK = must not source from this supplier (no human override in the agent flow).
HOLD  = needs a human to resolve evidence first; the agent must not pick it autonomously.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Severity = Literal["HOLD", "BLOCK"]
Outcome = Literal["PASS", "HOLD", "BLOCK"]

RISK_MAX_AGE = timedelta(days=30)
CAPACITY_TOLERANCE = 1.10


@dataclass(frozen=True)
class Check:
    code: str
    passed: bool
    severity: Severity
    detail: str


def evaluate(profile: dict | None, incoming_qty: float, today: date) -> list[Check]:
    if not profile:
        return [Check("NO_PROFILE", False, "BLOCK", "Supplier has no compliance profile")]

    checks = []
    valid_to = profile.get("CertificateValidTo")
    cert = profile.get("CertificateType") or "Certificate"
    checks.append(Check(
        "CERT_VALID", valid_to is not None and valid_to >= today, "HOLD",
        "No verified certificate" if valid_to is None
        else f"{cert} expired {valid_to}" if valid_to < today else f"{cert} valid to {valid_to}"))

    alert = bool(profile.get("DeforestationAlert"))
    checks.append(Check(
        "NO_DEFORESTATION_ALERT", not alert, "BLOCK",
        "Deforestation alert on sourcing area after EUDR cut-off (2020-12-31)" if alert
        else "No deforestation alerts"))

    checks.append(Check(
        "GEOLOCATION", bool(profile.get("GeolocationProvided")), "HOLD",
        "Plot geolocation on file" if profile.get("GeolocationProvided")
        else "Plot geolocation missing (EUDR Art. 9)"))

    band = profile.get("RiskBand")
    checks.append(Check("RISK_BAND", band in ("LOW", "MEDIUM"), "BLOCK" if band == "HIGH" else "HOLD",
                        f"Risk band {band or 'UNSCORED'}"))

    scored_at = profile.get("RiskScoredAt")
    fresh = scored_at is not None and today - scored_at <= RISK_MAX_AGE
    checks.append(Check("RISK_FRESH", fresh, "HOLD", f"Risk last scored {scored_at or 'never'}"))

    capacity = float(profile.get("DeclaredAnnualCapacity") or 0)
    ytd = float(profile.get("YtdDeliveredQty") or 0)
    within = capacity > 0 and ytd + incoming_qty <= capacity * CAPACITY_TOLERANCE
    checks.append(Check("VOLUME_PLAUSIBLE", within, "HOLD",
                        f"YTD + incoming {ytd + incoming_qty:,.0f} vs declared capacity {capacity:,.0f}"))
    return checks


def outcome(checks: list[Check]) -> Outcome:
    failed = [c for c in checks if not c.passed]
    if any(c.severity == "BLOCK" for c in failed):
        return "BLOCK"
    return "HOLD" if failed else "PASS"
