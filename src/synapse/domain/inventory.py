"""Inventory math: safety stock, EOQ, reorder point, stock projection.

Projection convention: `on_hand` is the closing stock of the as-of day (day 0). Day n's closing
stock = day n-1 closing + receipts arriving on day n - daily demand.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from statistics import NormalDist, fmean, stdev


@dataclass(frozen=True)
class Stats:
    mean: float
    sd: float
    n: int


@dataclass(frozen=True)
class ProjectionDay:
    day: date
    receipts: float
    demand: float
    closing: float


def z_for_service_level(service_level: float) -> float:
    """One-sided z-score, e.g. 0.95 -> 1.645."""
    if not 0.5 <= service_level < 1:
        raise ValueError(f"service_level must be in [0.5, 1), got {service_level}")
    return NormalDist().inv_cdf(service_level)


def safety_stock(z: float, lead_time_days: float, demand_sd: float, daily_demand: float,
                 lead_time_sd: float) -> float:
    """SS = z * sqrt(L * sigma_D^2 + D^2 * sigma_L^2) — demand and lead-time uncertainty combined."""
    for name, v in (("z", z), ("lead_time_days", lead_time_days), ("demand_sd", demand_sd),
                    ("daily_demand", daily_demand), ("lead_time_sd", lead_time_sd)):
        if v < 0:
            raise ValueError(f"{name} must be >= 0, got {v}")
    return z * sqrt(lead_time_days * demand_sd**2 + daily_demand**2 * lead_time_sd**2)


def eoq(annual_demand: float, order_cost: float, holding_cost_per_unit_year: float) -> float:
    """Economic order quantity: sqrt(2 * D * S / H)."""
    if annual_demand < 0 or order_cost < 0:
        raise ValueError("annual_demand and order_cost must be >= 0")
    if holding_cost_per_unit_year <= 0:
        raise ValueError("holding_cost_per_unit_year must be > 0")
    return sqrt(2 * annual_demand * order_cost / holding_cost_per_unit_year)


def reorder_point(daily_demand: float, lead_time_days: float, ss: float) -> float:
    return daily_demand * lead_time_days + ss


def series_stats(values: Iterable[float]) -> Stats:
    vals = list(values)
    if len(vals) < 2:
        raise ValueError(f"need at least 2 observations, got {len(vals)}")
    return Stats(mean=fmean(vals), sd=stdev(vals), n=len(vals))


def daily_series(postings: Iterable[tuple[date, float]], start: date, end: date) -> list[float]:
    """Sum postings per calendar day over [start, end], with 0 for days without postings."""
    if end < start:
        raise ValueError("end must not be before start")
    totals = {start + timedelta(days=i): 0.0 for i in range((end - start).days + 1)}
    for day, qty in postings:
        if day in totals:
            totals[day] += qty
    return list(totals.values())


def project_stock(on_hand: float, receipts: Mapping[date, float], daily_demand: float,
                  start: date, days: int) -> list[ProjectionDay]:
    out, closing = [], on_hand
    for i in range(1, days + 1):
        day = start + timedelta(days=i)
        received = receipts.get(day, 0.0)
        closing = closing + received - daily_demand
        out.append(ProjectionDay(day, received, daily_demand, closing))
    return out


def first_breach(projection: list[ProjectionDay], threshold: float) -> ProjectionDay | None:
    return next((p for p in projection if p.closing < threshold), None)


def shortfall(projection: list[ProjectionDay], threshold: float) -> float:
    """Quantity needed to keep every projected day at or above `threshold`."""
    if not projection:
        return 0.0
    return max(0.0, threshold - min(p.closing for p in projection))
