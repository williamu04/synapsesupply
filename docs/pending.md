# Pending work (as of 2026-10-27)

Everything not done yet, who it waits on, and the exact steps once it's unblocked. Demo Day is
2026-10-31. Update this file when an item moves.

| # | Item | Waits on | Status |
|---|---|---|---|
| 1 | Bedrock as the primary model | an AWS account with Bedrock quota for Claude | not before Demo Day: the hackathon account's quota is zero and for now there is no Bedrock account or quota; Claude runs on SAP AI Core |
| 2 | AWS services (AgentCore, ECR, S3, Lambda, DynamoDB) | — | **solved:** allowed in `ap-southeast-2`, denied only in `us-west-2` |
| 3 | Deploy to AgentCore Runtime (Sydney) | — | **done:** runtime `synapsesupply-vFgJ0n85b6` READY, SC-01 verified |
| 4 | Shared case history (DynamoDB) + audit archive (S3) | — | **done** 2026-10-22: BTP app and AgentCore share cases and traces |
| 5 | Automatic ERP polling (poller → SQS FIFO → agent) | — | **done** 2026-10-22: ERP change to escalated case in 84 s, live |
| 5b | AgentCore Gateway + Policy (Cedar enforced outside the agent) | — | **dropped** for Demo Day (risk); presented as next step |
| 6 | Push the repo to GitHub | — | **done**: `https://github.com/williamu04/synapsesupply` (first commit 2026-10-22) |
| 7 | Team rehearsal | team | open |
| 8 | Start the demo from Joule (hidden "simulate SC-01" command) | team decision | proposed, about 1 hour |
| 9 | Rotate all secrets | after Demo Day | open |
| 10 | Verified approver identity in Joule | SAP principal propagation setup | future work |
| 11 | Joule notifications (push escalations to the planner) | SAP notification/task service | future work |
| 12 | Real S/4HANA instead of the mock | an S/4 system | future work |
| 13 | Rich Joule replies (decision card, options table, projection chart) | — | **done** 2026-10-23: `GET /cases/{id}/view` + capability. Analytical chart verified in the tenant 2026-10-27 after adding `feeds` (without them UI5 throws and the card stays on "please wait") |
| 14 | AWS Amplify hosting of the React SPA | — | **dropped**: the console is served same-origin by the API at `/console/`; Joule is the decision surface. No Amplify resources |

## 1. Bedrock as the primary model

The hackathon AWS account has a zero Bedrock token quota for Claude, and for now there is no
Bedrock account or quota, so Claude runs on SAP AI Core. ModelRouter still lists Bedrock
first; moving to Bedrock is a configuration change on an account with quota. No approval is expected
before Demo Day.

Every deployment is set to `bedrock,aicore` in `ap-southeast-2` with Claude Sonnet 4.6 as the default
model. While Bedrock refuses, the router skips it for 5 minutes after each refusal and Claude on SAP
AI Core answers.

| Where | State | Left for the team |
|---|---|---|
| Cloud Foundry API (live demo) | deployed with the new router; AWS key set (`scripts/cf_bedrock_credentials.sh`, run 2026-10-22), Bedrock now answers `ThrottlingException` (quota only) | none |
| AgentCore runtime | version 3, READY, new image (`scripts/agentcore_update.sh`, run 2026-10-22) | none |
| Laptop | defaults need no `.env` change | none |

**On an account with quota:** nothing else to configure. Within 5 minutes the logs stop showing
`model provider bedrock failed`. Then: run the regression eval (`uv run python scripts/eval_scenarios.py
--runs 3`), re-time SC-01, update deck slide 10 ("Amazon Bedrock as primary model": Running),
`architecture.md`, the eval table in `agent.md`, `demo.md`'s "Where is AWS?" answer, and re-record
`recordings/sc0{1,2,3}-claude.jsonl`.

## 2. AWS services blocked by the organization: solved by region

`AccountFullAccessRole` has `AdministratorAccess`, but the organization (`o-aoyve0xnw6`) denies
AgentCore, ECR, S3, Lambda and DynamoDB **in `us-west-2` only**. In `ap-southeast-2` all of them work
(probed 2026-10-22). So all AWS resources go to Sydney, next to SAP AI Core (ap10). The drafted email
to the organizers is no longer needed for access.

```bash
for c in "bedrock-agentcore-control list-agent-runtimes" "ecr describe-repositories" "dynamodb list-tables"; do aws $c --region ap-southeast-2 --max-items 1 > /dev/null && echo "OK $c" || echo "DENIED $c"; done
```

## 3. Deploy to AgentCore Runtime

Done in `ap-southeast-2` (`agentcore.md`): SC-01 invoked 2026-10-22: AWAITING_APPROVAL in 25 s, Claude via AI Core, RPT-1 live, Cedar ESCALATE. The console and Joule talk to the
Cloud Foundry API, which shares one DynamoDB case store with this runtime (#4).
AgentCore Gateway + Policy (mapping `synapse.cedar` to the gateway's tool names) comes after.

## 4–5. AWS pipeline: done

Stack `synapsesupply` (`infra/synapsesupply.yaml`, deployed with `scripts/aws_deploy.sh`):

- **DynamoDB** `SynapseSupplyCases` and `SynapseSupplyTrace`: the BTP app and the AgentCore runtime
  share cases and traces (memory fallback if DynamoDB is unreachable).
- **S3** `synapsesupply-audit-398074591173-ap-southeast-2`: one versioned audit file per case.
- **One S/4:** the BTP app serves its mock S/4 at `/s4` (API key); AgentCore and the poller use it.
- **EventBridge → Lambda `synapsesupply-erp-poller`** (every minute) → **SQS FIFO**
  `synapsesupply-cases.fifo` (+ dead-letter queue) → **Lambda `synapsesupply-case-dispatcher`** →
  **AgentCore Runtime**.

Verified live 2026-10-22: `POST /demo/scenarios/SC-01/stage` changed the ERP only; the poller queued
`4500000091-10` within a minute, AgentCore escalated it in 28 s, and the case appeared in the console
(84 s in total, dead-letter queue empty).

**AgentCore Gateway + Policy was dropped** for Demo Day: Cedar already gates every write inside the
agent, and moving the write tools behind a gateway was the riskiest change this close to the demo.
It is the next step: the policies are already in AgentCore Policy's language (Cedar).

## 6. Push the repo to GitHub: done

Remote `origin` is `https://github.com/williamu04/synapsesupply` (first commit 2026-10-22). `.env` and
generated files are ignored.

## 7. Team rehearsal

Run the 15 minutes in `demo.md` once, timed: console (SC-01 opens by itself) → approve in Joule →
SC-03 in Joule → slides. Before the real demo: **Reset demo**, then wait for SC-01 or click it.

## 8. Start the demo from Joule (decision needed)

Option: a guarded demo-only Joule command ("simulate SC-01") so the story starts and ends in Joule,
with the console as the view inside the agent. Alternative: keep triggering from the console.

## 9. Rotate secrets after Demo Day

All four (AI Core key, Joule key, API key, A2A key): where each lives and how to rotate it is in
`operations.md`.

## 10–12. Future work, presented as such in the deck

- **Verified approver identity:** principal propagation from Joule (XSUAA), replacing
  `joule:unknown-user`.
- **Joule notifications:** push escalations to the planner instead of waiting for "What needs my
  approval?".
- **Real S/4HANA:** point `SYNAPSE_ERP_URL` at it; the OData client and tools stay the same.
