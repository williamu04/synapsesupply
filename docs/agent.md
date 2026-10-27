# The agent

## How a case flows

```
CaseMessage ──► CaseService.handle
                 │ PLAN: case received, SOP selected (skill router: process_type → sops/*.md)
                 │ USER_REQUEST only: triage (Claude Sonnet 4.6; rule-based if unreachable)
                 ▼
            Planner ── Claude Sonnet on Bedrock via Strands  (ModelRouter → SAP AI Core fallback)
                 │     └─ if the model is unreachable or ends without a decision → autopilot
                 ▼
            CaseToolkit (traced tools, ERP via OData)
              get_case_details → analyze_stock_position → find_sourcing_options
              → [check_supplier_compliance] → submit_action | close_without_action
                 ▼
            submit_action: proposal → Cedar (PolicyEngine)
              ALLOW    → write in S/4 now                      → EXECUTED
              ESCALATE → approval card (Joule / console)       → AWAITING_APPROVAL
              DENY     → nothing written                       → BLOCKED
                 ▼
            CaseService.approve(case, planner) → Cedar as the approver → write → EXECUTED
            CaseService.reject(case, planner, reason)                           → REJECTED
```

## Who decides what

| Decision | Made by | Why |
|---|---|---|
| Stock projection, safety stock, shortfall | Code (`domain/`) | Reproducible numbers, unit-tested |
| What the options are, with arrival, cost and compliance | Code (`domain/options.py`) | The model can't invent an option or a price |
| How likely each supplier is to deliver on time | **SAP RPT-1** (`sap/rpt.py`), predicting in-context from S/4 delivery history; empirical per-supplier rate if AI Core is unreachable, labelled as such | Learned from the ERP's own record |
| Which option, and why; the summary for the planner | The model, following the SOP | Judgement and explanation, which is the agentic part |
| Confidence | Code (`plan_confidence`) | Evidence quality, not the model's self-assessment |
| Whether it may run | Cedar | Deterministic guardrail the model cannot override |

`submit_action` takes only an `option_id`. It recomputes quantity limits, cost and confidence
itself, so a model mistake can at worst choose a different *valid* option. If the model chooses a
BLOCKed supplier, Cedar denies it (`tests/test_agent_llm.py`).

## Confidence (what "≥ 0.90" means)

The score starts at 0.97 and drops for each weakness:

| Weakness | Deduction |
|---|---|
| Quantity doesn't cover the shortfall | −0.15 |
| Arrives after the breach day | −0.20 |
| Fewer than 30 days of demand history | −0.05 |
| Fewer than 10 lead-time samples | −0.05 |
| Running on the fallback (mock) ERP | −0.10 |
| Chosen supplier predicted more likely late than on time (RPT-1 late probability ≥ 0.5) | −0.10 |

Any single weakness drops the score below 0.90, so a human decides.

## Running it

```bash
uv run python -m synapse.agent.cli all                          # LLM if reachable, else autopilot
uv run python -m synapse.agent.cli SC-01 --approve "Planner Dewi"
uv run python -m synapse.agent.cli SC-02 --erp-url http://127.0.0.1:9 --fallback-mock   # failover drill
uv run python -m synapse.agent.cli all --planner autopilot --record demo.jsonl          # replay recording
```

### Using the real models

- **Bedrock:** run `aws login`. Default model `global.anthropic.claude-sonnet-4-6` for planning and
  triage, in `ap-southeast-2` (the account's region). Override with `SYNAPSE_REASONING_MODEL_ID`,
  `SYNAPSE_TRIAGE_MODEL_ID` and `AWS_REGION`.
- **Failover is fast and sticky:** no boto3 retries and no throttling backoff while another provider
  exists; a provider that fails is skipped process-wide for 5 minutes (`CooldownStrategy` in
  `models.py`). Before this, a throttled Bedrock made SC-01 take 203 s on AgentCore; now the
  refusal costs about a second (verified 2026-10-22 against the real zero-quota Bedrock).
- **SAP AI Core fallback:** `uv sync --extra aicore`, then set the `AICORE_*` variables (the same
  ones as the Joule A2A sample's `.env`). The router then fails over from Bedrock to
  `sap/anthropic--claude-4.6-sonnet`.

If neither is reachable, the trace shows `Model unavailable — deterministic autopilot takes over`
and the case still completes.

Entry points (CLI, API, Joule agent) read a git-ignored `.env` for local secrets; the platform's
environment wins if both are set.

### Results with a real model (2026-10-21)

Bedrock refused every call (`AccessDeniedException: Your account is currently being verified`).
The router failed over to `anthropic--claude-4.6-sonnet` on SAP AI Core, and SAP RPT-1 ran live.

| Scenario | Claude's decision | Outcome | Time |
|---|---|---|---|
| SC-01 | 920 t transfer from Mill Jambi-2; Siak Agro Wood (BLOCK) and Sumatra Chip Traders (HOLD) rejected | ESCALATE → approved → stock transfer created | 46 s |
| SC-02 | 430 m³ from Jambi Pulpwood Estate (RPT-1: 81% on time) | ALLOW → purchase order created | 38–41 s |
| SC-03 | Submitted the buyer's literal request as SOP-REQ-01 requires, then recommended a compliant alternative | DENY (`Policy-ComplianceBlock`) | 47 s |

Two issues the scripted tests could not catch, both fixed:
- The model wrote "€" for USD amounts. Tool results now carry `currency`, and the prompt says so.
- Summaries came back with markdown headings and rules. The prompt now asks for plain sentences,
  and the service strips headings and rules.
- In a rejection reason, Claude restated a certificate expiry as "20 October 2026"; the gate said
  2026-10-11. Reasons for HOLD and BLOCK options are now built from the compliance gate's findings,
  and the model's wording is used only for non-compliance reasons (timing, cost).

Recordings of these runs (with the model's own reasoning) are `recordings/sc0{1,2,3}-claude.jsonl`.

### Regression eval

`scripts/eval_scenarios.py --runs N` runs each scenario N times against the real model and checks:
the policy effect, the chosen option, and that the model (not the autopilot fallback) planned.
Re-run it after every SOP or prompt change.

| Date | Model | SC-01 | SC-02 | SC-03 | Median / max time (laptop) |
|---|---|---|---|---|---|
| 2026-10-22 | Claude 4.6 Sonnet on SAP AI Core | 3/3 | 3/3 | 3/3 | 25–31 s / 37.5 s |
| 2026-10-22 (after the inventory-position fix; also NOACT 3/3, QUESTION 3/3) | same | 3/3 | 3/3 | 3/3 | 26–34 s / 34 s |

The tool-call count was identical in every run (5 for delays, 6 for the buyer request), so the
planning path is stable, not only the outcome.

"Do nothing" paths, where an unneeded order would be the worst failure, also run each case 3 times
(2026-10-22, same model):

| Case | What it checks | Result |
|---|---|---|
| `NOACT` | SC-01's PO without the delay: the agent must close the case without ordering | 3/3, no ERP write, 13–17 s |
| `QUESTION` | "How much acacia chip stock does Mill Riau-1 have…?": answer from tools, no order | 3/3, no ERP write, 14–19 s |

A spot check of the `QUESTION` answer found every figure correct, but it said to reorder "when
stock falls below the reorder point", although on-hand stock already was below it (open POs cover
the gap). Fixed at the tool: `analyze_stock_position` now returns `open_inbound`,
`inventory_position` and `below_reorder_point`, and SOP-REQ-01 says to compare the reorder point
with the inventory position. In all three re-runs, Claude now reports a 2,600 t on-hand + 9,300 t
inbound = 11,900 t position, above the 4,784 t reorder point.

## Done since

- **AgentCore Runtime deployment.** READY in `ap-southeast-2` (`docs/agentcore.md`).
- **Persistence.** Cases and traces live in DynamoDB, with an S3 audit file per case
  (`docs/pending.md` #4, done 2026-10-22).

## Not done yet

- **AgentCore Gateway + Policy.** The Cedar file is ready, but entity and action names may need
  mapping to what AgentCore generates for the gateway's tools.
- **Bedrock itself.** All real-model runs so far used Claude on SAP AI Core (see below). The
  hackathon AWS account has a zero Bedrock token quota for Claude, and for now there is no Bedrock
  account or quota, so Claude runs on SAP AI Core. ModelRouter still lists Bedrock first;
  moving to Bedrock is a configuration change on an account with quota.

SAP RPT-1 runs live against the team's AI Core: about 3 s per prediction, with the response matching
the SAP Cloud SDK for AI's `RPTResponse` model. The empirical fallback is used only when AI Core is
unreachable.
