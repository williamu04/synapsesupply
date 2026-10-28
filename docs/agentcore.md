# Deploying the agent to Amazon Bedrock AgentCore Runtime

**Status (2026-10-22): deployed and running in `ap-southeast-2`.** Runtime `synapsesupply-vFgJ0n85b6`
(status READY). SC-01 invoked end to end: `AWAITING_APPROVAL` in 25 s, Claude via SAP AI Core
reasoning, SAP RPT-1 live (`sap-rpt-1.6`), Cedar ESCALATE ($8,280 > $5,000).
The account's organization policy denies these services in `us-west-2` but **allows them in
`ap-southeast-2` (Sydney)**, so everything runs there. The hackathon AWS account has a zero Bedrock
token quota for Claude, and for now there is no Bedrock account or quota, so Claude runs
on SAP AI Core. ModelRouter still lists Bedrock first; moving to Bedrock is a configuration change on
an account with quota.

Created in `ap-southeast-2` (2026-10-22), besides the runtime:

| Resource | Name |
|---|---|
| ECR repository (scan on push) | `synapsesupply-agent`, tag `latest` (ARM64) |
| IAM execution role | `SynapseSupplyAgentCoreRuntime` (trust: `bedrock-agentcore.amazonaws.com`, this account only) |
| Secrets Manager secret | `synapsesupply/runtime`: JSON with the `AICORE_*` variables, `LITELLM_PROVIDER` (unused), and `SYNAPSE_ERP_USER` / `SYNAPSE_ERP_PASSWORD` for the CF `/s4` (written by `scripts/aws_deploy.sh`) |

The role has two inline policies. `runtime` allows pulling this repository, writing the runtime's
CloudWatch logs, X-Ray/metrics, workload access tokens, reading `synapsesupply/runtime` and invoking
Bedrock models. `synapsesupply-data` (from `infra/synapsesupply.yaml`) allows the `SynapseSupplyCases`
and `SynapseSupplyTrace` DynamoDB tables and `s3:PutObject` on the audit bucket's `cases/*`.

## What exists

| Piece | File | Verified |
|---|---|---|
| Runtime entry point (bedrock-agentcore SDK: `POST /invocations`, `GET /ping`, port 8080) | `src/synapse/agentcore.py` | unit tests (`tests/test_agentcore.py`); real process over HTTP |
| ARM64 container (AgentCore runs linux/arm64) | `Dockerfile`, `.dockerignore` | built with buildx (248 MB), run under emulation: `/ping` Healthy, SC-01 handled, non-root user, no `.env` in the image |
| Same case service as the API | `synapse.api.main.build_service()` | shared wiring |

### Payloads

```json
{"scenario": "SC-01"}                                       // demo mode: resets the shared S/4 and clears the shared case tables
{"case": { ...CaseMessage... }}                             // from the poller / queue
{"request": "Order 1,300 t of chips …", "user": "buyer01"}  // buyer request
{"approve": "4500000091-10", "approver": "planner:dewi"}
{"reject": "4500000091-10", "approver": "planner:dewi", "reason": "…"}
{"status": "4500000091-10"}
```

Each reply is `{"case": CaseRecord, "trace": [...]}`, or `{"error", "code"}` with a code of
`bad_request`, `not_found`, `conflict`, `not_available` or `failed`. Add `"include_trace": false` to
leave out the trace.

**Warning:** the deployed runtime points `SYNAPSE_ERP_URL` at the Cloud Foundry `/s4` with
`SYNAPSE_DEMO=1`, so a `scenario` payload resets the shared mock S/4 (the one the console uses) and
deletes every case in the shared DynamoDB tables. The in-process mock is only the failover
(`SYNAPSE_FALLBACK_MOCK=1`).

## Deploy (ap-southeast-2)

```bash
ACCOUNT=398074591173 REGION=ap-southeast-2 REPO=synapsesupply-agent

# 1. Image to ECR (ARM64)
aws ecr create-repository --repository-name $REPO --region $REGION --image-scanning-configuration scanOnPush=true
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker buildx build --platform linux/arm64 -t $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest --push .

# 2. Execution role and secret: done (see the table above). The secret is read at startup by
#    synapse.env.load_secrets_manager when SYNAPSE_SECRETS_ID is set.

# 3. Runtime
aws bedrock-agentcore-control create-agent-runtime --region $REGION \
  --agent-runtime-name synapsesupply \
  --agent-runtime-artifact "containerConfiguration={containerUri=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest}" \
  --network-configuration networkMode=PUBLIC \
  --role-arn arn:aws:iam::$ACCOUNT:role/SynapseSupplyAgentCoreRuntime \
  --environment-variables '{"AWS_REGION":"ap-southeast-2","SYNAPSE_SECRETS_ID":"synapsesupply/runtime","SYNAPSE_MODEL_PROVIDERS":"bedrock,aicore","SYNAPSE_CASES_TABLE":"SynapseSupplyCases","SYNAPSE_TRACE_TABLE":"SynapseSupplyTrace","SYNAPSE_AUDIT_BUCKET":"synapsesupply-audit-398074591173-ap-southeast-2","SYNAPSE_ERP_URL":"https://synapsesupply-api-yang-penting-daftar-dulu.cfapps.ap10.hana.ondemand.com/s4","SYNAPSE_FALLBACK_MOCK":"1","SYNAPSE_DEMO":"1"}'
# After pushing a new image: scripts/agentcore_update.sh (update-agent-runtime with these same
# variables: shared tables, audit bucket, CF /s4 with mock failover, demo mode; then waits for READY).

# 4. Invoke
aws bedrock-agentcore invoke-agent-runtime --region $REGION \
  --agent-runtime-arn arn:aws:bedrock-agentcore:$REGION:$ACCOUNT:runtime/synapsesupply-vFgJ0n85b6 \
  --runtime-session-id "synapsesupply-demo-$(date +%s)-session-0001" \
  --cli-binary-format raw-in-base64-out --payload '{"scenario":"SC-01","include_trace":false}' out.json
# Caution: this resets the shared S/4 and clears the console's cases (see Payloads).
```

The JSON form of `--environment-variables` is needed because `bedrock,aicore` contains a comma.

**AI Core credentials** come from the secret, never from the runtime's plain configuration. Without
them, the runtime uses Bedrock only, and the deterministic autopilot if no model answers.

## Not covered yet

- **AgentCore Gateway + Policy:** `src/synapse/policy/synapse.cedar` is the policy set. Entity and
  action names must be mapped to the names AgentCore generates for the gateway's tools.
- **Approver identity:** pass the caller's identity via `--runtime-user-id` / AgentCore Identity
  instead of the `approver` field.
