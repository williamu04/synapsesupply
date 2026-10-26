"""Process entrypoint, configured from the environment.

  uv run uvicorn synapse.api.main:app --port 8080

  SYNAPSE_ERP_URL          S/4 or mock base URL. Unset: an in-process mock (demo mode).
  SYNAPSE_ERP_USER/_PASSWORD  basic auth for S/4 (optional)
  SYNAPSE_FALLBACK_MOCK=1  fail over to an in-process mock if SYNAPSE_ERP_URL is unreachable
  SYNAPSE_DEMO=1           enable /demo routes against SYNAPSE_ERP_URL (it must be the mock)
  SYNAPSE_PLANNER          auto (Claude, autopilot fallback; default) | autopilot
  SYNAPSE_API_KEY          require this x-api-key on every route except /health
  SYNAPSE_RECORDINGS_DIR   directory of *.jsonl recordings for replay (default ./recordings)
  SYNAPSE_CORS_ORIGINS     comma-separated origins allowed to call the API (only for a separately hosted UI)
  SYNAPSE_UI_DIR           built console to serve at /console (default ./ui/dist, if present)
  SYNAPSE_DEMO_BOOT_SCENARIO  demo mode: stage this scenario (e.g. SC-01) at every startup
"""
import os
from datetime import date

from starlette.testclient import TestClient

from synapse.agent import models
from synapse.agent.config import Settings
from synapse.agent.service import CaseService
from synapse.aws_store import stores_from_env
from synapse.env import load_env
from synapse.erp import ErpClient, http_client
from synapse.mock_s4.app import create_app as create_mock
from synapse.policy.engine import PolicyEngine
from synapse.sap.rpt import delay_predictor_from_env

from .app import DemoControl, create_api


def build_service() -> tuple[CaseService, DemoControl | None]:
    """The case service and (in demo mode) the mock's control, wired from the environment.
    Shared by this API process and the AgentCore Runtime entry point (synapse.agentcore)."""
    load_env()
    settings = Settings()
    erp_url = os.environ.get("SYNAPSE_ERP_URL")
    mock = TestClient(create_mock()) if not erp_url or os.environ.get("SYNAPSE_FALLBACK_MOCK") == "1" else None

    def erp_factory(on_failover):
        if not erp_url:
            return ErpClient(mock, on_failover=on_failover)
        primary = http_client(erp_url, user=os.environ.get("SYNAPSE_ERP_USER"),
                              password=os.environ.get("SYNAPSE_ERP_PASSWORD"))
        return ErpClient(primary, fallback=mock, on_failover=on_failover)

    demo = None
    if not erp_url:
        demo = DemoControl(mock)
    elif os.environ.get("SYNAPSE_DEMO") == "1":
        demo = DemoControl(http_client(erp_url, user=os.environ.get("SYNAPSE_ERP_USER"),
                                       password=os.environ.get("SYNAPSE_ERP_PASSWORD")))

    llm = os.environ.get("SYNAPSE_PLANNER", "auto") == "auto"
    repo, trace_store, archive = stores_from_env()
    service = CaseService(
        erp_factory=erp_factory, policy=PolicyEngine(), repo=repo, trace_store=trace_store, archive=archive,
        business_date=demo.as_of if demo else date.today, settings=settings,
        delay_predictor=delay_predictor_from_env(),
        planner_model=(lambda: models.reasoning_model(settings)) if llm else None,
        triage_model=(lambda: models.triage_model(settings)) if llm else None)
    return service, demo


def build():
    service, demo = build_service()
    return create_api(service, demo=demo, api_key=os.environ.get("SYNAPSE_API_KEY"),
                      recordings_dir=os.environ.get("SYNAPSE_RECORDINGS_DIR"),
                      cors_origins=[o for o in os.environ.get("SYNAPSE_CORS_ORIGINS", "").split(",") if o],
                      ui_dir=os.environ.get("SYNAPSE_UI_DIR", "ui/dist"),
                      boot_scenario=os.environ.get("SYNAPSE_DEMO_BOOT_SCENARIO"),
                      s4_app=_exposed_s4(demo))


def _exposed_s4(demo: DemoControl | None):
    """The in-process mock S/4 as an ASGI app, when SYNAPSE_EXPOSE_S4=1 (Cloud Foundry only)."""
    if os.environ.get("SYNAPSE_EXPOSE_S4") != "1" or demo is None:
        return None
    return getattr(demo.client, "app", None)  # the TestClient wrapping the mock


app = build()
