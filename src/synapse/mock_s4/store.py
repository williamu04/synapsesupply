"""In-memory ERP state for the mock, loaded from the synthetic seed.

Writes are validated roughly the way S/4 would reject them and are appended to an audit log so
the demo can show exactly what the agent changed. `reset()` restores the seed between runs.
"""
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.resources import files
from typing import Any

from synapse.sap.odata import ODataError, bad_request, from_wire
from synapse.sap.schema import ENTITY_SETS, EntitySet

SCHEDULE_LINE_WRITABLE = {"ScheduleLineDeliveryDate", "ScheduleLineOrderQuantity"}
PO_HEADER_DEFAULTS = {"CompanyCode": "1000", "PurchasingOrganization": "1000", "PurchasingGroup": "001",
                      "DocumentCurrency": "USD", "CreatedByUser": "SYNAPSE_AGENT"}


def load_seed() -> dict:
    return json.loads(files("synapse.data").joinpath("seed.json").read_text())


def decode_row(es: EntitySet, raw: dict) -> dict:
    unknown = set(raw) - set(es.types)
    if unknown:
        raise bad_request(f"Unknown properties for {es.name}: {', '.join(sorted(unknown))}")
    return {f: from_wire(raw.get(f), t) for f, t in es.types.items()}


class Store:
    def __init__(self, seed: dict):
        self._seed = seed
        self.reset()

    def reset(self) -> None:
        self.rows: dict[str, list[dict]] = {
            name: [decode_row(es, r) for r in self._seed["entities"].get(name, [])]
            for name, es in ENTITY_SETS.items()}
        self.audit: list[dict] = []
        self.applied_scenarios: list[str] = []

    @property
    def meta(self) -> dict:
        return self._seed["meta"]

    @property
    def as_of(self) -> date:
        return date.fromisoformat(self.meta["as_of"])

    @property
    def scenarios(self) -> list[dict]:
        return self._seed["scenarios"]

    # --- reads ----------------------------------------------------------------------------------

    def get(self, set_name: str, key: dict[str, str]) -> dict:
        for r in self.rows[set_name]:
            if all(r[k] == v for k, v in key.items()):
                return r
        raise ODataError(404, "/IWBEP/CM_MGW_RT/020", f"Resource not found for {set_name} with key {key}")

    def navigate(self, es: EntitySet, row: dict, nav_name: str) -> list[dict]:
        nav = es.navs[nav_name]
        return [t for t in self.rows[nav.target] if all(row[s] == t[d] for s, d in nav.on)]

    # --- writes ---------------------------------------------------------------------------------

    def _log(self, op: str, entity_set: str, key: dict, payload: dict) -> None:
        self.audit.append({"ts": datetime.now(UTC).isoformat(), "op": op, "entity_set": entity_set,
                           "key": key, "payload": payload})

    def patch_schedule_line(self, key: dict[str, str], changes: dict[str, Any]) -> dict:
        es = ENTITY_SETS["A_PurchaseOrderScheduleLine"]
        row = self.get(es.name, key)
        illegal = set(changes) - SCHEDULE_LINE_WRITABLE
        if illegal:
            raise bad_request(f"Properties not updatable: {', '.join(sorted(illegal))}")
        new = {f: from_wire(v, es.types[f]) for f, v in changes.items()}
        if "ScheduleLineOrderQuantity" in new and new["ScheduleLineOrderQuantity"] < max(
                row["RoughGoodsReceiptQty"] or Decimal(0), Decimal("0.001")):
            raise bad_request("Quantity must be positive and not below the quantity already received")
        if "ScheduleLineDeliveryDate" in new and new["ScheduleLineDeliveryDate"] < self.as_of:
            raise bad_request("Delivery date lies in the past")
        row.update(new)
        self._log("PATCH", es.name, key, changes)
        return row

    def create_purchase_order(self, payload: dict) -> dict:
        po_es, item_es, sl_es = (ENTITY_SETS[n] for n in
                                 ("A_PurchaseOrder", "A_PurchaseOrderItem", "A_PurchaseOrderScheduleLine"))
        payload = dict(payload)
        items_raw = (payload.pop("to_PurchaseOrderItem", None) or {}).get("results") or []
        if not items_raw:
            raise bad_request("A purchase order needs at least one item (to_PurchaseOrderItem)")
        if "PurchaseOrder" in payload:
            raise bad_request("PurchaseOrder number is assigned by the system")

        header = decode_row(po_es, {**PO_HEADER_DEFAULTS, **payload})
        header["PurchaseOrderDate"] = header["PurchaseOrderDate"] or self.as_of
        po_type = header["PurchaseOrderType"]
        if po_type == "NB":
            if not header["Supplier"] or not self._exists("SupplierCompliance", Supplier=header["Supplier"]):
                raise bad_request(f"Supplier {header['Supplier']!r} does not exist")
            if header["SupplyingPlant"]:
                raise bad_request("Standard PO (NB) must not have a SupplyingPlant")
        elif po_type == "UB":
            if header["SupplyingPlant"] not in self.meta["plants"]:
                raise bad_request(f"Supplying plant {header['SupplyingPlant']!r} does not exist")
            if header["Supplier"]:
                raise bad_request("Stock transport order (UB) must not have a Supplier")
        else:
            raise bad_request(f"Unsupported PurchaseOrderType {po_type!r} (use NB or UB)")

        number = str(max(int(p["PurchaseOrder"]) for p in self.rows[po_es.name]) + 1)
        header["PurchaseOrder"] = number
        items, lines = [], []
        for n, item_raw in enumerate(items_raw, start=1):
            item_raw = dict(item_raw)
            sl_raw = (item_raw.pop("to_ScheduleLine", None) or {}).get("results") or []
            item = decode_row(item_es, {"PurchaseOrderItem": str(n * 10), "DocumentCurrency": header["DocumentCurrency"],
                                        "IsCompletelyDelivered": False, **item_raw})
            item["PurchaseOrder"] = number
            material = self.meta["materials"].get(item["Material"])
            if material is None:
                raise bad_request(f"Material {item['Material']!r} does not exist")
            if item["Plant"] not in self.meta["plants"]:
                raise bad_request(f"Plant {item['Plant']!r} does not exist")
            if po_type == "UB" and item["Plant"] == header["SupplyingPlant"]:
                raise bad_request("Receiving plant must differ from supplying plant")
            if not item["OrderQuantity"] or item["OrderQuantity"] <= 0:
                raise bad_request("OrderQuantity must be positive")
            item["PurchaseOrderQuantityUnit"] = item["PurchaseOrderQuantityUnit"] or material["unit"]
            if item["PurchaseOrderQuantityUnit"] != material["unit"]:
                raise bad_request(f"Unit for {item['Material']} must be {material['unit']}")
            if item["NetPriceAmount"] is None:
                item["NetPriceAmount"] = Decimal(0) if po_type == "UB" else self._info_price(
                    header["Supplier"], item["Material"], item["Plant"])
            item["StorageLocation"] = item["StorageLocation"] or "0001"

            if not sl_raw:
                raise bad_request(f"Item {item['PurchaseOrderItem']} needs at least one schedule line")
            total = Decimal(0)
            for m, sl in enumerate(sl_raw, start=1):
                line = decode_row(sl_es, {"ScheduleLine": str(m), "RoughGoodsReceiptQty": 0,
                                          "PurchaseOrderQuantityUnit": item["PurchaseOrderQuantityUnit"], **sl})
                line["PurchasingDocument"], line["PurchasingDocumentItem"] = number, item["PurchaseOrderItem"]
                if not line["ScheduleLineDeliveryDate"] or line["ScheduleLineDeliveryDate"] < self.as_of:
                    raise bad_request("Schedule line needs a delivery date that is not in the past")
                total += line["ScheduleLineOrderQuantity"] or 0
                lines.append(line)
            if total != item["OrderQuantity"]:
                raise bad_request(f"Schedule lines ({total}) do not add up to OrderQuantity ({item['OrderQuantity']})")
            items.append(item)

        self.rows[po_es.name].append(header)
        self.rows[item_es.name].extend(items)
        self.rows[sl_es.name].extend(lines)
        self._log("CREATE", po_es.name, {"PurchaseOrder": number}, payload | {"items": items_raw})
        return header

    def apply_scenario(self, scenario_id: str) -> dict:
        scenario = next((s for s in self.scenarios if s["scenario_id"] == scenario_id), None)
        if scenario is None:
            raise ODataError(404, "SYNAPSE/NO_SCENARIO", f"Unknown scenario {scenario_id}")
        for m in scenario["mutations"]:
            es = ENTITY_SETS[m["entity_set"]]
            row = self.get(es.name, m["key"])
            row.update({f: from_wire(v, es.types[f]) for f, v in m["changes"].items()})
        self.applied_scenarios.append(scenario_id)
        return scenario

    # --- helpers --------------------------------------------------------------------------------

    def _exists(self, set_name: str, **key: str) -> bool:
        return any(all(r[k] == v for k, v in key.items()) for r in self.rows[set_name])

    def _info_price(self, supplier: str, material: str, plant: str) -> Decimal:
        for r in self.rows["A_PurchasingInfoRecord"]:
            if (r["Supplier"], r["Material"], r["Plant"]) == (supplier, material, plant):
                return r["NetPriceAmount"]
        raise bad_request(f"No info record (price) for supplier {supplier}, material {material}, plant {plant}")
