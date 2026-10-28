# Interface contracts

Frozen on 2026-10-21 so the three workstreams can build in parallel. The source of truth is
`src/synapse/contracts.py` (Pydantic models, with `extra="forbid"`). Any change needs agreement from
all three members, plus an updated test in `tests/test_contracts.py`.

| # | Contract | Producer → consumer | Model |
|---|---|---|---|
| 1 | Case payload | Ingestion (M3) → agent (M1) | `CaseMessage` |
| 2 | MCP tool names | Agent (M1) ↔ SAP integration (M2) | `McpTool` |
| 3 | A2A context | Joule (M2) ↔ agent (M1) | `A2AContext` |
| 4 | Action proposal | Agent → policy layer and UI | `ActionProposal` |
| 5 | Policy request and decision | Agent ↔ Cedar (AgentCore Policy) | `PolicyRequest`, `PolicyDecision` |
| 6 | Case record | Agent and ingestion → DynamoDB → UI | `CaseRecord` |
| 7 | Trace event (SSE) | Agent → UI (live and replay) | `TraceEvent` |

## 1. Case payload

- `case_id` = `{document_number}-{item_id}`, matching `^[A-Z0-9]{4,20}-[0-9]{1,6}$`. For an ASN delay,
  the document is the **purchase order** that the ASN references. `make_case_id()` normalises item
  numbers (`00010` becomes `10`), but the poller Lambda builds the id itself as `f"{po}-{po_item}"`
  without normalising; it works today because the mock seed uses item `10`. Buyer requests get
  `REQ<yymmddHHMMSS + 1/100 ms>-1` (`new_request_case_id()`).
- `process_type`: `ASN_DELAY`, `STOCK_BELOW_SAFETY`, `SUPPLIER_COMPLIANCE_ALERT`, `USER_REQUEST`.
  `payload_source`: `ODATA_POLLER`, `CARRIER_WEBHOOK`, `JOULE_A2A`, `MANUAL`.
- In SQS FIFO, `MessageGroupId = case_id` (cases are processed in order per PO item) and
  `MessageDeduplicationId = case_id:<new delivery date>` (the poller; the `CaseMessage` docstring
  still says `case_id + timestamp`).
- `timestamp` must be timezone-aware (UTC by convention; any offset passes the validator).
- `raw_payload` is a small dict built by the producer, not the source record unchanged:

  | Source | Keys |
  |---|---|
  | Poller Lambda | `delivery_document`, `supplier`, `plant`, `material`, `planned_date`, `new_date`, `delay_days` |
  | Demo scenario | `scenario_id`, `title`, `plant`, `material`, `carrier_notice`, `utterance` (those that are set) |
  | Buyer request | `utterance`, `requested_by` |

  The service adds `triage` for requests and reads `plant`, `material`, `utterance` and `carrier_notice`.

## 2. MCP tools

`sap_mcp:find_sap_services`, `sap_mcp:get_metadata`, `sap_mcp:read_entity`, `sap_mcp:create_entity`,
`sap_mcp:update_entity`. There is no delete tool. Deletion is forbidden by Cedar (`Policy-ForbidDelete`),
and the ERP refuses it as well.

## 3. A2A context

`A2AContext` (`session_id`, `user_utterance`, `context_payload`) is defined but not used. The Joule A2A
server reads the user's words from the message's **text** part (`context.get_user_input()`): plain
text, a JSON string literal, or `{"user_request": …}` (`joule/server.py`).
**The user's JWT travels in the `Authorization` header, never in the message body.** Message bodies get
logged and traced. The token's signature is not verified; it is only used as the approver label.
This changes the original plan, which put `jwt_token` in the body.

## 4. Action proposal

- `financial_impact_usd` is the **incremental cost** compared with the original plan, not the gross order
  value. For a new PO it is `(new price − price on the delayed PO) × qty`, with the per-unit difference
  floored at 0; for a buyer request there is no delayed PO, so the baseline is the cheapest compliant
  (PASS) info-record price. For a stock transfer it is `freight per unit × qty`.
- `action_type`: `RESCHEDULE_PO_LINE`, `CREATE_PURCHASE_ORDER`, `CREATE_STOCK_TRANSFER`, `NOTIFY_ONLY`.
- Validators: `quantity > 0`, `financial_impact_usd ≥ 0`, `0 ≤ confidence ≤ 1`.
  `CREATE_PURCHASE_ORDER` requires `supplier` and the `compliance_outcome` from the gate
  (`domain/compliance.py`); `CREATE_STOCK_TRANSFER` requires a `supplying_plant` different from
  `plant`; `RESCHEDULE_PO_LINE` requires `reference_document`.
- `option_id` links the proposal to the computed sourcing option (`PO:<supplier>` or `STO:<plant>`).
- `alternatives` lists what the agent rejected and why. The UI shows this list, and it is what makes
  the agent's reasoning visible to judges.

## 5. Policy

| Effect | Meaning | Example |
|---|---|---|
| `ALLOW` | Execute autonomously | confidence ≥ 0.90, impact ≤ $5,000, gate PASS or not applicable (stock transfer); HOLD always escalates |
| `ESCALATE` | Needs a human to approve, via a Joule card or the UI | transfer with $8.2k of freight |
| `DENY` | No approval path | delete, or any supplier the gate BLOCKs |

Policies: `Policy-ReadPermit`, `Policy-WriteGating`, `Policy-HumanApproval` (an approver may execute
an escalated write; listed in every ESCALATE decision), `Policy-ForbidDelete`, `Policy-ComplianceBlock`.
Actions are namespaced: `sap:read`, `sap:reschedule_po_line`, `sap:create_purchase_order`,
`sap:create_stock_transfer`, `sap:delete`.

## 6. Case record

Status flow: `NEW → ANALYZING →` one of `EXECUTED`, `AWAITING_APPROVAL`, `BLOCKED`,
`NO_ACTION_NEEDED` (stock stays above safety stock) or `FAILED`.
`AWAITING_APPROVAL` then becomes `EXECUTED`, `REJECTED`, `BLOCKED` (Cedar refused the approver), or
`FAILED` (the S/4 write failed after approval).

## 7. Trace event

One SSE `data:` frame per event. `seq` is per case and strictly increasing. Replay mode re-emits
recorded events in file order (recordings are written in `seq` order; `load_recording` does not
sort), with the original gaps between `ts` values divided by `speed` and capped at 3 s each.

## Mock S/4 (system of record for the demo)

The mock uses real S/4HANA Cloud API names. Tool code should go through the mock, so it later works
against a real system without changes:

| Service | Entity sets |
|---|---|
| `API_PURCHASEORDER_PROCESS_SRV` | `A_PurchaseOrder`, `A_PurchaseOrderItem`, `A_PurchaseOrderScheduleLine` |
| `API_MATERIAL_STOCK_SRV` | `A_MatlStkInAcctMod` |
| `API_INBOUND_DELIVERY_SRV;v=0002` | `A_InbDeliveryHeader`, `A_InbDeliveryItem` |
| `API_MATERIAL_DOCUMENT_SRV` | `A_MaterialDocumentItem` (261 = consumption, 101 = goods receipt) |
| `API_INFORECORD_PROCESS_SRV` | `A_PurchasingInfoRecord` (simplified) |
| `ZSCM_SYNAPSE_SRV` (custom) | `SupplierCompliance`, `TransportLane` |

The wire format matches S/4: dates are `/Date(ms)/`, decimals are strings, and writes need a CSRF
token fetched with `x-csrf-token: Fetch`. To detect ASN changes, poll:
`A_InbDeliveryHeader?$filter=LastChangeDate ge datetime'<last poll>'`.
