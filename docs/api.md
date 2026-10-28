# SynapseSupply API

The integration point for the Joule A2A bridge (M2) and the console UI (M3). Run it with:

```bash
uv run uvicorn synapse.api.main:app --port 8080                     # in-process mock S/4, demo mode on
SYNAPSE_ERP_URL=http://localhost:8000 SYNAPSE_DEMO=1 uv run uvicorn synapse.api.main:app --port 8080
```

API-level environment variables are documented in `src/synapse/api/main.py` (except
`SYNAPSE_EXPOSE_S4`, read there too). Model, store, secrets and AI Core variables are read in
`agent/config.py`, `aws_store.py`, `env.py` and `sap/rpt.py`; `docs/operations.md` lists them all.

If `SYNAPSE_API_KEY` is set, send it as `x-api-key`, as `?api_key=` (browsers can't add headers to
an SSE connection), or as the HTTP Basic password with any user name. The console relies on Basic:
`/console` answers 401 with `WWW-Authenticate: Basic`, the browser prompts once and then sends it on
every same-origin request, `EventSource` included. `/s4` accepts only `x-api-key` or Basic, not
`?api_key=`. Open without the key: `/health`, and FastAPI's default `/docs`, `/redoc` and
`/openapi.json` (not disabled in `create_api`).

The console is normally served same-origin, so CORS is not needed; to host the SPA separately, list
that origin in `SYNAPSE_CORS_ORIGINS` and build the UI with `VITE_API_BASE=https://<api-host>`. With
a key set, also build with `VITE_API_KEY`, which appends `?api_key=` to every call; it ends up in the
public bundle.

If `ui/dist/index.html` exists (override the directory with `SYNAPSE_UI_DIR`, relative to the working
directory), the built console is served at `/console/`, so the whole demo runs from one URL.

## Routes

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | `{status, demo, queued}`; no API key needed |
| POST | `/cases` | `CaseMessage` | `202 {case_id, status: NEW}`; with `?wait=true`, `200` and the `CaseRecord`; 409 if the case id is already queued or stored |
| POST | `/requests` | `{utterance, user?}` (`utterance` 1–2000 chars) | same as above, for a `USER_REQUEST` from Joule |
| GET | `/cases` | | `CaseRecord[]`, oldest first |
| GET | `/cases/{id}` | | `CaseRecord`, or `{case_id, status: NEW}` while queued |
| GET | `/cases/{id}/trace` | | `TraceEvent[]` |
| GET | `/cases/{id}/view` | | Compact structured view for Joule: case, decision, stock analysis, sourcing options (`docs/joule.md`) |
| GET | `/cases/{id}/events` | | SSE stream (see below) |
| POST | `/cases/{id}/approve` | `{approver}` (1–80 chars) | `CaseRecord`; 404 unknown case, 409 if not awaiting approval. Cedar re-checks the approver: if it refuses, `200` with status `BLOCKED` |
| POST | `/cases/{id}/reject` | `{approver, reason}` (reason 1–500 chars) | `CaseRecord` (`REJECTED`); 404 / 409 as for approve. No Cedar check |
| GET | `/recordings` | | names of recorded runs |
| GET | `/recordings/{name}?speed=1` | | SSE replay of a recording: original gaps divided by `speed` (0.1–50, else 422), each capped at 3 s |
| GET | `/demo/scenarios` | | the three demo scenarios (mock only) |
| POST | `/demo/reset` | | resets the mock S/4 and forgets all cases |
| POST | `/demo/scenarios/{id}/run` | | reset, apply the disruption, start the case: `202 {case_id, status: NEW}`; `?wait=true` as for `/cases`; 404 unknown scenario |
| POST | `/demo/scenarios/{id}/stage` | | reset and change the ERP only: `200 {status: "staged", scenario_id, case_id, note}`. The ERP poller Lambda queues the case within about a minute and AgentCore handles it. Only SC-01 and SC-02 change the ERP; staging SC-03 queues nothing |
| * | `/s4/...` | | the in-process mock S/4 (OData), behind the API key, when `SYNAPSE_EXPOSE_S4=1` and `SYNAPSE_ERP_URL` is unset (otherwise nothing is mounted); AgentCore and the poller use it, so the whole system shares one ERP |

Cases run one at a time, in order, matching the SQS FIFO queue in AWS.

## Live trace (SSE)

```
id: 9
event: POLICY
data: {"case_id":"4500000091-10","seq":9,"ts":"…","kind":"POLICY","title":"Cedar: ESCALATE","detail":{…}}
```

- The stream first replays everything so far, then sends new events as they happen. It closes when
  the case reaches a final status (EXECUTED, REJECTED, BLOCKED, NO_ACTION_NEEDED, FAILED) and the
  last event is `DONE`.
- **A case awaiting approval keeps the stream open**: the approval and the S/4 write arrive on it
  later. Use `?follow=false` to get the replay only.
- Every stream also closes after 30 minutes (`MAX_STREAM_SECONDS`) or when the client disconnects.
- On reconnect, `EventSource` sends `Last-Event-ID` and the stream resumes after that `seq`.
- A `: keep-alive` comment is sent every 15 s.

## Case view (Joule rich replies)

`GET /cases/{id}/view` returns one small JSON object derived from the record and its trace — no extra
storage. The Joule A2A bridge forwards it in the data part of the reply, so the capability can render
a decision `card`, an options `Table` and a projection `Analytical` chart without another round trip:

```json
{"case_id":"…","status":"AWAITING_APPROVAL","process_type":"ASN_DELAY","source":"ODATA_POLLER",
 "summary":"…","approver":null,"sap_document":null,
 "decision":{"effect":"ESCALATE","policy_ids":[…],"reasons":[…],"action_type":"CREATE_STOCK_TRANSFER",
  "option_id":"STO:1200","quantity":920.0,"unit":"TO","delivery_date":"…","confidence":…,
  "financial_impact_display":"$8,280","quantity_display":"920 t",
  "compliance_display":"Not applicable (own plant)",…},
 "analysis":{"safety_stock":1196.0,"first_breach_day":"…","projection":[…],…},
 "options":[{"source_name":"…","compliance":"BLOCK","compliance_state":"Error","chosen":false,…}]}
```

`compliance_state` (`Success|Warning|Error|Information`) and `outcome` (`Chosen|Rejected|Considered`)
are precomputed so the function YAML needs no equality helpers. For the same reason the decision
carries display strings next to the raw numbers (which stay unchanged):

| Field | Example | Rule |
|---|---|---|
| `financial_impact_display` | `$8,280` | USD, no decimals, thousands separator |
| `quantity_display` | `920 t`, `430 m³` | no decimals; `TO` → `t`, `M3` → `m³` (as `unitLabel` in `ui/src/format.ts`) |
| `compliance_display` | `PASS`, `HOLD`, `BLOCK` | `Not applicable (own plant)` for a stock transfer; `null` when there is no proposal or no gate outcome |

All three are `null` when the case has a policy decision but no proposal.

A case still queued returns
`{case_id, status: "NEW", decision: null, analysis: null, options: []}`.

## Useful views for the UI

Each event kind renders as (every event is also a timeline row):

| Kind | Render as |
|---|---|
| `PLAN` | "Case received from …" (`process_type`, `sop`) and, for requests, "Request triaged". The console builds its case header from the `get_case_details` `TOOL_RESULT`, not from PLAN |
| `TOOL_CALL` / `TOOL_RESULT` | Collapsible step. `analyze_stock_position` includes `projection` (chart it against `safety_stock`); `find_sourcing_options` includes `options` (a table with compliance badges) |
| `REASONING` | The model's own words (LLM planner only). May contain `**bold**`: the console renders it with `inlineBold` (`ui/src/inline.tsx`), as it does the case summary; Joule renders the same markdown itself |
| `POLICY` | The decision card: effect, `policy_ids`, `reasons`, `confidence`, `financial_impact_usd` |
| `APPROVAL` | Approval requested, given ("Approval by X: ALLOW"), not permitted by Cedar ("Approval by X: DENY") or rejected ("Rejected by X"); the console tells them apart by title |
| `ACTION` | The S/4 document that was created |
| `ERROR` | Titles starting with `DEGRADED`, `Model unavailable` or `Agent ended without` mean a fallback is active, and the run still completes; the console shows these as header badges. Other errors appear only in the timeline |
| `DONE` | Status and summary at the end of every run, including one that stops at `AWAITING_APPROVAL`, so an approved case has two. Final only if the title is a final status |

## Joule approval card (M2)

When a case reaches `AWAITING_APPROVAL`, `CaseRecord.proposal` and `CaseRecord.policy.reasons` hold
everything the card needs: the action, quantity, source, delivery date, incremental cost and
rejected alternatives. Approve or reject buttons call the two POST routes, with the Joule user as
`approver`. The approver's identity goes through Cedar again (`Policy-HumanApproval`), so even a
human can't approve sourcing from a BLOCKed supplier.

## Replay mode (M3)

Record a rehearsal with:

```bash
uv run python -m synapse.agent.cli SC-01 --record recordings/sc01.jsonl
```

Then open `/console/?replay=sc01`, or pick the recording in the sidebar. The console replays at
`speed=2` (`&speed=` overrides the deep link). It's the same SSE format, so the same renderer works.
A live case opens with `/console/?case=<case_id>`. `recordings/` contains `sc01`, `sc01-approved`, `sc02` and `sc03`
(autopilot), and `sc01-claude`, `sc02-claude` and `sc03-claude` (real Claude runs, the Demo Day
fallback in `docs/demo.md`). Re-record them whenever the data or the agent changes.
