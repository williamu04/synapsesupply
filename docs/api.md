# SynapseSupply API

The integration point for the Joule A2A bridge (M2) and the console UI (M3). Run it with:

```bash
uv run uvicorn synapse.api.main:app --port 8080                     # in-process mock S/4, demo mode on
SYNAPSE_ERP_URL=http://localhost:8000 SYNAPSE_DEMO=1 uv run uvicorn synapse.api.main:app --port 8080
```

All environment variables are documented in `src/synapse/api/main.py`. If `SYNAPSE_API_KEY` is set,
send it as `x-api-key` on every route except `/health`. Browsers can't add headers to an SSE
connection, so `?api_key=` is accepted too. For a UI on another origin (Amplify), list that origin
in `SYNAPSE_CORS_ORIGINS` and build the UI with `VITE_API_BASE=https://<api-host>`.

If `ui/dist` exists, the built console is served at `/console/`, so the whole demo runs from one URL.

## Routes

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/cases` | `CaseMessage` | `202 {case_id, status: NEW}`; with `?wait=true`, `200` and the `CaseRecord` |
| POST | `/requests` | `{utterance, user?}` | same as above, for a `USER_REQUEST` from Joule |
| GET | `/cases` | | `CaseRecord[]`, oldest first |
| GET | `/cases/{id}` | | `CaseRecord`, or `{case_id, status: NEW}` while queued |
| GET | `/cases/{id}/trace` | | `TraceEvent[]` |
| GET | `/cases/{id}/events` | | SSE stream (see below) |
| POST | `/cases/{id}/approve` | `{approver}` | `CaseRecord` (409 if not awaiting approval) |
| POST | `/cases/{id}/reject` | `{approver, reason}` | `CaseRecord` |
| GET | `/recordings` | | names of recorded runs |
| GET | `/recordings/{name}?speed=1` | | SSE replay of a recording, using its original timing |
| GET | `/demo/scenarios` | | the three demo scenarios (mock only) |
| POST | `/demo/reset` | | resets the mock S/4 and forgets all cases |
| POST | `/demo/scenarios/{id}/run` | | reset, apply the disruption, start the case: `202 {case_id}` |

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
- On reconnect, `EventSource` sends `Last-Event-ID` and the stream resumes after that `seq`.
- A `: keep-alive` comment is sent every 15 s.

## Useful views for the UI

Each event kind renders as:

| Kind | Render as |
|---|---|
| `PLAN` | Case header: source, SOP, triage result |
| `TOOL_CALL` / `TOOL_RESULT` | Collapsible step. `analyze_stock_position` includes `projection` (chart it against `safety_stock`); `find_sourcing_options` includes `options` (a table with compliance badges) |
| `REASONING` | The model's own words (LLM planner only) |
| `POLICY` | The decision card: effect, `policy_ids`, `reasons`, `confidence`, `financial_impact_usd` |
| `APPROVAL` | Approval requested or given |
| `ACTION` | The S/4 document that was created |
| `ERROR` | A warning banner. Titles starting with `DEGRADED` or `Model unavailable` mean a fallback is active, and the run still completes |
| `DONE` | Final status and summary |

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

Then open `/console/?replay=sc01`, or pick the recording in the sidebar. It's the same SSE format,
so the same renderer works. `recordings/` contains `sc01`, `sc01-approved`, `sc02` and `sc03`.
Re-record them whenever the data or the agent changes.
