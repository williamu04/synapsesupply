"""ERP poller (Lambda, every minute): finds inbound deliveries that slipped past their PO schedule
line and queues one ASN_DELAY case per PO item on SQS FIFO.

Reads S/4 over OData: A_InbDeliveryHeader changed in the last LOOKBACK_DAYS (with its items), then
each referenced A_PurchaseOrderScheduleLine. A case already in the Cases table is not queued again;
SQS FIFO deduplication (case + new delivery date) covers the rest.

Standard library and boto3 only. Environment: S4_URL, SECRET_ID (JSON with SYNAPSE_ERP_USER and
SYNAPSE_ERP_PASSWORD), QUEUE_URL, CASES_TABLE, LOOKBACK_DAYS (default 30).
"""
import base64
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

INB = "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV;v=0002"
PO = "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV"

Get = Callable[[str, dict], dict]


def odata_date(value: str | None) -> date | None:
    """`/Date(1793750400000)/` (OData v2) -> date."""
    if not value:
        return None
    millis = int(value[value.index("(") + 1:value.index(")")].split("+")[0].split("-")[0])
    return datetime.fromtimestamp(millis / 1000, UTC).date()


def find_delays(get: Get, since: date) -> list[dict]:
    headers = get(f"{INB}/A_InbDeliveryHeader", {
        "$filter": f"LastChangeDate ge datetime'{since.isoformat()}T00:00:00'",
        "$expand": "to_DeliveryDocumentItem"})["d"]["results"]
    delays = []
    for header in headers:
        delivery_date = odata_date(header.get("DeliveryDate"))
        for item in header.get("to_DeliveryDocumentItem", {}).get("results", []):
            po, po_item = item.get("ReferenceSDDocument"), item.get("ReferenceSDDocumentItem")
            if not (po and po_item and delivery_date):
                continue
            lines = get(f"{PO}/A_PurchaseOrderScheduleLine", {
                "$filter": f"PurchasingDocument eq '{po}' and PurchasingDocumentItem eq '{po_item}'"})["d"]["results"]
            planned = min((d for d in (odata_date(line.get("ScheduleLineDeliveryDate")) for line in lines) if d),
                          default=None)
            if planned and delivery_date > planned:
                delays.append({
                    "case_id": f"{po}-{po_item}", "delivery_document": header["DeliveryDocument"],
                    "supplier": header.get("Supplier"), "plant": item.get("Plant") or header.get("ReceivingPlant"),
                    "material": item.get("Material"), "planned_date": planned.isoformat(),
                    "new_date": delivery_date.isoformat(), "delay_days": (delivery_date - planned).days})
    return delays


def case_message(delay: dict, now: datetime) -> dict:
    """A `synapse.contracts.CaseMessage` as JSON."""
    return {"case_id": delay["case_id"], "process_type": "ASN_DELAY", "payload_source": "ODATA_POLLER",
            "timestamp": now.isoformat(), "raw_payload": {k: v for k, v in delay.items() if k != "case_id"}}


def http_get(base_url: str, user: str, password: str) -> Get:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()

    def get(path: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params | {"$format": "json"}, quote_via=urllib.parse.quote)
        request = urllib.request.Request(f"{base_url.rstrip('/')}{path}?{query}",
                                         headers={"authorization": f"Basic {token}", "accept": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    return get


def poll(get: Get, sqs, dynamodb, queue_url: str, cases_table: str, since: date, now: datetime) -> dict:
    queued, known = [], []
    for delay in find_delays(get, since):
        case_id = delay["case_id"]
        if dynamodb.get_item(TableName=cases_table, Key={"case_id": {"S": case_id}}).get("Item"):
            known.append(case_id)
            continue
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(case_message(delay, now)),
                         MessageGroupId=case_id, MessageDeduplicationId=f"{case_id}:{delay['new_date']}")
        queued.append(case_id)
    return {"queued": queued, "already_cases": known}


_secret: dict | None = None


def handler(event, context):
    import boto3
    global _secret
    if _secret is None:
        _secret = json.loads(boto3.client("secretsmanager").get_secret_value(
            SecretId=os.environ["SECRET_ID"])["SecretString"])
    now = datetime.now(UTC)
    since = now.date() - timedelta(days=int(os.environ.get("LOOKBACK_DAYS", "30")))
    result = poll(http_get(os.environ["S4_URL"], _secret["SYNAPSE_ERP_USER"], _secret["SYNAPSE_ERP_PASSWORD"]),
                  boto3.client("sqs"), boto3.client("dynamodb"), os.environ["QUEUE_URL"],
                  os.environ["CASES_TABLE"], since, now)
    print(json.dumps(result))
    return result
