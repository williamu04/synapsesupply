# Known issues (found 2026-10-28)

Problems found in the full docs-vs-code audit before the code freeze. The docs already describe the
current behaviour; nothing here is fixed yet. Fix after Demo Day unless the team decides otherwise.

## Code

| # | Issue | Where | Risk | Suggested fix |
|---|---|---|---|---|
| 1 | **Order quantity is not bounded for purchase orders.** `submit_action` takes the model's `quantity` and only checks that it is positive and, for a stock transfer, not above `max_quantity`. Purchase orders have no limit, and the compliance gate result from `find_sourcing_options` is reused instead of re-run for the submitted quantity. Reproduced on the local mock S/4: a 200,000 t PO (incremental cost $0, PASS) was ALLOWed and executed without approval. | `src/synapse/agent/toolkit.py` (`_submit`), `src/synapse/domain/options.py` | High: an autonomous write far beyond the need | Enforce SOP rule 12 (at most 10% over the shortfall) in `_submit`, and re-run the gate for the submitted quantity |
| 2 | **A demo invoke on AgentCore wipes shared data.** `{"scenario": "SC-01"}` calls `demo.reset()` and `service.clear()`; on the deployed runtime that resets the shared mock S/4 on Cloud Foundry and deletes every case in the shared DynamoDB tables. | `src/synapse/agentcore.py` | Medium: one test invoke clears the console and Joule | Refuse `scenario` payloads unless an explicit flag is set, or drop scenario support from the runtime |
| 3 | **API documentation routes are open.** FastAPI's default `/docs`, `/redoc` and `/openapi.json` respond without the API key. | `src/synapse/api/app.py` (`FastAPI(...)`) | Low: exposes the API surface, no data | `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` when `SYNAPSE_API_KEY` is set |
| 4 | **Console does not reopen a case after Reset demo.** `autoOpened` stays `true` after the first case, so after **Reset demo** the console waits on an empty page until a scenario is clicked. | `ui/src/App.tsx` (`refreshCases`) | Low: presenter must click SC-01 (runbook says so) | Reset `autoOpened.current = false` on Reset demo |
| 5 | **Poller builds case ids without `make_case_id`.** It uses `f"{po}-{po_item}"` with no normalisation; a real S/4 item number such as `00010` would give `…-00010` instead of `…-10`. Works today only because the mock data uses `10`. | `lambdas/poller/handler.py` | Low now, high with a real S/4 | Use `synapse.contracts.make_case_id` |
| 6 | **Stale docstrings.** `agentcore.py` says "persistence (DynamoDB) is planned" (it is wired in); `api/app.py` says queued cases reach `POST /cases` through an "agent-invoker Lambda" (the dispatcher calls AgentCore Runtime directly); `contracts.py` describes `MessageDeduplicationId` as `case_id + timestamp` (it is `case_id:<new delivery date>`). | `src/synapse/agentcore.py:18`, `src/synapse/api/app.py:2-3`, `src/synapse/contracts.py:65` | None (comments only) | Update the docstrings |
| 7 | **`LITELLM_PROVIDER` is unused.** Nothing reads it; LiteLLM takes the provider from the `sap/` prefix of `SYNAPSE_AICORE_MODEL_ID`. | `manifest.yml`, Secrets Manager `synapsesupply/runtime` | None | Remove it from the manifest and the secret |

## Docs

| # | Issue | Suggested fix |
|---|---|---|
| 8 | The new mermaid diagrams in `docs/architecture.md` (AWS path) were not rendered to check the syntax. | Open the file on GitHub and check both diagrams render |
| 9 | `docs/img/architecture-*.png` still show the old diagrams without the AWS path. | Re-export the images from the mermaid sources |
