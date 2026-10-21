"""SAP RPT-1 (tabular foundation model on SAP AI Core) as the delivery-delay predictor.

RPT-1 predicts in-context: we send delivered-order history plus the candidate orders with
`[PREDICT]` in the target columns, and it fills them in — no training step. Request and response
follow the SAP Cloud SDK for AI models (gen_ai_hub.proxy.native.sap.models: RPTRequest/RPTResponse),
called over plain HTTP as in BTP_Instructions/README.md § Tabular Prediction.

Configuration (same variables as the Joule A2A sample's .env):
  AICORE_AUTH_URL  AICORE_CLIENT_ID  AICORE_CLIENT_SECRET  AICORE_BASE_URL  AICORE_RESOURCE_GROUP
  SYNAPSE_RPT_DEPLOYMENT_ID   (default d76cf689a05d504f = sap-rpt-1.6 in the hackathon tenant)

Any failure falls back to the empirical predictor and says so in `method`, so the trace and the UI
never present a fallback estimate as an RPT-1 prediction.
"""
import logging
import os
import time

import httpx

from synapse.domain.delays import (
    FEATURES,
    PREDICT,
    TARGETS,
    DelayEstimate,
    DelayPredictor,
    EmpiricalDelayPredictor,
)

log = logging.getLogger(__name__)

DEFAULT_DEPLOYMENT = "d76cf689a05d504f"
MAX_CONTEXT_ROWS = 2_000
SCHEMA = {"SUPPLIER": "string", "PLANT": "string", "MATERIAL": "string", "PLANNED_LEAD_DAYS": "numeric",
          "QUANTITY": "numeric", "WEEKDAY": "string", "DELAY_DAYS": "numeric", "LATE": "string"}


class RptError(RuntimeError):
    pass


def build_request(history: list[dict], queries: list[dict]) -> dict:
    rows = [{"ID": f"H{n}", **{c: r[c] for c in FEATURES + TARGETS}} for n, r in enumerate(history[-MAX_CONTEXT_ROWS:])]
    rows += [{"ID": f"Q{n}", **{c: q[c] for c in FEATURES + TARGETS}} for n, q in enumerate(queries)]
    return {
        "prediction_config": {"target_columns": [
            {"name": "DELAY_DAYS", "prediction_placeholder": PREDICT, "task_type": "regression"},
            {"name": "LATE", "prediction_placeholder": PREDICT, "task_type": "classification"},
        ]},
        "index_column": "ID",
        "rows": rows,
        # Explicit types: supplier numbers like "0000100001" must stay strings.
        "data_schema": {c: {"dtype": t} for c, t in SCHEMA.items()},
    }


def parse_response(data: dict, n_queries: int, method: str) -> list[DelayEstimate]:
    """`predictions` holds one object per query row: target column -> [{prediction, confidence}],
    plus the index column when the service returns it."""
    status = data.get("status") or {}
    if status.get("code") not in (None, 0, 200):
        raise RptError(f"RPT-1 status {status.get('code')}: {status.get('message')}")
    predictions = data.get("predictions") or []
    by_id = {p["ID"]: p for p in predictions if isinstance(p, dict) and isinstance(p.get("ID"), str)}
    ordered = [by_id[f"Q{n}"] for n in range(n_queries)] if len(by_id) >= n_queries else predictions
    if len(ordered) != n_queries:
        raise RptError(f"RPT-1 returned {len(ordered)} predictions for {n_queries} query rows")
    out = []
    for p in ordered:
        delay = float(_first(p["DELAY_DAYS"])["prediction"])
        late = _first(p["LATE"])
        conf = late.get("confidence")
        is_late = str(late["prediction"]).upper() == "Y"
        p_late = (conf if is_late else 1 - conf) if conf is not None else float(is_late)
        out.append(DelayEstimate(round(max(delay, 0.0), 2), round(min(max(p_late, 0.0), 1.0), 2), method))
    return out


def _first(value) -> dict:
    item = value[0] if isinstance(value, list) else value
    if not isinstance(item, dict) or "prediction" not in item:
        raise RptError(f"Unexpected RPT-1 prediction item: {value!r}")
    return item


class RptDelayPredictor:
    method = "sap-rpt-1.6"

    def __init__(self, client: httpx.Client, *, auth_url: str, client_id: str, client_secret: str, base_url: str,
                 resource_group: str = "default", deployment_id: str = DEFAULT_DEPLOYMENT,
                 fallback: DelayPredictor | None = None):
        self.client, self.auth_url = client, auth_url
        self.client_id, self.client_secret = client_id, client_secret
        self.predict_url = f"{base_url.rstrip('/')}/v2/inference/deployments/{deployment_id}/predict"
        self.resource_group = resource_group
        self.fallback = fallback or EmpiricalDelayPredictor()
        self._token: tuple[str, float] | None = None
        self.last_error: str | None = None

    def predict(self, history: list[dict], queries: list[dict]) -> list[DelayEstimate]:
        if not queries:
            return []
        try:
            r = self.client.post(self.predict_url, json=build_request(history, queries), timeout=30, headers={
                "Authorization": f"Bearer {self._access_token()}", "AI-Resource-Group": self.resource_group})
            if r.status_code >= 400:
                raise RptError(f"HTTP {r.status_code}: {r.text[:200]}")
            self.last_error = None
            return parse_response(r.json(), len(queries), self.method)
        except (httpx.HTTPError, RptError, KeyError, TypeError, ValueError) as e:
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("RPT-1 unavailable, using empirical delay estimate: %s", self.last_error)
            return [DelayEstimate(d.expected_delay_days, d.late_probability, "empirical (RPT-1 unavailable)")
                    for d in self.fallback.predict(history, queries)]

    def _access_token(self) -> str:
        if self._token and self._token[1] > time.monotonic() + 60:
            return self._token[0]
        r = self.client.post(self.auth_url, data={"grant_type": "client_credentials"},
                             auth=(self.client_id, self.client_secret), timeout=15)
        if r.status_code >= 400:
            raise RptError(f"AI Core token request failed: HTTP {r.status_code}")
        body = r.json()
        self._token = (body["access_token"], time.monotonic() + float(body.get("expires_in", 3600)))
        return self._token[0]


def delay_predictor_from_env() -> DelayPredictor:
    env = os.environ
    if not all(env.get(k) for k in ("AICORE_AUTH_URL", "AICORE_CLIENT_ID", "AICORE_CLIENT_SECRET", "AICORE_BASE_URL")):
        return EmpiricalDelayPredictor()
    return RptDelayPredictor(httpx.Client(), auth_url=env["AICORE_AUTH_URL"], client_id=env["AICORE_CLIENT_ID"],
                             client_secret=env["AICORE_CLIENT_SECRET"], base_url=env["AICORE_BASE_URL"],
                             resource_group=env.get("AICORE_RESOURCE_GROUP", "default"),
                             deployment_id=env.get("SYNAPSE_RPT_DEPLOYMENT_ID", DEFAULT_DEPLOYMENT))
