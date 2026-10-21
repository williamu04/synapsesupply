"""Delivery-delay prediction: history extraction, the empirical fallback, the RPT-1 wire contract,
and how predictions reach the agent's options and confidence."""
import json
from datetime import date

import httpx
import pytest
from agent_helpers import TODAY, message, scenario

from synapse.agent.toolkit import CaseToolkit
from synapse.agent.trace import Tracer
from synapse.domain.delays import PREDICT, DelayEstimate, EmpiricalDelayPredictor, delivery_history, query_row
from synapse.domain.options import plan_confidence
from synapse.erp import ErpClient
from synapse.policy.engine import PolicyEngine
from synapse.sap.rpt import (
    RptDelayPredictor,
    RptError,
    build_request,
    delay_predictor_from_env,
    parse_response,
)

D = date


def hist(supplier, delay):
    return {"SUPPLIER": supplier, "PLANT": "1100", "MATERIAL": "WC", "PLANNED_LEAD_DAYS": 2, "QUANTITY": 2300.0,
            "WEEKDAY": "Mon", "DELAY_DAYS": delay, "LATE": "Y" if delay > 0 else "N"}


def query(supplier):
    return query_row(supplier=supplier, plant="1100", material="WC", lead_days=1, quantity=920, arrival=D(2026, 11, 1))


# --- history ---------------------------------------------------------------------------------------

def test_delivery_history_from_s4_rows():
    pos = [{"PurchaseOrder": "A", "PurchaseOrderDate": D(2026, 10, 1), "Supplier": "S1"},
           {"PurchaseOrder": "B", "PurchaseOrderDate": D(2026, 10, 2), "Supplier": "S2"}]
    items = [
        {"PurchaseOrder": "A", "PurchaseOrderItem": "10", "Plant": "1100", "Material": "WC", "OrderQuantity": 100,
         "to_ScheduleLine": [{"ScheduleLineDeliveryDate": D(2026, 10, 3)}]},
        {"PurchaseOrder": "B", "PurchaseOrderItem": "10", "Plant": "1200", "Material": "WC", "OrderQuantity": 50,
         "to_ScheduleLine": [{"ScheduleLineDeliveryDate": D(2026, 10, 5)}]},
        {"PurchaseOrder": "C", "PurchaseOrderItem": "10", "Plant": "1200", "Material": "WC", "OrderQuantity": 50,
         "to_ScheduleLine": [{"ScheduleLineDeliveryDate": D(2026, 10, 5)}]},  # no header in window -> skipped
    ]
    docs = [{"GoodsMovementType": "101", "PurchaseOrder": "A", "PurchaseOrderItem": "10", "PostingDate": D(2026, 10, 5)},
            {"GoodsMovementType": "101", "PurchaseOrder": "A", "PurchaseOrderItem": "10", "PostingDate": D(2026, 10, 4)},
            {"GoodsMovementType": "101", "PurchaseOrder": "B", "PurchaseOrderItem": "10", "PostingDate": D(2026, 10, 4)},
            {"GoodsMovementType": "261", "PurchaseOrder": None, "PurchaseOrderItem": None, "PostingDate": D(2026, 10, 4)}]
    rows = delivery_history(pos, items, docs)
    assert [(r["SUPPLIER"], r["DELAY_DAYS"], r["LATE"], r["PLANNED_LEAD_DAYS"]) for r in rows] == [
        ("S1", 1, "Y", 2), ("S2", -1, "N", 3)]
    assert rows[0]["WEEKDAY"] == "Sat"


def test_query_rows_carry_placeholders():
    q = query("S1")
    assert q["DELAY_DAYS"] == q["LATE"] == PREDICT and q["WEEKDAY"] == "Sun"


# --- empirical fallback ----------------------------------------------------------------------------

def test_empirical_predictor():
    history = [hist("S1", d) for d in (0, 0, 1, 2)] + [hist("S2", d) for d in (0, -1, 0, 0)]
    s1, s2, new = EmpiricalDelayPredictor().predict(history, [query("S1"), query("S2"), query("S9")])
    assert (s1.expected_delay_days, s1.late_probability) == (0.75, 0.5)    # (2 late + 1) / (4 + 2)
    assert (s2.expected_delay_days, s2.late_probability) == (0.0, 0.17)    # early counts as on time
    assert new.late_probability == pytest.approx(0.3)                       # unknown supplier: everyone's rate
    assert EmpiricalDelayPredictor().predict([], [query("S1")])[0].late_probability == 0.5


def test_late_risk_lowers_confidence():
    base = {"covers_shortfall": True, "arrives_in_time": True, "demand_samples": 90, "lead_time_samples": 30,
            "erp_degraded": False}
    assert plan_confidence(**base, late_risk=0.49) == 0.97
    assert plan_confidence(**base, late_risk=0.5) == 0.87


# --- RPT-1 wire contract ---------------------------------------------------------------------------

def rpt_response(*items, with_ids=True):
    preds = [({"ID": f"Q{n}"} if with_ids else {}) | {"DELAY_DAYS": [{"prediction": delay}],
                                                      "LATE": [{"prediction": late, "confidence": conf}]}
             for n, (delay, late, conf) in enumerate(items)]
    return {"id": "r-1", "status": {"code": 0, "message": "ok"}, "predictions": preds,
            "metadata": {"num_rows": 3, "num_columns": 9, "num_predictions": 2 * len(items),
                         "num_query_rows": len(items)}}


def test_build_request_follows_the_sdk_model():
    body = build_request([hist("0000100001", 1)], [query("0000100004")])
    assert body["index_column"] == "ID"
    assert [r["ID"] for r in body["rows"]] == ["H0", "Q0"]
    assert body["rows"][1]["DELAY_DAYS"] == "[PREDICT]"
    targets = {t["name"]: t["task_type"] for t in body["prediction_config"]["target_columns"]}
    assert targets == {"DELAY_DAYS": "regression", "LATE": "classification"}
    assert body["data_schema"]["SUPPLIER"] == {"dtype": "string"}  # keep leading zeros


def test_parse_response():
    late, on_time = parse_response(rpt_response((1.6, "Y", 0.8), (-0.2, "N", 0.9)), 2, "sap-rpt-1.6")
    assert (late.expected_delay_days, late.late_probability) == (1.6, 0.8)
    assert (on_time.expected_delay_days, on_time.late_probability) == (0.0, 0.1)
    by_order = parse_response(rpt_response((1, "Y", None), with_ids=False), 1, "m")[0]
    assert by_order.late_probability == 1.0
    with pytest.raises(RptError, match="predictions for 2"):
        parse_response(rpt_response((1, "Y", 0.5)), 2, "m")
    with pytest.raises(RptError, match="status 400"):
        parse_response({"status": {"code": 400, "message": "bad"}, "predictions": []}, 1, "m")


class FakeAICore:
    """Token endpoint + RPT-1 predict endpoint, recording what the client sends."""

    def __init__(self, fail_predict=False):
        self.requests: list[httpx.Request] = []
        self.fail_predict = fail_predict

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if self.fail_predict:
            return httpx.Response(503, text="unavailable")
        n = sum(1 for r in json.loads(request.content)["rows"] if r["DELAY_DAYS"] == "[PREDICT]")
        return httpx.Response(200, json=rpt_response(*[(0.4, "N", 0.7)] * n))


def predictor(fake: FakeAICore) -> RptDelayPredictor:
    return RptDelayPredictor(httpx.Client(transport=httpx.MockTransport(fake)),
                             auth_url="https://auth.example/oauth/token", client_id="id", client_secret="secret",
                             base_url="https://ai.example", deployment_id="d76cf689a05d504f")


def test_rpt_predictor_calls_ai_core():
    fake = FakeAICore()
    p = predictor(fake)
    out = p.predict([hist("S1", 1)], [query("S1"), query("S2")])
    assert [e.method for e in out] == ["sap-rpt-1.6"] * 2 and out[0].late_probability == 0.3
    p.predict([hist("S1", 1)], [query("S1")])
    token_calls = [r for r in fake.requests if r.url.path == "/oauth/token"]
    predict_calls = [r for r in fake.requests if r.url.path.endswith("/predict")]
    assert len(token_calls) == 1  # cached
    assert predict_calls[0].url.path == "/v2/inference/deployments/d76cf689a05d504f/predict"
    assert predict_calls[0].headers["authorization"] == "Bearer tok"
    assert predict_calls[0].headers["ai-resource-group"] == "default"


def test_rpt_outage_falls_back_and_says_so():
    p = predictor(FakeAICore(fail_predict=True))
    [e] = p.predict([hist("S1", 1)], [query("S1")])
    assert e.method == "empirical (RPT-1 unavailable)" and "503" in p.last_error


def test_predictor_from_env(monkeypatch):
    for k in ("AICORE_AUTH_URL", "AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    assert isinstance(delay_predictor_from_env(), EmpiricalDelayPredictor)
    for k in ("AICORE_AUTH_URL", "AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_BASE_URL"):
        monkeypatch.setenv(k, "https://x" if "URL" in k else "v")
    assert isinstance(delay_predictor_from_env(), RptDelayPredictor)


# --- reaching the agent ----------------------------------------------------------------------------

class FixedPredictor:
    method = "fixed"

    def __init__(self, late: float):
        self.late = late
        self.seen: list = []

    def predict(self, history, queries):
        self.seen.append((len(history), [q["SUPPLIER"] for q in queries]))
        return [DelayEstimate(1.0, self.late, self.method) for _ in queries]


def kit(client, sid, predictor) -> CaseToolkit:
    sc = scenario(client, sid)
    return CaseToolkit(message(sc), ErpClient(client), PolicyEngine(), Tracer(sc["case_id"]), TODAY,
                       delay_predictor=predictor)


def test_options_carry_delivery_risk(client):
    p = FixedPredictor(0.2)
    k = kit(client, "SC-01", p)
    k.get_case_details()
    found = k.find_sourcing_options("1100", "WC-ACACIA", 920, "2026-11-02")
    assert found["delay_prediction"]["method"] == "fixed" and found["delay_prediction"]["history_rows"] > 50
    by_id = {o["option_id"]: o for o in found["options"]}
    assert by_id["PO:0000100003"]["on_time_probability"] == 0.8
    assert by_id["PO:0000100003"]["expected_arrival"] == "2026-11-02"  # Sun 1 Nov + 1 day
    assert "on_time_probability" not in by_id["STO:1200"]  # own trucks: not predicted
    history_rows, suppliers = p.seen[0]
    assert history_rows == found["delay_prediction"]["history_rows"]
    assert set(suppliers) == {"0000100001", "0000100002", "0000100003", "0000100004", "0000100005"}


def test_high_late_risk_sends_an_otherwise_autonomous_order_to_a_human(client):
    k = kit(client, "SC-02", FixedPredictor(0.7))
    k.get_case_details()
    k.analyze_stock_position("1100", "LOG-EUCA")
    k.find_sourcing_options("1100", "LOG-EUCA", 430, "2026-11-01")
    result = k.submit_action("PO:0000100004", 430, "Only compliant supplier in time")
    assert result["confidence"] == 0.87 and result["decision"] == "ESCALATE"
