from datetime import date
from decimal import Decimal

import httpx
import pytest
from starlette.testclient import TestClient

from synapse.erp import ErpClient, ErpError
from synapse.mock_s4.app import create_app
from synapse.sap.odata import literal


def unreachable() -> httpx.Client:
    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)
    return httpx.Client(base_url="http://s4.invalid", transport=httpx.MockTransport(boom))


def new_po(qty=100):
    return {"PurchaseOrderType": "NB", "Supplier": "0000100004", "to_PurchaseOrderItem": [{
        "Material": "LOG-EUCA", "Plant": "1100", "OrderQuantity": qty,
        "to_ScheduleLine": [{"ScheduleLineDeliveryDate": date(2026, 11, 2), "ScheduleLineOrderQuantity": qty}]}]}


def test_literal():
    assert literal("O'Brien") == "'O''Brien'"
    assert literal(date(2026, 11, 2)) == "datetime'2026-11-02T00:00:00'"
    assert literal(12.5) == "12.5" and literal(3) == "3"
    assert literal(True) == "true" and literal(None) == "null"


def test_read_decodes_types(client):
    erp = ErpClient(client)
    rows = erp.read("A_InbDeliveryHeader", filter=f"ReceivingPlant eq {literal('1100')}", orderby="DeliveryDocument")
    assert len(rows) == 2 and isinstance(rows[0]["DeliveryDate"], date)
    stock = erp.read("A_MatlStkInAcctMod", filter="Plant eq '1100' and InventoryStockType eq '01'",
                     select=["Material", "MatlWrhsStkQtyInMatlBaseUnit"])
    assert {r["Material"]: r["MatlWrhsStkQtyInMatlBaseUnit"] for r in stock} == {
        "WC-ACACIA": Decimal(2600), "LOG-EUCA": Decimal(600)}


def test_get_with_expand_and_missing(client):
    erp = ErpClient(client)
    po = erp.read("A_PurchaseOrderItem", filter="IsCompletelyDelivered eq false", top=1)[0]["PurchaseOrder"]
    item = erp.get("A_PurchaseOrderItem", {"PurchaseOrder": po, "PurchaseOrderItem": "10"},
                   expand="to_ScheduleLine,to_PurchaseOrder")
    assert item["to_PurchaseOrder"]["PurchaseOrder"] == po
    assert isinstance(item["to_ScheduleLine"][0]["ScheduleLineDeliveryDate"], date)
    assert erp.get("A_PurchaseOrder", {"PurchaseOrder": "0000000000"}) is None


def test_create_and_update_handle_csrf(client):
    erp = ErpClient(client)
    created = erp.create("A_PurchaseOrder", new_po())
    assert created["to_PurchaseOrderItem"][0]["OrderQuantity"] == Decimal(100)
    po = created["PurchaseOrder"]
    erp._csrf = {k: "stale-token" for k in erp._csrf}  # session expired: client must refetch and retry once
    erp.update("A_PurchaseOrderScheduleLine",
               {"PurchasingDocument": po, "PurchasingDocumentItem": "10", "ScheduleLine": "1"},
               {"ScheduleLineDeliveryDate": date(2026, 11, 3)})
    line = erp.get("A_PurchaseOrderScheduleLine",
                   {"PurchasingDocument": po, "PurchasingDocumentItem": "10", "ScheduleLine": "1"})
    assert line["ScheduleLineDeliveryDate"] == date(2026, 11, 3)


def test_business_errors_surface(client):
    with pytest.raises(ErpError) as e:
        ErpClient(client).create("A_PurchaseOrder", new_po() | {"Supplier": "9999999999"})
    assert e.value.status == 400 and "does not exist" in e.value.message
    with pytest.raises(ValueError, match="no property"):
        ErpClient(client).create("A_PurchaseOrder", {"Nope": 1})


def test_failover_on_unreachable_primary(client):
    events = []
    erp = ErpClient(unreachable(), fallback=client, on_failover=events.append)
    assert erp.read("SupplierCompliance") and erp.degraded
    assert len(events) == 1 and "ConnectError" in events[0]
    erp.read("TransportLane")
    assert len(events) == 1  # sticky: no second failover


def test_failover_on_server_error_for_reads(seed, client):
    broken = TestClient(create_app(seed, rng_seed=0))
    broken.post("/admin/faults", json={"error_rate": 1.0})
    erp = ErpClient(broken, fallback=client)
    assert erp.read("SupplierCompliance")
    assert erp.degraded


def test_writes_are_not_replayed_after_server_error(seed, client):
    broken = TestClient(create_app(seed, rng_seed=0))
    erp = ErpClient(broken, fallback=client)
    erp.read("SupplierCompliance")  # healthy so far
    broken.post("/admin/faults", json={"error_rate": 1.0})
    with pytest.raises(ErpError) as e:
        erp.create("A_PurchaseOrder", new_po())
    assert e.value.status == 503
    assert client.get("/admin/audit").json()["writes"] == []


def test_unreachable_without_fallback():
    with pytest.raises(ErpError) as e:
        ErpClient(unreachable()).read("SupplierCompliance")
    assert e.value.status == 503 and e.value.code == "SYNAPSE/UNREACHABLE"
