# Architecture (as built, 2026-10-22)

Everything below runs today. Items marked *planned* are designed but not deployed (see "Not yet
built" at the end).

## System

![System](img/architecture-system.png)

```mermaid
---
config:
  layout: elk
---
flowchart LR
  USER(["Planner / buyer"])
  subgraph SAP["SAP BTP — hackathon tenant"]
    JOULE["SAP Joule<br/>synapsesupply_assistant (IAS-group gated)<br/>→ BTP destination (Basic auth)"]
    subgraph CF["Cloud Foundry space"]
      A2A["Joule agent · A2A v0.3"]
      API["SynapseSupply API + console<br/>FastAPI · live SSE trace"]
      AGENT["Agent · Strands SDK<br/>SOPs (RFC 2119) · traced tools"]
      CEDAR{{"Cedar policies<br/>ALLOW · ESCALATE · DENY"}}
      S4[("S/4HANA (mock)<br/>OData v2 APIs")]
    end
    subgraph AICORE["SAP AI Core · Generative AI Hub"]
      RPT["SAP RPT-1<br/>delivery-delay prediction"]
      CLAUDE["Claude 4.6 Sonnet<br/>(planning, triage)"]
    end
  end
  BEDROCK["Amazon Bedrock · Claude<br/>(primary; pending account access)"]

  USER -- "chat" --> JOULE --> A2A -- "x-api-key" --> API
  USER -- "browser" --> API
  API --> AGENT
  AGENT -- "every write" --> CEDAR
  AGENT -- "reads; writes only via submit_action" --> S4
  AGENT -- "on-time probability" --> RPT
  AGENT -- "LLM" --> CLAUDE
  AGENT -. "primary model (ModelRouter)" .-> BEDROCK
```

## One case

![One case](img/architecture-case.png)

```mermaid
sequenceDiagram
  autonumber
  participant S4 as S/4 (OData)
  participant AG as Agent (Claude + SOP)
  participant T as Tools (code)
  participant RPT as SAP RPT-1
  participant P as Cedar
  participant J as Joule / console

  S4->>AG: ASN delayed (case 4500000091-10)
  AG->>T: get_case_details, analyze_stock_position
  T->>S4: PO, ASN, stock, 90 days of history
  T-->>AG: safety stock, 7-day projection, shortfall 911 t
  AG->>T: find_sourcing_options(920 t, by 2 Nov)
  T->>RPT: supplier delivery history + candidates
  RPT-->>T: on-time probability per supplier
  T-->>AG: options with EUDR gate (PASS/HOLD/BLOCK), cost, arrival
  AG->>T: submit_action(STO:1200, 920 t, rationale, rejected options)
  T->>P: confidence 0.97, impact $8,280, compliance n/a
  P-->>T: ESCALATE (over $5,000)
  T-->>J: approval request
  J->>P: planner approves (re-checked as approver)
  P-->>J: ALLOW
  J->>S4: stock transfer order created
```

## Who decides what

| Decision | Made by |
|---|---|
| Stock projection, safety stock, shortfall | Code (`domain/inventory.py`, `domain/supply.py`) |
| Which options exist; their arrival, cost, compliance | Code (`domain/options.py`, `domain/compliance.py`) |
| Supplier on-time probability | SAP RPT-1 (empirical fallback, labeled) |
| Which option, and why; the summary | Claude, following the SOP |
| Confidence | Code (evidence quality, not model self-assessment) |
| Whether it may run | Cedar; a human for ESCALATE |

## Not yet built

| Planned | Status |
|---|---|
| Bedrock as the primary model | Code ready (`ModelRouter`); account token quota is 0 (increase requested) |
| AgentCore Gateway with AgentCore Policy | Cedar file ready. (AgentCore **Runtime is deployed** in ap-southeast-2, `docs/agentcore.md`) |
| DynamoDB case store, SQS FIFO ingestion, OData poller | Interfaces ready (`CaseRepository`, `CaseMessage`); allowed in ap-southeast-2, not built; cases are in memory |
| Real S/4HANA | Mock uses real API names and wire format; no S/4 in the tenant |
| Verified approver identity in Joule | Needs XSUAA / principal propagation |
