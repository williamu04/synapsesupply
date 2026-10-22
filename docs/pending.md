# Pending work (as of 2026-10-22)

Everything not done yet, who it waits on, and the exact steps once it's unblocked. Demo Day is
2026-10-31. Update this file when an item moves.

| # | Item | Waits on | Status |
|---|---|---|---|
| 1 | Bedrock as the primary model | AWS: quota increase for Claude Sonnet 4.6 (zero in every region) | case opened (us-west-2); file it for ap-southeast-2 too |
| 2 | AWS services (AgentCore, ECR, S3, Lambda, DynamoDB) | — | **solved:** allowed in `ap-southeast-2`, denied only in `us-west-2` |
| 3 | Deploy to AgentCore Runtime (Sydney) | — | **done:** runtime `synapsesupply-vFgJ0n85b6` READY, SC-01 verified |
| 4 | Durable case history (DynamoDB) | nothing (Sydney allows DynamoDB) | designed, interface ready |
| 5 | Automatic ERP polling (poller → SQS FIFO → agent) | a real S/4 to poll | not built |
| 6 | Push the repo to GitHub | team: create the remote | 5 local commits on `main` |
| 7 | Team rehearsal | team | open |
| 8 | Start the demo from Joule (hidden "simulate SC-01" command) | team decision | proposed, about 1 hour |
| 9 | Rotate all secrets | after Demo Day | open |
| 10 | Verified approver identity in Joule | SAP principal propagation setup | future work |
| 11 | Joule notifications (push escalations to the planner) | SAP notification/task service | future work |
| 12 | Real S/4HANA instead of the mock | an S/4 system | future work |

## 1. Bedrock as the primary model

**Now:** the account has the Anthropic use-case form approved, but every model's tokens-per-minute
quota is 0 (`ThrottlingException`) in both `us-west-2` and `ap-southeast-2`, including Amazon Nova, so
it is account-wide, not regional. A Service Quotas increase for "Global cross-region model
inference tokens per minute for Anthropic Claude Sonnet 4.6" is open. Claude 5.x is not offered to
this account ("contact AWS Sales"), so the plan uses Sonnet 4.6 for both planning and triage. A
separate Haiku quota is not needed.

**When the quota is approved:**

1. Check that the model answers (from the laptop, after `aws login`):
   ```bash
   uv run python -c 'import boto3; print(boto3.client("bedrock-runtime", region_name="ap-southeast-2").converse(modelId="global.anthropic.claude-sonnet-4-6", messages=[{"role":"user","content":[{"text":"Reply OK"}]}], inferenceConfig={"maxTokens":8})["output"])'
   ```
2. Set the model IDs locally (`.env`):
   ```
   SYNAPSE_REASONING_MODEL_ID=global.anthropic.claude-sonnet-4-6
   SYNAPSE_TRIAGE_MODEL_ID=global.anthropic.claude-sonnet-4-6
   ```
3. Run the regression eval on Bedrock only, and compare with the AI Core results in `agent.md`:
   ```bash
   SYNAPSE_MODEL_PROVIDERS=bedrock uv run python scripts/eval_scenarios.py --runs 3
   ```
4. **Give the Cloud Foundry app AWS credentials.** It has none: `aws login` credentials live only on
   the laptop and expire. Options, best first:
   - a **Bedrock API key** for the account, set as `AWS_BEARER_TOKEN_BEDROCK` on the API app
     (needs a check that the Strands `BedrockModel` / boto3 version picks it up);
   - an IAM user with only `bedrock:InvokeModel*`, with its access key set as `AWS_ACCESS_KEY_ID` /
     `AWS_SECRET_ACCESS_KEY` (IAM itself works: the AgentCore role was created on 2026-10-22).

   Set either with `cf set-env synapsesupply-api-yang-penting-daftar-dulu …`, never in the manifest.
5. Switch the deployed system to Bedrock first, AI Core as fallback. In `manifest.yml` (API app):
   ```yaml
   SYNAPSE_MODEL_PROVIDERS: bedrock,aicore
   SYNAPSE_REASONING_MODEL_ID: global.anthropic.claude-sonnet-4-6
   SYNAPSE_TRIAGE_MODEL_ID: global.anthropic.claude-sonnet-4-6
   AWS_REGION: ap-southeast-2
   ```
   Then `cf stop` + `cf push` the API app (`operations.md`).
6. Re-time SC-01 on BTP. If it gets close to Joule's 60-second limit, keep `aicore` first instead.
7. Update: deck slide 10 ("Amazon Bedrock as primary model": Running), `architecture.md` (Bedrock
   edge no longer "pending"), the eval table in `agent.md`, `demo.md`'s "Where is AWS?" answer, and
   re-record `recordings/sc0{1,2,3}-claude.jsonl`.

## 2. AWS services blocked by the organization: solved by region

`AccountFullAccessRole` has `AdministratorAccess`, but the organization (`o-aoyve0xnw6`) denies
AgentCore, ECR, S3, Lambda and DynamoDB **in `us-west-2` only**. In `ap-southeast-2` all of them work
(probed 2026-10-22). So all AWS resources go to Sydney, next to SAP AI Core (ap10). The drafted email
to the organizers is no longer needed for access; it can still ask about the zero Bedrock quota.

```bash
for c in "bedrock-agentcore-control list-agent-runtimes" "ecr describe-repositories" "dynamodb list-tables"; do aws $c --region ap-southeast-2 --max-items 1 > /dev/null && echo "OK $c" || echo "DENIED $c"; done
```

## 3. Deploy to AgentCore Runtime

Done in `ap-southeast-2` (`agentcore.md`): SC-01 invoked 2026-10-22: AWAITING_APPROVAL in 25 s, Claude via AI Core, RPT-1 live, Cedar ESCALATE. Still open: the console and Joule talk to the
Cloud Foundry API, not to this runtime (each has its own in-memory cases); wiring them to AgentCore
needs DynamoDB (#4) so both share one case store.
After deploying, update deck slide 10 and `architecture.md`. AgentCore Gateway + Policy (mapping
`synapse.cedar` to the gateway's tool names) comes after.

## 4. Durable case history (DynamoDB)

Cases and traces live in memory. Restarts re-stage SC-01 automatically, so the demo is not affected.
To build: a `DynamoCaseRepository` implementing `synapse.agent.cases.CaseRepository` (table `Cases`,
partition key `case_id`), plus persisted trace events so the live stream survives restarts.

## 5. Automatic ERP polling

Today a disruption is triggered from the console (demo buttons). Planned: an OData poller reading
`A_InbDeliveryHeader?$filter=LastChangeDate ge …` (`contracts.md`), turning delays into
`CaseMessage`s on an SQS FIFO queue (`MessageGroupId = case_id`), consumed by the agent. On stage,
say: "the ERP raises this automatically; we simulate it here."

## 6. Push the repo to GitHub

```bash
git remote add origin <url> && git push -u origin main
```
`.env` and generated files are ignored. Check `git status` shows nothing unexpected before pushing.

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
