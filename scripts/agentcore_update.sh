#!/usr/bin/env bash
# Points the AgentCore runtime at the current :latest image in ECR (ap-southeast-2), with the
# settings below, and waits until it is READY. Run after every image push:
#   docker buildx build --platform linux/arm64 -t <ecr>/synapsesupply-agent:latest --push .
set -euo pipefail

ACCOUNT=398074591173
REGION=ap-southeast-2
RUNTIME_ID=synapsesupply-vFgJ0n85b6
IMAGE=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/synapsesupply-agent:latest

aws bedrock-agentcore-control update-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" \
  --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"$IMAGE\"}}" \
  --network-configuration networkMode=PUBLIC \
  --role-arn "arn:aws:iam::$ACCOUNT:role/SynapseSupplyAgentCoreRuntime" \
  --environment-variables '{"AWS_REGION":"ap-southeast-2","SYNAPSE_SECRETS_ID":"synapsesupply/runtime","SYNAPSE_MODEL_PROVIDERS":"bedrock,aicore","SYNAPSE_CASES_TABLE":"SynapseSupplyCases","SYNAPSE_TRACE_TABLE":"SynapseSupplyTrace","SYNAPSE_AUDIT_BUCKET":"synapsesupply-audit-398074591173-ap-southeast-2"}' \
  --query '[agentRuntimeVersion,status]' --output text

for _ in $(seq 1 60); do
  status=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" \
    --query status --output text)
  [ "$status" = READY ] && { echo "READY"; exit 0; }
  sleep 5
done
echo "still $status after 5 minutes" >&2
exit 1
