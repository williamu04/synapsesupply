from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from synapse.contracts import (
    ActionProposal,
    ActionType,
    CaseMessage,
    GateOutcome,
    PolicyRequest,
    TraceEvent,
    make_case_id,
)

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)


def test_make_case_id_normalises_item_number():
    assert make_case_id("4500000093", "00010") == "4500000093-10"


def test_case_message_round_trip():
    msg = CaseMessage(case_id="4500000093-10", process_type="ASN_DELAY", payload_source="ODATA_POLLER",
                      timestamp=NOW, raw_payload={"DeliveryDocument": "180000001"})
    assert CaseMessage.model_validate_json(msg.model_dump_json()) == msg


@pytest.mark.parametrize("bad", [
    {"case_id": "4500000093"},
    {"case_id": "45-10; drop"},
    {"timestamp": datetime(2026, 10, 31, 9, 0)},
    {"process_type": "SOMETHING"},
    {"unexpected": 1},
])
def test_case_message_rejects(bad):
    data = {"case_id": "4500000093-10", "process_type": "ASN_DELAY", "payload_source": "ODATA_POLLER",
            "timestamp": NOW, "raw_payload": {}} | bad
    with pytest.raises(ValidationError):
        CaseMessage(**data)


def proposal(**kw):
    base = {"action_type": ActionType.CREATE_STOCK_TRANSFER, "plant": "1100", "material": "WC-ACACIA",
            "quantity": 911, "unit": "TO", "delivery_date": date(2026, 11, 1), "supplying_plant": "1200",
            "financial_impact_usd": 8199, "confidence": 0.93,
            "rationale": "Only compliant option arriving before day 2"}
    return ActionProposal(**(base | kw))


def test_valid_stock_transfer():
    assert proposal().supplying_plant == "1200"


@pytest.mark.parametrize("kw, msg", [
    ({"supplying_plant": "1100"}, "supplying_plant"),
    ({"supplying_plant": None}, "supplying_plant"),
    ({"action_type": ActionType.CREATE_PURCHASE_ORDER, "supplier": None}, "supplier"),
    ({"action_type": ActionType.CREATE_PURCHASE_ORDER, "supplier": "0000100004"}, "compliance_outcome"),
    ({"action_type": ActionType.RESCHEDULE_PO_LINE}, "reference_document"),
    ({"confidence": 1.2}, "confidence"),
    ({"quantity": 0}, "quantity"),
])
def test_invalid_proposals(kw, msg):
    with pytest.raises(ValidationError, match=msg):
        proposal(**kw)


def test_purchase_order_with_gate_result_is_valid():
    p = proposal(action_type=ActionType.CREATE_PURCHASE_ORDER, supplier="0000100004", supplying_plant=None,
                 compliance_outcome=GateOutcome.PASS)
    assert p.compliance_outcome is GateOutcome.PASS


def test_policy_request_uses_namespaced_actions():
    req = PolicyRequest(principal="agent:synapse", action="sap:create_stock_transfer", resource="A_PurchaseOrder",
                        context={"confidence": 0.93, "financial_impact_usd": 8199})
    assert req.model_dump(mode="json")["action"] == "sap:create_stock_transfer"


def test_trace_event_requires_aware_timestamp():
    with pytest.raises(ValidationError):
        TraceEvent(case_id="4500000093-10", seq=0, ts=datetime(2026, 10, 31), kind="PLAN", title="x")
