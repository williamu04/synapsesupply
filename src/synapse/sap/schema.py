"""Entity sets served by the mock, using S/4HANA Cloud API service, entity and property names.

Each set carries a subset of the real properties — enough for the use case. Simplifications
versus the real APIs are marked "SIMPLIFIED". ZSCM_SYNAPSE_SRV is a custom (Z) service: S/4 has no
standard API for EUDR compliance profiles or transport lane rates.
"""
from dataclasses import dataclass, field

# Property types: str | date | decimal | int | bool


@dataclass(frozen=True)
class Nav:
    target: str
    on: tuple[tuple[str, str], ...]  # (source property, target property)
    many: bool = True


@dataclass(frozen=True)
class EntitySet:
    name: str
    service: str
    keys: tuple[str, ...]
    types: dict[str, str]
    navs: dict[str, Nav] = field(default_factory=dict)

    @property
    def namespace(self) -> str:
        return self.service.split(";")[0]


PO_SRV = "API_PURCHASEORDER_PROCESS_SRV"
STOCK_SRV = "API_MATERIAL_STOCK_SRV"
INB_SRV = "API_INBOUND_DELIVERY_SRV;v=0002"
MATDOC_SRV = "API_MATERIAL_DOCUMENT_SRV"
INFOREC_SRV = "API_INFORECORD_PROCESS_SRV"
Z_SRV = "ZSCM_SYNAPSE_SRV"

_SETS = [
    EntitySet("A_PurchaseOrder", PO_SRV, ("PurchaseOrder",), {
        "PurchaseOrder": "str", "CompanyCode": "str", "PurchaseOrderType": "str",
        "PurchasingOrganization": "str", "PurchasingGroup": "str", "Supplier": "str",
        "SupplyingPlant": "str", "PurchaseOrderDate": "date", "DocumentCurrency": "str",
        "CreatedByUser": "str",
    }, {"to_PurchaseOrderItem": Nav("A_PurchaseOrderItem", (("PurchaseOrder", "PurchaseOrder"),))}),
    EntitySet("A_PurchaseOrderItem", PO_SRV, ("PurchaseOrder", "PurchaseOrderItem"), {
        "PurchaseOrder": "str", "PurchaseOrderItem": "str", "Material": "str", "Plant": "str",
        "StorageLocation": "str", "OrderQuantity": "decimal", "PurchaseOrderQuantityUnit": "str",
        "NetPriceAmount": "decimal", "DocumentCurrency": "str", "IsCompletelyDelivered": "bool",
    }, {
        "to_PurchaseOrder": Nav("A_PurchaseOrder", (("PurchaseOrder", "PurchaseOrder"),), many=False),
        "to_ScheduleLine": Nav("A_PurchaseOrderScheduleLine", (
            ("PurchaseOrder", "PurchasingDocument"), ("PurchaseOrderItem", "PurchasingDocumentItem"))),
    }),
    EntitySet("A_PurchaseOrderScheduleLine", PO_SRV,
              ("PurchasingDocument", "PurchasingDocumentItem", "ScheduleLine"), {
        "PurchasingDocument": "str", "PurchasingDocumentItem": "str", "ScheduleLine": "str",
        "ScheduleLineDeliveryDate": "date", "ScheduleLineOrderQuantity": "decimal",
        "RoughGoodsReceiptQty": "decimal", "PurchaseOrderQuantityUnit": "str",
    }),
    # SIMPLIFIED: real key also includes Batch, Supplier, SDDocument, WBSElementInternalID, ...
    EntitySet("A_MatlStkInAcctMod", STOCK_SRV, ("Material", "Plant", "StorageLocation", "InventoryStockType"), {
        "Material": "str", "Plant": "str", "StorageLocation": "str", "InventoryStockType": "str",
        "MatlWrhsStkQtyInMatlBaseUnit": "decimal", "MaterialBaseUnit": "str",
    }),
    EntitySet("A_InbDeliveryHeader", INB_SRV, ("DeliveryDocument",), {
        "DeliveryDocument": "str", "Supplier": "str", "ReceivingPlant": "str", "DeliveryDate": "date",
        "CreationDate": "date", "LastChangeDate": "date",
    }, {"to_DeliveryDocumentItem": Nav("A_InbDeliveryItem", (("DeliveryDocument", "DeliveryDocument"),))}),
    EntitySet("A_InbDeliveryItem", INB_SRV, ("DeliveryDocument", "DeliveryDocumentItem"), {
        "DeliveryDocument": "str", "DeliveryDocumentItem": "str", "Material": "str", "Plant": "str",
        "ActualDeliveryQuantity": "decimal", "DeliveryQuantityUnit": "str",
        "ReferenceSDDocument": "str", "ReferenceSDDocumentItem": "str",
    }),
    EntitySet("A_MaterialDocumentItem", MATDOC_SRV, ("MaterialDocumentYear", "MaterialDocument", "MaterialDocumentItem"), {
        "MaterialDocumentYear": "str", "MaterialDocument": "str", "MaterialDocumentItem": "str",
        "Material": "str", "Plant": "str", "StorageLocation": "str", "GoodsMovementType": "str",
        "QuantityInBaseUnit": "decimal", "MaterialBaseUnit": "str", "PostingDate": "date",
        "PurchaseOrder": "str", "PurchaseOrderItem": "str", "Supplier": "str",
    }),
    # SIMPLIFIED: real API splits price and planned delivery time into org/plant data and conditions.
    EntitySet("A_PurchasingInfoRecord", INFOREC_SRV, ("PurchasingInfoRecord",), {
        "PurchasingInfoRecord": "str", "Supplier": "str", "Material": "str", "Plant": "str",
        "PurchasingOrganization": "str", "NetPriceAmount": "decimal", "Currency": "str",
        "OrderPriceUnit": "str", "MaterialPlannedDeliveryDurn": "int",
    }),
    EntitySet("SupplierCompliance", Z_SRV, ("Supplier",), {
        "Supplier": "str", "SupplierName": "str", "Country": "str", "CertificateType": "str",
        "CertificateNumber": "str", "CertificateValidTo": "date", "RiskBand": "str", "RiskScore": "decimal",
        "RiskScoredAt": "date", "DeforestationAlert": "bool", "GeolocationProvided": "bool",
        "DeclaredAnnualCapacity": "decimal", "YtdDeliveredQty": "decimal", "QuantityUnit": "str",
    }),
    EntitySet("TransportLane", Z_SRV, ("LaneId",), {
        "LaneId": "str", "FromPlant": "str", "ToPlant": "str", "Material": "str", "Mode": "str",
        "CostPerUnit": "decimal", "Currency": "str", "TransitDays": "int", "MaxDailyQty": "decimal",
        "Unit": "str",
    }),
]

ENTITY_SETS: dict[str, EntitySet] = {es.name: es for es in _SETS}
SERVICES: dict[str, list[str]] = {}
for _es in _SETS:
    SERVICES.setdefault(_es.service, []).append(_es.name)
