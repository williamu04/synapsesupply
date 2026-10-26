# SynapseSupply

A compliance-aware agent that handles logistics exceptions and rebalances stock for pulp and paper
mills. Built for the AWS-SAP AI Agentic Hackathon 2026 (Intelligent Supply Chain track), with Demo Day
on 2026-10-31.

When a wood-fiber delivery slips, the agent works through these steps:

1. **Plan:** pull the POs, stock, ASNs and consumption history.
2. **Reason:** compute safety stock, EOQ and a 7-day stock projection.
3. **Compare options:** another supplier, or a stock transfer between mills.
4. **Check compliance:** run each option through an EUDR / certification gate. The agent does not
   source from a supplier with a deforestation alert, however cheap.
5. **Act or escalate:** Cedar policies execute small, high-confidence fixes autonomously. Anything over
   $5k goes to an approval card in SAP Joule.

![Architecture](docs/img/architecture-system.png)

**Docs:** `docs/pending.md` (everything still open, with next steps) · `docs/links.md` (every link used, and what for) · `docs/architecture.md` (as built, and what isn't) · `docs/demo.md` (Demo Day runbook) ·
`docs/operations.md` (run, deploy, configure, secrets, troubleshooting) · `docs/agent.md` (agent internals, evals) ·
`docs/api.md` · `docs/joule.md` · `docs/agentcore.md` · `docs/contracts.md`.

## Status

| Part | Owner | State |
|---|---|---|
| Contracts (`src/synapse/contracts.py`, `docs/contracts.md`) | all | done, frozen |
| Domain math, sourcing options, compliance gate (`src/synapse/domain/`) | M1 | done, tested |
| Synthetic dataset and scenarios (`src/synapse/data/`) | M3 | done, tested |
| Mock S/4 OData server (`src/synapse/mock_s4/`) and ERP client with failover (`erp.py`) | M2 | done, tested |
| Cedar policies + engine (`src/synapse/policy/`) | M1 | done, tested locally (cedarpy) |
| Agent: Strands tools, SOPs, model routing, triage, autopilot fail-safe, case service, CLI (`src/synapse/agent/`, `docs/agent.md`) | M1 | done; all 3 scenarios correct with real Claude 4.6 Sonnet on SAP AI Core (Bedrock pending AWS account verification) |
| HTTP API: cases, approvals, SSE live trace, recordings replay, demo control (`src/synapse/api/`, `docs/api.md`) | M2/M3 consume | done, tested |
| Console UI: live trace, stock projection chart, options + compliance, decision card with approve/reject, demo buttons, replay (`ui/`) | M3 | done, unit-tested, screenshot-checked light/dark/phone |
| AgentCore Runtime packaging: entry point + ARM64 image (`src/synapse/agentcore.py`, `Dockerfile`, `docs/agentcore.md`) | M1 | **deployed** to AgentCore Runtime in ap-southeast-2; SC-01 verified |
| DynamoDB cases + trace, S3 audit archive (`src/synapse/aws_store.py`) | M1 | **running**; AgentCore Gateway + Policy dropped for Demo Day |
| Joule: A2A agent + capability YAML (request, pending approvals, approve/reject in chat, rich cards: decision, options table, stock projection) (`src/synapse/joule/`, `joule/`, `docs/joule.md`) | M2 | **live**: assistant `synapsesupply_assistant` + destination `SYNAPSE_AGENT_YPDD`; approve-in-Joule tested end to end; rich replies prepared (`GET /cases/{id}/view`) |
| Cloud Foundry deployment of API + console + Joule agent (`manifest.yml`, `scripts/cf_prepare.sh`) | M2/M3 | **deployed** to the team space; both apps protected by keys; SC-02 runs live in 18 s (URLs in `docs/joule.md`) |
| SAP RPT-1 delivery-risk prediction per supplier option (`sap/rpt.py`, `domain/delays.py`), shown in console and used in confidence | M2 | done, verified live against the team's AI Core |
| ERP poller Lambda → SQS FIFO → dispatcher Lambda → AgentCore (`lambdas/`, `infra/`) | M3 | **running**: ERP change to escalated case in 84 s |

## Quick start

```bash
uv sync
uv run pytest                                            # 255 tests
uv run uvicorn synapse.mock_s4.app:app --port 8000       # mock S/4 on localhost:8000
uv run python -m synapse.agent.cli all                   # run all demo scenarios end to end
uv run uvicorn synapse.api.main:app --port 8080          # API for Joule + UI (docs/api.md)
uv run python scripts/eval_scenarios.py --runs 3         # regression eval against the real model
(cd ui && npm install && npm test && npm run build)      # console; then open http://localhost:8080/console/
```

For UI development, run `npm run dev` in `ui/`, which proxies API calls to :8080. Deep links:
`/console/?case=<case_id>` opens a case (link to it from the Joule card), and `/console/?replay=sc01`
replays a recording from `recordings/`.

The agent uses Claude on Bedrock when credentials are available and otherwise falls back to the
deterministic autopilot. See `docs/agent.md` for model setup, the decision split and the failover drill.

Try it:

```bash
curl -s "localhost:8000/sap/opu/odata/sap/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod?\$filter=Plant%20eq%20'1100'"
curl -s -X POST localhost:8000/admin/scenarios/SC-01/apply   # trigger the disruption live
curl -s -X POST localhost:8000/admin/reset                   # back to baseline
curl -s -X POST localhost:8000/admin/faults -H 'content-type: application/json' \
     -d '{"error_rate":0.3,"latency_ms":800}'                 # rehearse failure handling
```

## Demo scenarios

The synthetic data is fictional (companies, mills, suppliers). It is generated deterministically
relative to Demo Day: `uv run python -m synapse.data.generate`. The tests in
`tests/test_seed_story.py` fail if an edit to the data breaks a scenario's point.

| ID | Trigger | What happens | Expected |
|---|---|---|---|
| SC-01 | Chip ASN from Riau Fibre slips 3 days (flooded road) | Mill Riau-1 projected at 285 t on day 2 (safety stock ≈1,196 t). Cheapest fast supplier is BLOCKed (deforestation alert), the next is on HOLD (expired certificate). The only compliant option in time is a transfer from Mill Jambi-2, moving 920 t with $8,280 of freight | **ESCALATE** → Joule approval |
| SC-02 | Log ASN slips 1 day | 98 m³ on day 1 (safety stock ≈527). Compliant top-up of 430 m³ from Jambi Pulpwood, premium $2,150 | **ALLOW** → autonomous PO |
| SC-03 | Buyer asks Joule to order from Siak Agro Wood ("cheapest") | Gate BLOCK | **DENY**, with an explanation |

## Repo layout

```
src/synapse/contracts.py     interface contracts (see docs/contracts.md)
src/synapse/domain/          inventory math, sourcing options, confidence, compliance gate (pure, no I/O)
src/synapse/data/            dataset generator + committed seed.json
src/synapse/sap/             S/4 OData v2 entity schema and wire format (shared)
src/synapse/erp.py           OData client: typed rows, CSRF, failover to the mock
src/synapse/mock_s4/         OData v2 mock: store and FastAPI app
src/synapse/policy/          Cedar policies, schema and the ALLOW/ESCALATE/DENY engine
src/synapse/agent/           toolkit, SOPs, prompts, model routing, triage, autopilot, service, CLI
src/synapse/api/             HTTP API: cases, approvals, SSE trace, replay, demo control, serves ui/dist
src/synapse/joule/           A2A agent for SAP Joule (chat -> API), deployable to Cloud Foundry
src/synapse/agentcore.py     Amazon Bedrock AgentCore Runtime entry point (Dockerfile builds the ARM64 image)
src/synapse/env.py           loads the git-ignored .env for local secrets
joule/                       Joule capability (da.sapdas.yaml, scenarios, function)
ui/                          React + TypeScript console (Vite), no UI library; chart is hand-built SVG
recordings/                  recorded demo runs (JSONL) for the replay fallback
scripts/                     cf_prepare.sh (Cloud Foundry build), eval_scenarios.py (regression eval)
manifest.yml, runtime.txt    Cloud Foundry apps (API + console, Joule agent); Python 3.13 pin
tests/                       unit, HTTP and "the data tells the story" tests
```

Reference material from the event (guides, the `files/` sample platform, the Joule A2A sample) lives
in the parent workspace folder. It is not part of this repo.

## Credentials

Never commit AI Core or Joule service keys, client secrets or tokens. `.gitignore` covers `.env*` and
`*-key.json`. Keep keybroker output in `.env` locally.
