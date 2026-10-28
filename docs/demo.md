# Demo Day runbook (15 minutes including Q&A, in English)

Judging weights: Innovation 25% · Working demo 20% · AWS/SAP use 20% · Problem–solution fit 20% ·
Presentation 10% · Q&A 5%. Judges are told to look for: plan, reason, act/tool, review,
orchestration, human in the loop, responsible AI. Every step below shows at least one of these.

## Before going on stage (T−30 min)

| Check | How | Expected |
|---|---|---|
| Apps up | `cf apps` | both `started`, `web:1/1` |
| API key works | open the console URL, log in (any user, `SYNAPSE_CF_API_KEY`) | console loads, "Demo · mock S/4" badge |
| Model reachable | console → **Reset demo** → **SC-02** | EXECUTED in about 20 s, planner "Claude" |
| Joule reachable | web client → "What needs my approval?" | "Nothing is waiting…" |
| Fresh state | console → **Reset demo** | no cases listed |
| Fallback ready | console → Replay → `sc01-claude` | plays to the end |

Keep two browser tabs open: the **console** and the **Joule web client**. Don't press any SC
button between the steps below; each one resets the demo.

URLs (team `yang-penting-daftar-dulu`):
- Console: `https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com/console/`
- Joule: `https://aws-sap-hackathon-si4ykj9d.ap10.sapdas.cloud.sap/webclient/standalone/synapsesupply_assistant`

## The 15 minutes

| Time | What you show | What you say | Criterion |
|---|---|---|---|
| 0:00–1:30 | (slides) problem | A mill stops when chips run out. Each logistics incident takes about 150 min of manual handling (industry estimate), and the cheapest fix is often illegal under EUDR. | Fit |
| 1:30–2:30 | (slide) architecture | S/4 OData → Strands agent with SOPs → computed options → EUDR gate → Cedar → S/4 write or Joule approval. Claude on SAP AI Core, SAP RPT-1, Cloud Foundry, Joule A2A. | AWS/SAP use |
| 2:30–6:00 | Console → **SC-01** | Live trace: the agent reads the delayed ASN, projects stock (chart turns red on Mon 2 Nov), lists options with **SAP RPT-1 on-time probabilities**, rejects Siak Agro Wood (BLOCK: deforestation alert) although it is cheapest and fastest, and proposes a 920 t transfer. Cedar **escalates**: $8,280 is over the $5,000 autonomous limit. | Plan, reason, tool, review, responsible AI |
| 6:00–8:00 | Joule → "What needs my approval?" → click **Approve** (or type "approve 4500000091-10") | The planner approves inside SAP Joule. Cedar re-checks the approver, and the S/4 stock transfer is created. Switch to the console: the trace shows APPROVAL → ACTION live. | Human in the loop, orchestration |
| 8:00–9:30 | Joule → "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood" | A buyer insists on the cheapest supplier. The agent submits it as asked, and Cedar **denies** it. No human can override a BLOCK, and the agent points to the compliant alternative. | Responsible AI |
| 9:30–10:30 | (slide) impact | Time to decision measured at 18 s vs ~150 min manual (industry estimate); every action is policy-checked and traced. | Fit |
| 10:30–15:00 | Q&A | see below | Q&A |

If time is short, drop SC-03. If there's spare time, run **SC-02** (autonomous execution) before
SC-01 to show the contrast: a small, safe fix runs alone, a large one goes to a human.

## Fallbacks

| Problem on stage | Do this |
|---|---|
| Model slow or erroring | The case still completes on the deterministic autopilot (a "Model unavailable" banner appears). Say that this is the designed fail-safe. |
| Network or app down | Console → Replay → `sc01-claude`, `sc03-claude` (recorded real Claude runs) |
| Joule doesn't answer | Approve in the console instead (same API, same Cedar check) |
| Wrong case state | Console → **Reset demo** → run the scenario again |

## Likely questions, with answers grounded in what we measured

- **"Is it reliable or did you get lucky?"** Our regression eval (`scripts/eval_scenarios.py`) ran each
  of the 3 scenarios three times against Claude: 9/9 runs reached the expected decision and option
  (plus the two do-nothing cases, 6/6), with an identical tool-call count each time.
- **"How do you prevent hallucinated actions?"** The model can only pick an `option_id` that code
  computed. Cost and confidence are recomputed by the tool from that option, and Cedar decides
  whether it runs. The quantity is the model's: the tool only checks that it is positive and, for a
  transfer, within what the plant can spare (`docs/agent.md`). In a live run Claude restated a certificate date wrongly; compliance reasons now
  come from the gate, not the model (`docs/agent.md`).
- **"What is the 0.97 confidence?"** Evidence quality, not model self-assessment: 0.97 minus fixed
  deductions (shortfall not covered, late arrival, thin history, fallback ERP, RPT-1 late risk ≥ 50%).
  Any one major weakness (shortfall, late arrival, fallback ERP, RPT-1 late risk) drops it below
  0.90; thin demand or lead-time history costs 0.05 each.
- **"Is this real SAP?"** The S/4 system is a mock with real API names and wire format (OData v2,
  CSRF, `/Date()/`). The data is synthetic and fictional. Joule, AI Core, RPT-1 and Cloud Foundry
  are the real hackathon tenant.
- **"Where is AWS?"** The agent is built on the AWS Strands Agents SDK and **runs on Amazon Bedrock
  AgentCore Runtime** (Sydney), with its credentials in AWS Secrets Manager; Cedar is the policy
  language of AgentCore Policy. Say plainly: the hackathon AWS account has a zero Bedrock token
  quota for Claude, and for now there is no Bedrock account or quota, so Claude runs on
  SAP AI Core. ModelRouter still lists Bedrock first; moving to Bedrock is a configuration change on
  an account with quota. The production
  path runs on AWS too: an EventBridge-scheduled **Lambda** polls S/4 every minute, late deliveries
  go to an **SQS FIFO** queue, a second Lambda hands them to AgentCore, and cases and traces live in
  **DynamoDB** (shared with the console and Joule), with an audit file per case in **S3**.
- **Optional live proof of the pipeline (about 90 s):** `curl -X POST -H "x-api-key: …"
  …/demo/scenarios/SC-01/stage` changes only the ERP. Keep talking; within about a minute the case
  appears in the console with source `ODATA_POLLER`, handled by AgentCore. Use it only with time to
  spare: the normal flow (console button) is instant.
- **"Who approved in Joule?"** Shown as `joule:unknown-user`: the destination uses Basic auth to
  protect the agent, and access is limited to the team's IAS group. Verified user identity
  (XSUAA/principal propagation) is future work.
- **"Does it scale?"** Each case is independent and serialized per PO item (FIFO semantics). The
  agent already runs on AgentCore Runtime. Cases and traces live in DynamoDB, shared by the BTP API,
  Joule and AgentCore, with an S3 audit file per case (`docs/pending.md` #4, done 2026-10-22).
