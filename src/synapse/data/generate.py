"""Deterministic synthetic dataset for the mock S/4 system and the demo scenarios.

All dates are relative to an as-of date (Demo Day by default), so regenerating for another day
keeps the story intact:

  * Mill Riau-1 (1100) burns ~1,150 t/day of acacia chips and is healthy on its open POs.
  * SC-01: the next chip ASN from Riau Fibre slips 3 days -> stock drops far below safety stock
    on day 2. Compliant suppliers need 3 days, too late. The fastest, cheapest supplier (Siak Agro
    Wood, 1 day) has a deforestation alert -> BLOCK. Sumatra Chip Traders (2 days) has an expired
    certificate -> HOLD. The only compliant option in time is a stock transfer from Mill Jambi-2
    (1200, 1 day), whose freight exceeds $5k -> human approval in Joule.
  * SC-02: a log ASN slips 1 day -> small dip, cheap compliant top-up -> autonomous execution.
  * SC-03: a buyer asks Joule to order from the cheapest supplier, which is non-compliant -> denied.

Company and plant names are fictional.

Run:  uv run python -m synapse.data.generate [--as-of YYYY-MM-DD] [--out PATH]
"""
import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

DEMO_DAY = date(2026, 10, 31)
RNG_SEED = 42
CONSUMPTION_HISTORY_DAYS = 90
PO_HISTORY_START, PO_HISTORY_END = 62, 4  # schedule dates, days before as-of
DEFAULT_OUT = Path(__file__).with_name("seed.json")

PLANTS = {"1100": "Mill Riau-1", "1200": "Mill Jambi-2"}
MATERIALS = {
    "WC-ACACIA": {"description": "Acacia wood chips", "unit": "TO", "eudr_relevant": True},
    "LOG-EUCA": {"description": "Eucalyptus pulpwood logs", "unit": "M3", "eudr_relevant": True},
}

SUPPLIERS = [
    # cert_days: certificate valid-to relative to as-of; scored: days since last risk scoring
    {"Supplier": "0000100001", "SupplierName": "Riau Fibre Plantations", "CertificateType": "FSC-FM",
     "cert_days": 400, "RiskBand": "LOW", "RiskScore": 12, "scored": 5, "DeforestationAlert": False,
     "GeolocationProvided": True, "DeclaredAnnualCapacity": 900_000, "YtdDeliveredQty": 610_000},
    {"Supplier": "0000100002", "SupplierName": "Kampar Timber Cooperative", "CertificateType": "PEFC",
     "cert_days": 200, "RiskBand": "MEDIUM", "RiskScore": 34, "scored": 10, "DeforestationAlert": False,
     "GeolocationProvided": True, "DeclaredAnnualCapacity": 250_000, "YtdDeliveredQty": 160_000},
    {"Supplier": "0000100003", "SupplierName": "Siak Agro Wood", "CertificateType": "FSC-CW",
     "cert_days": 120, "RiskBand": "HIGH", "RiskScore": 78, "scored": 2, "DeforestationAlert": True,
     "GeolocationProvided": True, "DeclaredAnnualCapacity": 300_000, "YtdDeliveredQty": 180_000},
    {"Supplier": "0000100004", "SupplierName": "Jambi Pulpwood Estate", "CertificateType": "FSC-FM",
     "cert_days": 500, "RiskBand": "LOW", "RiskScore": 9, "scored": 7, "DeforestationAlert": False,
     "GeolocationProvided": True, "DeclaredAnnualCapacity": 700_000, "YtdDeliveredQty": 420_000},
    {"Supplier": "0000100005", "SupplierName": "Sumatra Chip Traders", "CertificateType": "PEFC",
     "cert_days": -20, "RiskBand": "MEDIUM", "RiskScore": 41, "scored": 15, "DeforestationAlert": False,
     "GeolocationProvided": True, "DeclaredAnnualCapacity": 150_000, "YtdDeliveredQty": 120_000},
]
S1, S2, S3, S4, S5 = (s["Supplier"] for s in SUPPLIERS)

# (supplier, material, plant, net price USD per unit, planned delivery days)
INFO_RECORDS = [
    (S1, "WC-ACACIA", "1100", 64, 3), (S2, "WC-ACACIA", "1100", 66, 3), (S3, "WC-ACACIA", "1100", 58, 1),
    (S4, "WC-ACACIA", "1100", 71, 3), (S5, "WC-ACACIA", "1100", 63, 2),
    (S4, "WC-ACACIA", "1200", 62, 1), (S1, "WC-ACACIA", "1200", 65, 3), (S3, "WC-ACACIA", "1200", 57, 2),
    (S2, "LOG-EUCA", "1100", 48, 2), (S1, "LOG-EUCA", "1100", 49, 2), (S4, "LOG-EUCA", "1100", 53, 1),
]

# Demand profile and historical supplier mix per (plant, material)
FLOWS = {
    ("1100", "WC-ACACIA"): {"mean": 1150, "sd": 90, "on_hand": 2600, "qi": 300,
                            "mix": [(S1, 0.60), (S2, 0.25), (S5, 0.15)]},
    ("1100", "LOG-EUCA"): {"mean": 500, "sd": 40, "on_hand": 600, "qi": 0,
                           "mix": [(S2, 0.70), (S1, 0.30)]},
    ("1200", "WC-ACACIA"): {"mean": 600, "sd": 60, "on_hand": 9000, "qi": 0,
                            "mix": [(S4, 0.80), (S3, 0.20)]},
}

# Days late versus the schedule line: [(days, weight)]
DELIVERY_VARIANCE = {
    S1: [(0, 0.60), (1, 0.25), (2, 0.15)],
    S2: [(0, 0.80), (1, 0.15), (-1, 0.05)],
    S3: [(0, 0.85), (1, 0.15)],
    S4: [(0, 0.90), (1, 0.10)],
    S5: [(0, 0.50), (1, 0.30), (2, 0.20)],
}

# Open POs: (plant, material, supplier, qty, due in days, ASN already sent)
OPEN_POS = [
    ("1100", "WC-ACACIA", S1, 2400, 1, True),  # SC-01: this ASN slips 3 days
    ("1100", "WC-ACACIA", S1, 2300, 3, False),
    ("1100", "WC-ACACIA", S2, 2300, 5, False),
    ("1100", "WC-ACACIA", S1, 2300, 7, False),
    ("1100", "LOG-EUCA", S2, 600, 1, True),    # SC-02: this ASN slips 1 day
    ("1100", "LOG-EUCA", S2, 500, 2, False),
    ("1100", "LOG-EUCA", S1, 500, 3, False),
    ("1100", "LOG-EUCA", S2, 500, 4, False),
    ("1100", "LOG-EUCA", S1, 500, 5, False),
    ("1100", "LOG-EUCA", S2, 500, 6, False),
    ("1100", "LOG-EUCA", S2, 500, 7, False),
    ("1200", "WC-ACACIA", S4, 1200, 2, True),
    ("1200", "WC-ACACIA", S3, 1200, 4, False),
    ("1200", "WC-ACACIA", S4, 1200, 6, False),
]

TRANSPORT_LANES = [  # (from, to, material, USD per unit, transit days, max qty per day)
    ("1200", "1100", "WC-ACACIA", 9.0, 1, 1500),
    ("1100", "1200", "WC-ACACIA", 9.0, 1, 1500),
]


def _iso(d: date) -> str:
    return d.isoformat()


def generate(as_of: date = DEMO_DAY) -> dict:
    rng = random.Random(RNG_SEED)
    price = {(s, m, p): pr for s, m, p, pr, _ in INFO_RECORDS}
    lead = {(s, m, p): lt for s, m, p, _, lt in INFO_RECORDS}
    unit = {m: v["unit"] for m, v in MATERIALS.items()}

    pos, items, lines, matdocs, asn_headers, asn_items = [], [], [], [], [], []
    po_no, matdoc_no, asn_no = 4500000000, 4900000000, 180000000

    def add_po(plant, material, supplier, qty, po_date, due, delivered):
        nonlocal po_no
        po_no += 1
        po = str(po_no)
        pos.append({"PurchaseOrder": po, "CompanyCode": "1000", "PurchaseOrderType": "NB",
                    "PurchasingOrganization": "1000", "PurchasingGroup": "001", "Supplier": supplier,
                    "SupplyingPlant": None, "PurchaseOrderDate": _iso(po_date), "DocumentCurrency": "USD",
                    "CreatedByUser": "BUYER01"})
        items.append({"PurchaseOrder": po, "PurchaseOrderItem": "10", "Material": material, "Plant": plant,
                      "StorageLocation": "0001", "OrderQuantity": qty, "PurchaseOrderQuantityUnit": unit[material],
                      "NetPriceAmount": price[(supplier, material, plant)], "DocumentCurrency": "USD",
                      "IsCompletelyDelivered": delivered})
        lines.append({"PurchasingDocument": po, "PurchasingDocumentItem": "10", "ScheduleLine": "1",
                      "ScheduleLineDeliveryDate": _iso(due), "ScheduleLineOrderQuantity": qty,
                      "RoughGoodsReceiptQty": qty if delivered else 0,
                      "PurchaseOrderQuantityUnit": unit[material]})
        return po

    def add_matdoc(plant, material, movement, qty, posting, po=None, supplier=None):
        nonlocal matdoc_no
        matdoc_no += 1
        matdocs.append({"MaterialDocumentYear": str(posting.year), "MaterialDocument": str(matdoc_no),
                        "MaterialDocumentItem": "1", "Material": material, "Plant": plant,
                        "StorageLocation": "0001", "GoodsMovementType": movement, "QuantityInBaseUnit": qty,
                        "MaterialBaseUnit": unit[material], "PostingDate": _iso(posting),
                        "PurchaseOrder": po, "PurchaseOrderItem": "10" if po else None, "Supplier": supplier})

    # Delivered history: a PO every 2 days per flow; lead-time variance comes from the supplier.
    history = []
    for (plant, material), flow in FLOWS.items():
        suppliers, weights = zip(*flow["mix"])
        for back in range(PO_HISTORY_START, PO_HISTORY_END - 1, -2):
            supplier = rng.choices(suppliers, weights)[0]
            due = as_of - timedelta(days=back)
            po_date = due - timedelta(days=lead[(supplier, material, plant)])
            days, w = zip(*DELIVERY_VARIANCE[supplier])
            gr = due + timedelta(days=rng.choices(days, w)[0])
            history.append((po_date, plant, material, supplier, round(flow["mean"] * 2, -2), due, gr))
    for po_date, plant, material, supplier, qty, due, gr in sorted(history):
        po = add_po(plant, material, supplier, qty, po_date, due, delivered=True)
        add_matdoc(plant, material, "101", qty, gr, po=po, supplier=supplier)

    # Daily consumption (goods issue to production, movement 261)
    for (plant, material), flow in FLOWS.items():
        for back in range(CONSUMPTION_HISTORY_DAYS, 0, -1):
            qty = max(0, round(rng.gauss(flow["mean"], flow["sd"])))
            add_matdoc(plant, material, "261", qty, as_of - timedelta(days=back))

    # Open POs and their ASNs
    open_po = {}
    for plant, material, supplier, qty, due_in, has_asn in OPEN_POS:
        due = as_of + timedelta(days=due_in)
        po = add_po(plant, material, supplier, qty, due - timedelta(days=lead[(supplier, material, plant)] + 1),
                    due, delivered=False)
        open_po.setdefault((plant, material), []).append(po)
        if has_asn:
            asn_no += 1
            asn = str(asn_no)
            asn_headers.append({"DeliveryDocument": asn, "Supplier": supplier, "ReceivingPlant": plant,
                                "DeliveryDate": _iso(due), "CreationDate": _iso(as_of - timedelta(days=1)),
                                "LastChangeDate": _iso(as_of - timedelta(days=1))})
            asn_items.append({"DeliveryDocument": asn, "DeliveryDocumentItem": "10", "Material": material,
                              "Plant": plant, "ActualDeliveryQuantity": qty, "DeliveryQuantityUnit": unit[material],
                              "ReferenceSDDocument": po, "ReferenceSDDocumentItem": "10"})

    stock = []
    for (plant, material), flow in FLOWS.items():
        stock.append({"Material": material, "Plant": plant, "StorageLocation": "0001", "InventoryStockType": "01",
                      "MatlWrhsStkQtyInMatlBaseUnit": flow["on_hand"], "MaterialBaseUnit": unit[material]})
        if flow["qi"]:
            stock.append({"Material": material, "Plant": plant, "StorageLocation": "0001",
                          "InventoryStockType": "02", "MatlWrhsStkQtyInMatlBaseUnit": flow["qi"],
                          "MaterialBaseUnit": unit[material]})

    compliance = []
    for s in SUPPLIERS:
        row = {k: v for k, v in s.items() if k not in ("cert_days", "scored")}
        compliance.append(row | {
            "Country": "ID", "CertificateNumber": f"{s['CertificateType']}-{s['Supplier'][-4:]}",
            "CertificateValidTo": _iso(as_of + timedelta(days=s["cert_days"])),
            "RiskScoredAt": _iso(as_of - timedelta(days=s["scored"])), "QuantityUnit": "TO"})

    info_records = [{"PurchasingInfoRecord": f"53000000{n:02d}", "Supplier": s, "Material": m, "Plant": p,
                     "PurchasingOrganization": "1000", "NetPriceAmount": pr, "Currency": "USD",
                     "OrderPriceUnit": unit[m], "MaterialPlannedDeliveryDurn": lt}
                    for n, (s, m, p, pr, lt) in enumerate(INFO_RECORDS, start=1)]

    lanes = [{"LaneId": f"{f}-{t}-{m}", "FromPlant": f, "ToPlant": t, "Material": m, "Mode": "TRUCK",
              "CostPerUnit": c, "Currency": "USD", "TransitDays": d, "MaxDailyQty": q, "Unit": unit[m]}
             for f, t, m, c, d, q in TRANSPORT_LANES]

    hero_po, minor_po = open_po[("1100", "WC-ACACIA")][0], open_po[("1100", "LOG-EUCA")][0]
    asn_for = {a["ReferenceSDDocument"]: a["DeliveryDocument"] for a in asn_items}

    def delay(po: str, days: int) -> dict:
        new_date = date.fromisoformat(next(h for h in asn_headers if h["DeliveryDocument"] == asn_for[po])
                                      ["DeliveryDate"]) + timedelta(days=days)
        return {"entity_set": "A_InbDeliveryHeader", "key": {"DeliveryDocument": asn_for[po]},
                "changes": {"DeliveryDate": _iso(new_date), "LastChangeDate": _iso(as_of)}}

    scenarios = [
        {"scenario_id": "SC-01", "title": "Flooded access road delays Riau Fibre chip trucks by 3 days",
         "process_type": "ASN_DELAY", "payload_source": "ODATA_POLLER", "case_id": f"{hero_po}-10",
         "plant": "1100", "material": "WC-ACACIA", "mutations": [delay(hero_po, 3)],
         "carrier_notice": "Riau Fibre Plantations: access road to harvest block flooded; all chip trucks "
                           "held until further notice, estimated +3 days.",
         "expected": {"policy_effect": "ESCALATE", "action_type": "CREATE_STOCK_TRANSFER",
                      "blocked_suppliers": [S3], "held_suppliers": [S5]}},
        {"scenario_id": "SC-02", "title": "Eucalyptus log ASN from Kampar Timber slips 1 day",
         "process_type": "ASN_DELAY", "payload_source": "ODATA_POLLER", "case_id": f"{minor_po}-10",
         "plant": "1100", "material": "LOG-EUCA", "mutations": [delay(minor_po, 1)],
         "expected": {"policy_effect": "ALLOW", "action_type": "CREATE_PURCHASE_ORDER", "supplier": S4}},
        {"scenario_id": "SC-03", "title": "Buyer asks Joule to order from the cheapest chip supplier",
         "process_type": "USER_REQUEST", "payload_source": "JOULE_A2A", "case_id": None,
         "plant": "1100", "material": "WC-ACACIA", "mutations": [],
         "utterance": "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood, they're the cheapest.",
         "expected": {"policy_effect": "DENY", "gate_outcome": "BLOCK", "supplier": S3}},
    ]

    return {
        "meta": {"as_of": _iso(as_of), "rng_seed": RNG_SEED, "currency": "USD", "plants": PLANTS,
                 "materials": MATERIALS, "note": "Synthetic data. Company, plant and supplier names are fictional."},
        "entities": {
            "A_PurchaseOrder": pos, "A_PurchaseOrderItem": items, "A_PurchaseOrderScheduleLine": lines,
            "A_MatlStkInAcctMod": stock, "A_InbDeliveryHeader": asn_headers, "A_InbDeliveryItem": asn_items,
            "A_MaterialDocumentItem": matdocs, "A_PurchasingInfoRecord": info_records,
            "SupplierCompliance": compliance, "TransportLane": lanes,
        },
        "scenarios": scenarios,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as-of", type=date.fromisoformat, default=DEMO_DAY)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    data = generate(args.as_of)
    args.out.write_text(json.dumps(data, indent=1) + "\n")
    counts = ", ".join(f"{k}={len(v)}" for k, v in data["entities"].items())
    print(f"wrote {args.out} (as_of {args.as_of}): {counts}")


if __name__ == "__main__":
    main()
