"""HTTP-level tests: the mock must behave like S/4 OData v2 closely enough that tool code written
against it works unchanged against a real system."""
from conftest import INB, PO, STOCK, Z

from synapse.sap.odata import from_wire


def results(r):
    assert r.status_code == 200, r.text
    return r.json()["d"]["results"]


def open_chip_po(client):
    rows = results(client.get(f"{PO}/A_PurchaseOrderItem", params={
        "$filter": "Plant eq '1100' and Material eq 'WC-ACACIA' and IsCompletelyDelivered eq false",
        "$orderby": "PurchaseOrder"}))
    return rows[0]["PurchaseOrder"]


def new_po_body(**kw):
    body = {"PurchaseOrderType": "NB", "Supplier": "0000100004", "to_PurchaseOrderItem": {"results": [{
        "Material": "LOG-EUCA", "Plant": "1100", "OrderQuantity": "430",
        "to_ScheduleLine": {"results": [{"ScheduleLineDeliveryDate": "/Date(1793491200000)/",
                                         "ScheduleLineOrderQuantity": "430"}]}}]}}
    return body | kw


def test_service_document_and_unknown_service(client):
    r = client.get(f"{PO}/")
    assert "A_PurchaseOrder" in r.json()["d"]["EntitySets"]
    assert client.get("/sap/opu/odata/sap/NOPE_SRV/A_X").status_code == 404


def test_versioned_service_name_with_semicolon(client):
    rows = results(client.get(f"{INB}/A_InbDeliveryHeader"))
    assert len(rows) == 3


def test_entity_set_must_belong_to_service(client):
    r = client.get(f"{STOCK}/A_PurchaseOrder")
    assert r.status_code == 404
    assert r.json()["error"]["message"]["value"].startswith("Resource not found")


def test_collection_wire_format(client):
    rows = results(client.get(f"{STOCK}/A_MatlStkInAcctMod", params={"$filter": "Plant eq '1100'"}))
    row = next(r for r in rows if r["Material"] == "WC-ACACIA" and r["InventoryStockType"] == "01")
    assert row["MatlWrhsStkQtyInMatlBaseUnit"] == "2600"  # decimals are strings, as on S/4
    assert row["__metadata"]["type"] == "API_MATERIAL_STOCK_SRV.A_MatlStkInAcctModType"


def test_dates_are_odata_v2_format(client):
    row = results(client.get(f"{INB}/A_InbDeliveryHeader", params={"$top": "1"}))[0]
    assert row["DeliveryDate"].startswith("/Date(")


def test_top_skip_inlinecount_and_count(client):
    d = client.get(f"{PO}/A_PurchaseOrder", params={"$top": "5", "$skip": "100", "$inlinecount": "allpages"}).json()["d"]
    assert d["__count"] == "104" and len(d["results"]) == 4
    assert client.get(f"{PO}/A_PurchaseOrder/$count").text == "104"
    n = client.get(f"{PO}/A_PurchaseOrder/$count", params={"$filter": "Supplier eq '0000100003'"}).text
    assert 0 < int(n) < 104
    assert client.get(f"{PO}/A_PurchaseOrder", params={"$top": "-1"}).status_code == 400


def test_select(client):
    row = results(client.get(f"{Z}/SupplierCompliance", params={"$select": "Supplier,RiskBand"}))[0]
    assert set(row) == {"__metadata", "Supplier", "RiskBand"}
    assert client.get(f"{Z}/SupplierCompliance", params={"$select": "Nope"}).status_code == 400


def test_key_access_and_not_found(client):
    po = open_chip_po(client)
    d = client.get(f"{PO}/A_PurchaseOrder('{po}')").json()["d"]
    assert d["PurchaseOrder"] == po
    assert "__deferred" in d["to_PurchaseOrderItem"]
    item = client.get(f"{PO}/A_PurchaseOrderItem(PurchaseOrder='{po}',PurchaseOrderItem='10')").json()["d"]
    assert item["Material"] == "WC-ACACIA"
    assert client.get(f"{PO}/A_PurchaseOrder('0000000000')").status_code == 404
    assert client.get(f"{PO}/A_PurchaseOrderItem('{po}')").status_code == 400


def test_nested_expand_and_navigation(client):
    po = open_chip_po(client)
    d = client.get(f"{PO}/A_PurchaseOrder('{po}')", params={"$expand": "to_PurchaseOrderItem/to_ScheduleLine"}).json()["d"]
    lines = d["to_PurchaseOrderItem"]["results"][0]["to_ScheduleLine"]["results"]
    assert lines[0]["ScheduleLineOrderQuantity"] == "2400"
    nav = results(client.get(f"{PO}/A_PurchaseOrder('{po}')/to_PurchaseOrderItem"))
    assert nav[0]["PurchaseOrderItem"] == "10"
    parent = client.get(f"{PO}/A_PurchaseOrderItem(PurchaseOrder='{po}',PurchaseOrderItem='10')/to_PurchaseOrder").json()
    assert parent["d"]["PurchaseOrder"] == po
    assert client.get(f"{PO}/A_PurchaseOrder", params={"$expand": "to_Nope"}).status_code == 400


def test_writes_require_csrf_token(client):
    r = client.post(f"{PO}/A_PurchaseOrder", json=new_po_body())
    assert r.status_code == 403
    assert "CSRF" in r.json()["error"]["message"]["value"]


def test_create_purchase_order(client, csrf):
    r = client.post(f"{PO}/A_PurchaseOrder", json=new_po_body(), headers=csrf)
    assert r.status_code == 201, r.text
    d = r.json()["d"]
    item = d["to_PurchaseOrderItem"]["results"][0]
    assert item["NetPriceAmount"] == "53"  # defaulted from the info record
    assert item["PurchaseOrderQuantityUnit"] == "M3"
    assert r.headers["location"].endswith(f"A_PurchaseOrder('{d['PurchaseOrder']}')")
    assert client.get(f"{PO}/A_PurchaseOrder('{d['PurchaseOrder']}')").status_code == 200
    audit = client.get("/admin/audit").json()["writes"]
    assert audit[-1]["op"] == "CREATE" and audit[-1]["key"] == {"PurchaseOrder": d["PurchaseOrder"]}


def test_create_stock_transfer_order(client, csrf):
    body = new_po_body(PurchaseOrderType="UB", Supplier=None, SupplyingPlant="1200")
    body["to_PurchaseOrderItem"]["results"][0] |= {"Material": "WC-ACACIA", "OrderQuantity": "911",
                                                   "to_ScheduleLine": {"results": [{
                                                       "ScheduleLineDeliveryDate": "2026-11-01",
                                                       "ScheduleLineOrderQuantity": "911"}]}}
    r = client.post(f"{PO}/A_PurchaseOrder", json=body, headers=csrf)
    assert r.status_code == 201, r.text
    assert r.json()["d"]["SupplyingPlant"] == "1200"


def _item(body, **kw):
    body["to_PurchaseOrderItem"]["results"][0] |= kw
    return body


def test_create_validation(client, csrf):
    cases = [
        new_po_body(Supplier="9999999999"),
        new_po_body(PurchaseOrderType="ZZ"),
        new_po_body(PurchaseOrderType="UB", Supplier=None, SupplyingPlant="1100"),  # same as receiving plant
        new_po_body(PurchaseOrder="4599999999"),
        new_po_body(to_PurchaseOrderItem={"results": []}),
        new_po_body(Bogus="x"),
        _item(new_po_body(), Material="NOPE"),
        _item(new_po_body(), OrderQuantity="500"),  # schedule lines no longer add up
        _item(new_po_body(), PurchaseOrderQuantityUnit="TO"),
        _item(new_po_body(Supplier="0000100005")),  # no info record -> no price
        _item(new_po_body(), to_ScheduleLine={"results": [{"ScheduleLineDeliveryDate": "2026-10-01",
                                                           "ScheduleLineOrderQuantity": "430"}]}),
    ]
    for body in cases:
        r = client.post(f"{PO}/A_PurchaseOrder", json=body, headers=csrf)
        assert r.status_code == 400, (body, r.text)
    assert client.get("/admin/audit").json()["writes"] == []
    assert client.post(f"{Z}/SupplierCompliance", json={}, headers=csrf).status_code == 405
    assert client.post(f"{PO}/A_PurchaseOrder", content="nope", headers=csrf).status_code == 400


def test_patch_schedule_line(client, csrf):
    po = open_chip_po(client)
    key = f"A_PurchaseOrderScheduleLine(PurchasingDocument='{po}',PurchasingDocumentItem='10',ScheduleLine='1')"
    r = client.patch(f"{PO}/{key}", json={"ScheduleLineDeliveryDate": "/Date(1793750400000)/"}, headers=csrf)
    assert r.status_code == 204, r.text
    assert from_wire(client.get(f"{PO}/{key}").json()["d"]["ScheduleLineDeliveryDate"], "date").isoformat() == "2026-11-04"
    for bad in ({"Material": "X"}, {"ScheduleLineOrderQuantity": "0"}, {"ScheduleLineDeliveryDate": "2020-01-01"}):
        assert client.patch(f"{PO}/{key}", json=bad, headers=csrf).status_code == 400
    assert client.patch(f"{PO}/A_PurchaseOrder('{po}')", json={}, headers=csrf).status_code == 405


def test_delete_is_forbidden(client, csrf):
    po = open_chip_po(client)
    r = client.delete(f"{PO}/A_PurchaseOrder('{po}')", headers=csrf)
    assert r.status_code == 403
    assert client.get(f"{PO}/A_PurchaseOrder('{po}')").status_code == 200


def test_scenario_apply_and_reset(client, csrf):
    sc = client.get("/admin/scenarios").json()["scenarios"][0]
    asn = sc["mutations"][0]["key"]["DeliveryDocument"]
    before = client.get(f"{INB}/A_InbDeliveryHeader('{asn}')").json()["d"]["DeliveryDate"]
    assert client.post(f"/admin/scenarios/{sc['scenario_id']}/apply").status_code == 200
    after = client.get(f"{INB}/A_InbDeliveryHeader('{asn}')").json()["d"]["DeliveryDate"]
    assert from_wire(after, "date") > from_wire(before, "date")
    client.post(f"{PO}/A_PurchaseOrder", json=new_po_body(), headers=csrf)

    assert client.post("/admin/reset").status_code == 200
    assert client.get(f"{INB}/A_InbDeliveryHeader('{asn}')").json()["d"]["DeliveryDate"] == before
    assert client.get("/admin/audit").json()["writes"] == []
    assert client.get("/health").json()["applied_scenarios"] == []
    assert client.post("/admin/scenarios/SC-99/apply").status_code == 404


def test_fault_injection(client):
    assert client.post("/admin/faults", json={"error_rate": 1.0}).status_code == 200
    r = client.get(f"{PO}/A_PurchaseOrder?$top=1")
    assert r.status_code == 503 and r.json()["error"]["code"] == "SYNAPSE/INJECTED"
    assert client.get("/health").status_code == 200  # admin endpoints stay up
    assert client.post("/admin/faults", json={"error_rate": 2}).status_code == 422
    client.post("/admin/reset")
    assert client.get(f"{PO}/A_PurchaseOrder?$top=1").status_code == 200
