#!/usr/bin/env bash
# Creates or updates the SynapseSupply AWS stack (infra/synapsesupply.yaml) in ap-southeast-2.
# Safe to re-run. Needs: aws login, uv, and .env (for the S/4 login the poller and agent use).
#
#   1. adds SYNAPSE_ERP_USER / SYNAPSE_ERP_PASSWORD (the Cloud Foundry API key) to the runtime secret
#   2. builds the dispatcher Lambda with a current boto3 (it calls bedrock-agentcore)
#   3. uploads the Lambda code to an artifacts bucket and deploys the stack
set -euo pipefail
cd "$(dirname "$0")/.."

REGION=ap-southeast-2
STACK=synapsesupply
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ARTIFACTS=synapsesupply-artifacts-$ACCOUNT-$REGION
SECRET_ID=synapsesupply/runtime

echo "1/3 secret: S/4 login for the poller and the agent"
uv run python - "$REGION" "$SECRET_ID" <<'EOF'
import json, sys
import boto3
from dotenv import dotenv_values
region, secret_id = sys.argv[1:3]
key = dotenv_values(".env").get("SYNAPSE_CF_API_KEY")
if not key:
    sys.exit("SYNAPSE_CF_API_KEY missing in .env")
sm = boto3.client("secretsmanager", region_name=region)
values = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
wanted = {"SYNAPSE_ERP_USER": "agentcore", "SYNAPSE_ERP_PASSWORD": key}
if any(values.get(k) != v for k, v in wanted.items()):
    sm.put_secret_value(SecretId=secret_id, SecretString=json.dumps(values | wanted))
    print("   updated (values not shown)")
else:
    print("   already current")
EOF

echo "2/3 build: dispatcher Lambda"
rm -rf build/lambdas && mkdir -p build/lambdas/dispatcher
cp lambdas/dispatcher/handler.py build/lambdas/dispatcher/
uv pip install --quiet --target build/lambdas/dispatcher "boto3>=1.40"

echo "3/3 deploy: stack $STACK"
if ! aws s3api head-bucket --bucket "$ARTIFACTS" 2>/dev/null; then
  aws s3api create-bucket --bucket "$ARTIFACTS" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  aws s3api put-public-access-block --bucket "$ARTIFACTS" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi
aws cloudformation package --region "$REGION" --template-file infra/synapsesupply.yaml \
  --s3-bucket "$ARTIFACTS" --s3-prefix lambda --output-template-file build/packaged.yaml >/dev/null
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file build/packaged.yaml \
  --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset \
  --tags Project=ID-Hackathon-2026

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text
