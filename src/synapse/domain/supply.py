"""Turn S/4 rows (OData field names, Python-typed values) into inputs for the inventory math.

The agent's tools fetch rows from the ERP and call these functions, so the arithmetic is the same
in the demo, in tests, and against a real S/4 system.
"""
from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from .inventory import daily_series

UNRESTRICTED = "01"
GR_FOR_PO = "101"
CONSUMPTION = "261"


def unrestricted_stock(stock_rows: Iterable[dict], plant: str, material: str) -> float:
    """Only unrestricted-use stock counts as available; quality-inspection and blocked stock do not."""
    return sum(float(r["MatlWrhsStkQtyInMatlBaseUnit"]) for r in stock_rows
               if r["Plant"] == plant and r["Material"] == material
               and r["InventoryStockType"] == UNRESTRICTED)


def daily_consumption(material_docs: Iterable[dict], plant: str, material: str,
                      start: date, end: date) -> list[float]:
    postings = [(r["PostingDate"], float(r["QuantityInBaseUnit"])) for r in material_docs
                if r["GoodsMovementType"] == CONSUMPTION and r["Plant"] == plant
                and r["Material"] == material]
    return daily_series(postings, start, end)


def lead_times(purchase_orders: Iterable[dict], material_docs: Iterable[dict], plant: str,
               material: str, supplier: str | None = None) -> list[int]:
    """Actual lead time in days per PO item: first goods receipt minus PO date."""
    po_dates = {po["PurchaseOrder"]: po["PurchaseOrderDate"] for po in purchase_orders
                if supplier is None or po.get("Supplier") == supplier}
    first_gr: dict[tuple[str, str], date] = {}
    for r in material_docs:
        if (r["GoodsMovementType"] == GR_FOR_PO and r["Plant"] == plant and r["Material"] == material
                and r.get("PurchaseOrder") in po_dates):
            k = (r["PurchaseOrder"], r["PurchaseOrderItem"])
            first_gr[k] = min(first_gr.get(k, r["PostingDate"]), r["PostingDate"])
    return [(gr - po_dates[po]).days for (po, _), gr in sorted(first_gr.items())]


def expected_receipts(items: Iterable[dict], schedule_lines: Iterable[dict], asn_headers: Iterable[dict],
                      asn_items: Iterable[dict], plant: str, material: str) -> dict[date, float]:
    """Open inbound quantity per arrival date for one plant/material.

    An ASN (inbound delivery) overrides the schedule line: its quantity arrives on the ASN's
    DeliveryDate, and only the remainder stays on the schedule-line dates.
    """
    open_items = {(i["PurchaseOrder"], i["PurchaseOrderItem"]) for i in items
                  if i["Plant"] == plant and i["Material"] == material and not i["IsCompletelyDelivered"]}

    asn_date = {h["DeliveryDocument"]: h["DeliveryDate"] for h in asn_headers}
    asn_qty: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
    for a in asn_items:
        k = (a["ReferenceSDDocument"], a["ReferenceSDDocumentItem"])
        if k in open_items and a["DeliveryDocument"] in asn_date:
            asn_qty[k].append((asn_date[a["DeliveryDocument"]], float(a["ActualDeliveryQuantity"])))

    lines: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for s in schedule_lines:
        k = (s["PurchasingDocument"], s["PurchasingDocumentItem"])
        if k in open_items:
            lines[k].append(s)

    receipts: dict[date, float] = defaultdict(float)
    for k in open_items:
        announced = 0.0
        for day, qty in asn_qty.get(k, []):
            receipts[day] += qty
            announced += qty
        for s in sorted(lines[k], key=lambda s: s["ScheduleLineDeliveryDate"]):
            open_qty = float(s["ScheduleLineOrderQuantity"]) - float(s["RoughGoodsReceiptQty"] or 0)
            covered = min(open_qty, announced)
            announced -= covered
            if open_qty - covered > 0:
                receipts[s["ScheduleLineDeliveryDate"]] += open_qty - covered
    return dict(receipts)
