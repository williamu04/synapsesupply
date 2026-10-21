"""Delivery-delay prediction inputs and the empirical fallback predictor.

Each delivered PO item in S/4 history becomes one row (supplier, plant, material, planned lead
time, quantity, weekday → delay in days, late Y/N). SAP RPT-1 learns from these rows in-context and
predicts the delay for candidate orders (synapse.sap.rpt). When RPT-1 is unreachable, the empirical
predictor here gives a transparent per-supplier estimate instead.
"""
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import Protocol

PREDICT = "[PREDICT]"
FEATURES = ("SUPPLIER", "PLANT", "MATERIAL", "PLANNED_LEAD_DAYS", "QUANTITY", "WEEKDAY")
TARGETS = ("DELAY_DAYS", "LATE")


@dataclass(frozen=True)
class DelayEstimate:
    expected_delay_days: float
    late_probability: float
    method: str

    @property
    def on_time_probability(self) -> float:
        return round(1 - self.late_probability, 2)


class DelayPredictor(Protocol):
    method: str

    def predict(self, history: list[dict], queries: list[dict]) -> list[DelayEstimate]: ...


def delivery_history(purchase_orders: Iterable[dict], items: Iterable[dict], material_docs: Iterable[dict]
                     ) -> list[dict]:
    """One row per delivered PO item: first goods receipt versus the first schedule-line date.

    items must carry their schedule lines under `to_ScheduleLine` (OData $expand)."""
    headers = {po["PurchaseOrder"]: po for po in purchase_orders}
    first_gr: dict[tuple[str, str], date] = {}
    for d in material_docs:
        if d["GoodsMovementType"] == "101" and d.get("PurchaseOrder"):
            k = (d["PurchaseOrder"], d["PurchaseOrderItem"])
            first_gr[k] = min(first_gr.get(k, d["PostingDate"]), d["PostingDate"])
    rows = []
    for item in items:
        k = (item["PurchaseOrder"], item["PurchaseOrderItem"])
        header, lines = headers.get(item["PurchaseOrder"]), item.get("to_ScheduleLine") or []
        if k not in first_gr or header is None or not lines or not header.get("Supplier"):
            continue
        scheduled = min(sl["ScheduleLineDeliveryDate"] for sl in lines)
        delay = (first_gr[k] - scheduled).days
        rows.append({"SUPPLIER": header["Supplier"], "PLANT": item["Plant"], "MATERIAL": item["Material"],
                     "PLANNED_LEAD_DAYS": (scheduled - header["PurchaseOrderDate"]).days,
                     "QUANTITY": float(item["OrderQuantity"]), "WEEKDAY": scheduled.strftime("%a"),
                     "DELAY_DAYS": delay, "LATE": "Y" if delay > 0 else "N"})
    return rows


def query_row(*, supplier: str, plant: str, material: str, lead_days: int, quantity: float, arrival: date) -> dict:
    return {"SUPPLIER": supplier, "PLANT": plant, "MATERIAL": material, "PLANNED_LEAD_DAYS": lead_days,
            "QUANTITY": float(quantity), "WEEKDAY": arrival.strftime("%a"), "DELAY_DAYS": PREDICT, "LATE": PREDICT}


class EmpiricalDelayPredictor:
    """Per-supplier history: mean lateness (early counts as on time) and a Laplace-smoothed late rate.
    Suppliers without history get the overall rate."""

    method = "empirical"

    def predict(self, history: list[dict], queries: list[dict]) -> list[DelayEstimate]:
        by_supplier: dict[str, list[int]] = defaultdict(list)
        for row in history:
            by_supplier[row["SUPPLIER"]].append(int(row["DELAY_DAYS"]))
        everyone = [d for ds in by_supplier.values() for d in ds]

        def estimate(delays: list[int]) -> DelayEstimate:
            if not delays:
                return DelayEstimate(0.0, 0.5, self.method)
            late = sum(d > 0 for d in delays)
            return DelayEstimate(round(fmean(max(d, 0) for d in delays), 2),
                                 round((late + 1) / (len(delays) + 2), 2), self.method)

        return [estimate(by_supplier.get(q["SUPPLIER"]) or everyone) for q in queries]
