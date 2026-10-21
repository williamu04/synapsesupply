"""Regression eval: run each demo scenario N times with the real model and check the outcome.

  uv run python scripts/eval_scenarios.py --runs 3            # all scenarios, model from .env
  uv run python scripts/eval_scenarios.py --runs 5 --only SC-03

Each run uses a fresh in-process mock S/4. A run passes when:
  * the policy effect matches the scenario's `expected.policy_effect`,
  * the submitted option matches the expected action (SC-01 transfer, SC-02 Jambi Pulpwood PO,
    SC-03 the requested Siak Agro Wood PO),
  * the planner was the model (no fall-back to the deterministic autopilot).
Costs real model calls (Claude via SAP AI Core or Bedrock): roughly one agent run per scenario per run.
"""
import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

from synapse.agent import models
from synapse.agent.cases import InMemoryCaseRepository
from synapse.agent.config import Settings
from synapse.agent.scenarios import scenario_message
from synapse.agent.service import CaseService
from synapse.env import load_env
from synapse.erp import ErpClient
from synapse.mock_s4.app import create_app
from synapse.policy.engine import PolicyEngine
from synapse.sap.rpt import delay_predictor_from_env

EXPECTED_OPTION = {"SC-01": "STO:1200", "SC-02": "PO:0000100004", "SC-03": "PO:0000100003"}

# Paths where the right answer is to do nothing (the riskiest failure is an unneeded order):
#   NOACT    - SC-01's case without the delay: the ASN arrives on time, stock stays above safety stock
#   QUESTION - a buyer asks about stock instead of ordering
EXTRA = {
    "NOACT": {"base": "SC-01", "apply": False},
    "QUESTION": {"base": "SC-03", "apply": False,
                 "utterance": "How much acacia chip stock does Mill Riau-1 have, and when does it run low?"},
}


def run_once(scenario_id: str, settings: Settings, policy: PolicyEngine) -> dict:
    mock = TestClient(create_app())
    extra = EXTRA.get(scenario_id, {})
    base = extra.get("base", scenario_id)
    scenario = next(s for s in mock.get("/admin/scenarios").json()["scenarios"] if s["scenario_id"] == base)
    if extra.get("utterance"):
        scenario = scenario | {"utterance": extra["utterance"]}
    if extra.get("apply", True):
        mock.post(f"/admin/scenarios/{base}/apply")
    today = datetime.fromisoformat(mock.get("/health").json()["as_of"]).date()
    service = CaseService(erp_factory=lambda cb: ErpClient(mock, on_failover=cb), policy=policy,
                          repo=InMemoryCaseRepository(), business_date=lambda: today, settings=settings,
                          planner_model=lambda: models.reasoning_model(settings),
                          triage_model=lambda: models.triage_model(settings),
                          delay_predictor=delay_predictor_from_env())
    t = time.monotonic()
    record = service.handle(scenario_message(scenario))
    seconds = time.monotonic() - t
    events = service.trace(record.case_id)
    planner = events[-1].detail.get("planner")
    effect = record.policy.effect.value if record.policy else None
    option = record.proposal.option_id if record.proposal else None
    writes = mock.get("/admin/audit").json()["writes"]
    if extra:
        checks = {"no_action": record.status.value == "NO_ACTION_NEEDED", "no_erp_write": not writes,
                  "model_planned": planner == "llm"}
    else:
        checks = {
            "effect": effect == scenario["expected"]["policy_effect"],
            "option": option == EXPECTED_OPTION.get(scenario_id, option),
            "model_planned": planner == "llm",
        }
    return {"scenario": scenario_id, "passed": all(checks.values()), "checks": checks, "effect": effect,
            "option": option, "planner": planner, "status": record.status.value, "seconds": round(seconds, 1),
            "summary": record.summary[:600], "tool_calls": sum(1 for e in events if e.kind.value == "TOOL_CALL"),
            "errors": [e.title for e in events if e.kind.value == "ERROR"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", help="a single scenario id, e.g. SC-01")
    ap.add_argument("--out", type=Path, help="write results as JSON")
    args = ap.parse_args()
    load_env()
    settings, policy = Settings(), PolicyEngine()
    ids = [args.only] if args.only else [*sorted(EXPECTED_OPTION), *EXTRA]
    results = []
    for sid in ids:
        for n in range(1, args.runs + 1):
            r = run_once(sid, settings, policy)
            results.append(r)
            mark = "PASS" if r["passed"] else "FAIL"
            failed = [k for k, ok in r["checks"].items() if not ok]
            print(f"{mark} {sid} run {n}: {r['status']} {r['effect']} {r['option']} planner={r['planner']} "
                  f"{r['seconds']}s tools={r['tool_calls']}" + (f"  failed={failed} errors={r['errors']}" if failed else ""),
                  flush=True)
    print("\nscenario  pass  median_s  max_s")
    for sid in ids:
        rs = [r for r in results if r["scenario"] == sid]
        secs = [r["seconds"] for r in rs]
        print(f"{sid:<8}  {sum(r['passed'] for r in rs)}/{len(rs)}  {statistics.median(secs):>8.1f}  {max(secs):>5.1f}")
    if args.out:
        args.out.write_text(json.dumps({"at": datetime.now(UTC).isoformat(), "providers": settings.model_providers,
                                        "results": results}, indent=1))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
