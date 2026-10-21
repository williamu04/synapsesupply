from datetime import date

from synapse.domain import supply

D = date(2026, 11, 1)


def item(po, plant="1100", material="WC", done=False):
    return {"PurchaseOrder": po, "PurchaseOrderItem": "10", "Plant": plant, "Material": material,
            "IsCompletelyDelivered": done}


def line(po, day, qty, received=0, n="1"):
    return {"PurchasingDocument": po, "PurchasingDocumentItem": "10", "ScheduleLine": n,
            "ScheduleLineDeliveryDate": day, "ScheduleLineOrderQuantity": qty, "RoughGoodsReceiptQty": received}


def test_unrestricted_stock_ignores_quality_inspection():
    rows = [{"Plant": "1100", "Material": "WC", "InventoryStockType": "01", "MatlWrhsStkQtyInMatlBaseUnit": 100},
            {"Plant": "1100", "Material": "WC", "InventoryStockType": "02", "MatlWrhsStkQtyInMatlBaseUnit": 50},
            {"Plant": "1200", "Material": "WC", "InventoryStockType": "01", "MatlWrhsStkQtyInMatlBaseUnit": 70}]
    assert supply.unrestricted_stock(rows, "1100", "WC") == 100


def test_expected_receipts_use_schedule_lines_minus_received():
    items = [item("A"), item("B"), item("C", done=True), item("D", plant="1200")]
    lines = [line("A", D, 100, received=30), line("B", D, 50), line("C", D, 999), line("D", D, 999)]
    assert supply.expected_receipts(items, lines, [], [], "1100", "WC") == {D: 120}


def test_asn_date_overrides_schedule_line_and_remainder_stays():
    late = date(2026, 11, 4)
    items = [item("A")]
    lines = [line("A", D, 100)]
    headers = [{"DeliveryDocument": "180", "DeliveryDate": late}]
    asn_items = [{"DeliveryDocument": "180", "ReferenceSDDocument": "A", "ReferenceSDDocumentItem": "10",
                  "ActualDeliveryQuantity": 60}]
    assert supply.expected_receipts(items, lines, headers, asn_items, "1100", "WC") == {late: 60, D: 40}


def test_lead_times_from_first_goods_receipt():
    pos = [{"PurchaseOrder": "A", "PurchaseOrderDate": date(2026, 10, 1), "Supplier": "S1"},
           {"PurchaseOrder": "B", "PurchaseOrderDate": date(2026, 10, 5), "Supplier": "S2"}]
    docs = [
        {"GoodsMovementType": "101", "Plant": "1100", "Material": "WC", "PurchaseOrder": "A",
         "PurchaseOrderItem": "10", "PostingDate": date(2026, 10, 5)},
        {"GoodsMovementType": "101", "Plant": "1100", "Material": "WC", "PurchaseOrder": "A",
         "PurchaseOrderItem": "10", "PostingDate": date(2026, 10, 3)},
        {"GoodsMovementType": "101", "Plant": "1100", "Material": "WC", "PurchaseOrder": "B",
         "PurchaseOrderItem": "10", "PostingDate": date(2026, 10, 7)},
        {"GoodsMovementType": "261", "Plant": "1100", "Material": "WC", "PurchaseOrder": None,
         "PurchaseOrderItem": None, "PostingDate": date(2026, 10, 7)},
    ]
    assert supply.lead_times(pos, docs, "1100", "WC") == [2, 2]
    assert supply.lead_times(pos, docs, "1100", "WC", supplier="S2") == [2]
