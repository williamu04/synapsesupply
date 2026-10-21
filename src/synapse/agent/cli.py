"""Run demo scenarios end to end from the terminal — for development, rehearsals and recordings.

  uv run python -m synapse.agent.cli SC-01                      # in-process mock S/4, LLM if reachable
  uv run python -m synapse.agent.cli all --planner autopilot    # no model at all
  uv run python -m synapse.agent.cli SC-01 --approve "Planner Dewi"
  uv run python -m synapse.agent.cli SC-01 --erp-url http://localhost:8000 --record sc01.jsonl
  uv run python -m synapse.agent.cli SC-02 --erp-url http://unreachable:9 --fallback-mock   # failover drill
"""
import argparse
import sys
from datetime import date

import httpx
from starlette.testclient import TestClient

from synapse.env import load_env
from synapse.erp import ErpClient, http_client
from synapse.mock_s4.app import create_app
from synapse.policy.engine import PolicyEngine
from synapse.sap.rpt import delay_predictor_from_env

from . import models
from .cases import InMemoryCaseRepository
from .config import Settings
from .scenarios import scenario_message
from .service import CaseService
from .trace import JsonlRecorder, format_event


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run SynapseSupply demo scenarios")
    ap.add_argument("scenario", help="SC-01, SC-02, SC-03 or all")
    ap.add_argument("--planner", choices=["auto", "autopilot"], default="auto",
                    help="auto: Claude via Bedrock (AI Core fallback), autopilot if unreachable")
    ap.add_argument("--erp-url", help="S/4 or mock base URL; default: in-process mock")
    ap.add_argument("--fallback-mock", action="store_true", help="fail over to an in-process mock if --erp-url is down")
    ap.add_argument("--approve", metavar="APPROVER", help="approve escalated cases as this planner")
    ap.add_argument("--record", metavar="PATH", help="append trace events to a JSONL file (UI replay)")
    ap.add_argument("--quiet", action="store_true", help="print summaries only")
    args = ap.parse_args(argv)
    load_env()

    mock = TestClient(create_app())
    control = http_client(args.erp_url) if args.erp_url and not args.fallback_mock else mock
    try:
        today = date.fromisoformat(control.get("/health").json()["as_of"])
    except (httpx.HTTPError, KeyError, ValueError):
        today = date.today()
    all_scenarios = control.get("/admin/scenarios").json()["scenarios"]
    wanted = [s for s in all_scenarios if args.scenario in ("all", s["scenario_id"])]
    if not wanted:
        print(f"Unknown scenario {args.scenario}; have {[s['scenario_id'] for s in all_scenarios]}", file=sys.stderr)
        return 2

    def erp_factory(on_failover):
        if not args.erp_url:
            return ErpClient(mock, on_failover=on_failover)
        return ErpClient(http_client(args.erp_url), fallback=mock if args.fallback_mock else None,
                         on_failover=on_failover)

    sinks = [] if args.quiet else [lambda e: print(format_event(e), flush=True)]
    if args.record:
        sinks.append(JsonlRecorder(args.record))
    settings = Settings()
    llm = args.planner == "auto"
    service = CaseService(erp_factory=erp_factory, policy=PolicyEngine(), repo=InMemoryCaseRepository(),
                          business_date=lambda: today, settings=settings, sinks=sinks,
                          delay_predictor=delay_predictor_from_env(),
                          planner_model=(lambda: models.reasoning_model(settings)) if llm else None,
                          triage_model=(lambda: models.triage_model(settings)) if llm else None)

    exit_code = 0
    for sc in wanted:
        control.post("/admin/reset")
        control.post(f"/admin/scenarios/{sc['scenario_id']}/apply")
        print(f"\n=== {sc['scenario_id']}: {sc['title']}  (expected {sc['expected']['policy_effect']})")
        record = service.handle(scenario_message(sc))
        if args.approve and record.status.value == "AWAITING_APPROVAL":
            record = service.approve(record.case_id, args.approve)
        print(f"--> {record.status.value}: {record.summary}")
        if record.status.value == "FAILED":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
