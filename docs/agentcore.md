# Deploying the agent to Amazon Bedrock AgentCore Runtime

**Status (2026-10-22): packaged and tested locally; not deployed.** Our AWS role is denied ECR and
AgentCore (an organization SCP). Everything below can be run as soon as access is granted.

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

## Deploy (us-west-2)

```bash
ACCOUNT=398074591173 REGION=us-west-2 REPO=synapsesupply-agent

# 1. Image to ECR (ARM64)
aws ecr create-repository --repository-name $REPO --region $REGION
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker buildx build --platform linux/arm64 -t $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest --push .

# 2. Execution role (once): trusted by bedrock-agentcore.amazonaws.com, allowed to pull from ECR,
#    write CloudWatch Logs and call bedrock:InvokeModel / InvokeModelWithResponseStream.

# 3. Runtime
aws bedrock-agentcore-control create-agent-runtime --region $REGION \
  --agent-runtime-name synapsesupply \
  --agent-runtime-artifact "containerConfiguration={containerUri=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest}" \
  --network-configuration networkMode=PUBLIC \
  --role-arn arn:aws:iam::$ACCOUNT:role/<execution-role> \
  --environment-variables "SYNAPSE_MODEL_PROVIDERS=bedrock,aicore,SYNAPSE_REASONING_MODEL_ID=global.anthropic.claude-sonnet-4-6,SYNAPSE_TRIAGE_MODEL_ID=global.anthropic.claude-sonnet-4-6"

# 4. Invoke
aws bedrock-agentcore invoke-agent-runtime --region $REGION \
  --agent-runtime-arn <arn from step 3> \
  --cli-binary-format raw-in-base64-out --payload '{"scenario":"SC-01","include_trace":false}' out.json
```

Check the environment-variable shorthand against `aws bedrock-agentcore-control create-agent-runtime
help` when running it: values that contain commas may need the JSON form.

**AI Core fallback:** to keep the SAP AI Core failover inside AgentCore, provide the `AICORE_*`
variables (the client secret preferably from Secrets Manager, not as a plain environment variable).
Without them, the runtime uses Bedrock only, and the deterministic autopilot if Bedrock fails.

## Not covered yet

- **AgentCore Gateway + Policy:** `src/synapse/policy/synapse.cedar` is the policy set. Entity and
  action names must be mapped to the names AgentCore generates for the gateway's tools.
- **Persistence:** cases live in memory per runtime session; a DynamoDB `CaseRepository` is the
  planned replacement (the interface is `synapse.agent.cases.CaseRepository`).
- **Approver identity:** pass the caller's identity via `--runtime-user-id` / AgentCore Identity
  instead of the `approver` field.
