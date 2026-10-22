#!/usr/bin/env bash
# Gives the Cloud Foundry API app its own AWS credentials for Bedrock (ap-southeast-2).
#
# Creates IAM user synapsesupply-cf-bedrock, allowed ONLY to invoke Anthropic models, makes one
# access key and writes it straight into the app's environment (never printed, never on disk).
# Re-running replaces the key (rotation). Needs: aws login (account 398074591173) and cf login.
set -euo pipefail

USER_NAME=synapsesupply-cf-bedrock
ACCOUNT=398074591173
APP=synapsesupply-api-yang-penting-daftar-dulu

POLICY=$(cat <<EOF
{"Version":"2012-10-17","Statement":[{"Sid":"InvokeClaudeOnly","Effect":"Allow",
 "Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],
 "Resource":["arn:aws:bedrock:*::foundation-model/anthropic.*","arn:aws:bedrock:*:${ACCOUNT}:inference-profile/*anthropic*"]}]}
EOF
)

aws iam get-user --user-name "$USER_NAME" >/dev/null 2>&1 \
  || aws iam create-user --user-name "$USER_NAME" --tags Key=Project,Value=ID-Hackathon-2026 >/dev/null
aws iam put-user-policy --user-name "$USER_NAME" --policy-name bedrock-invoke --policy-document "$POLICY"
echo "IAM user $USER_NAME: Bedrock invoke only"

# Rotate: delete old keys, then create one new key.
for old in $(aws iam list-access-keys --user-name "$USER_NAME" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$old"
done
read -r KEY_ID KEY_SECRET < <(aws iam create-access-key --user-name "$USER_NAME" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)

cf set-env "$APP" AWS_ACCESS_KEY_ID "$KEY_ID" >/dev/null
cf set-env "$APP" AWS_SECRET_ACCESS_KEY "$KEY_SECRET" >/dev/null
unset KEY_ID KEY_SECRET
echo "credentials set on $APP; restarting (about 1 minute)"
cf restart "$APP" >/dev/null
echo "done"
