# Deploying the agent to Amazon Bedrock AgentCore Runtime

**Status (2026-10-22): deployed and running in `ap-southeast-2`.** Runtime `synapsesupply-vFgJ0n85b6`
(status READY). SC-01 invoked end to end: `AWAITING_APPROVAL` in 25 s, Claude via SAP AI Core
reasoning, SAP RPT-1 live (`sap-rpt-1.6`), Cedar ESCALATE ($8,280 > $5,000).
The account's organization policy denies these services in `us-west-2` but **allows them in
`ap-southeast-2` (Sydney)**, so everything runs there. Bedrock models have a zero token quota in both
regions, so the runtime uses Claude on SAP AI Core until the quota arrives.

Created in `ap-southeast-2` (2026-10-22), besides the runtime:

| Resource | Name |
|---|---|
| ECR repository (scan on push) | `synapsesupply-agent`, tag `latest` (ARM64) |
| IAM execution role | `SynapseSupplyAgentCoreRuntime` (trust: `bedrock-agentcore.amazonaws.com`, this account only) |
| Secrets Manager secret | `synapsesupply/runtime`: JSON with the `AICORE_*` variables and `LITELLM_PROVIDER` |

The role's inline policy `runtime` allows only: pulling this repository, writing the runtime's
CloudWatch logs, X-Ray/metrics, workload access tokens, reading `synapsesupply/runtime`, invoking
Bedrock models, and the (future) `SynapseSupplyCases` DynamoDB table.

## What exists

| Piece | File | Verified |
|---|---|---|
| Runtime entry point (bedrock-agentcore SDK: `POST /invocations`, `GET /ping`, port 8080) | `src/synapse/agentcore.py` | unit tests (`tests/test_agentcore.py`); real process over HTTP |
| ARM64 container (AgentCore runs linux/arm64) | `Dockerfile`, `.dockerignore` | built with buildx (248 MB), run under emulation: `/ping` Healthy, SC-01 handled, non-root user, no `.env` in the image |
| Same case service as the API | `synapse.api.main.build_service()` | shared wiring |

### Payloads

```json
{"scenario": "SC-01"}                                       // demo mode (in-process mock S/4)
{"case": { ...CaseMessage... }}                             // from the poller / queue
{"request": "Order 1,300 t of chips …", "user": "buyer01"}  // buyer request
{"approve": "4500000091-10", "approver": "planner:dewi"}
{"reject": "4500000091-10", "approver": "planner:dewi", "reason": "…"}
{"status": "4500000091-10"}
```

Each reply is `{"case": CaseRecord, "trace": [...]}`, or `{"error", "code"}` with a code of
`bad_request`, `not_found`, `conflict`, `not_available` or `failed`. Add `"include_trace": false` to
leave out the trace.

## Deploy (ap-southeast-2)

```bash
ACCOUNT=398074591173 REGION=ap-southeast-2 REPO=synapsesupply-agent

# 1. Image to ECR (ARM64)
aws ecr create-repository --repository-name $REPO --region $REGION
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
  --environment-variables '{"AWS_REGION":"ap-southeast-2","SYNAPSE_SECRETS_ID":"synapsesupply/runtime","SYNAPSE_MODEL_PROVIDERS":"bedrock,aicore"}'
# After pushing a new image: scripts/agentcore_update.sh (update-agent-runtime with the current
# settings, bedrock,aicore; then waits for READY).

# 4. Invoke
aws bedrock-agentcore invoke-agent-runtime --region $REGION \
  --agent-runtime-arn arn:aws:bedrock-agentcore:$REGION:$ACCOUNT:runtime/synapsesupply-vFgJ0n85b6 \
  --runtime-session-id "synapsesupply-demo-$(date +%s)-session-0001" \
  --cli-binary-format raw-in-base64-out --payload '{"scenario":"SC-01","include_trace":false}' out.json
```

The JSON form of `--environment-variables` is needed because `bedrock,aicore` contains a comma.

**AI Core credentials** come from the secret, never from the runtime's plain configuration. Without
them, the runtime uses Bedrock only, and the deterministic autopilot if no model answers.

## Not covered yet

- **AgentCore Gateway + Policy:** `src/synapse/policy/synapse.cedar` is the policy set. Entity and
  action names must be mapped to the names AgentCore generates for the gateway's tools.
- **Persistence:** cases live in memory per runtime session; a DynamoDB `CaseRepository` is the
  planned replacement (the interface is `synapse.agent.cases.CaseRepository`).
- **Approver identity:** pass the caller's identity via `--runtime-user-id` / AgentCore Identity
  instead of the `approver` field.
