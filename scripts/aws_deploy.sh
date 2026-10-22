#!/usr/bin/env bash
# Creates or updates the SynapseSupply AWS stack (infra/synapsesupply.yaml) in ap-southeast-2 and
# prints its outputs. Safe to re-run: unchanged stacks are left alone. Needs: aws login.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION=ap-southeast-2
STACK=synapsesupply

aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/synapsesupply.yaml \
  --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset \
  --tags Project=ID-Hackathon-2026

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text
