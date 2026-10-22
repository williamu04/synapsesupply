"""Case dispatcher (Lambda, SQS FIFO trigger, batch size 1): hands each queued case to the agent on
AgentCore Runtime. A case that already exists ("conflict") is done; any other error raises, so SQS
retries the message and finally moves it to the dead-letter queue.

boto3 only. Environment: AGENT_RUNTIME_ARN.
"""
import json
import os
import uuid


def dispatch(agentcore, runtime_arn: str, message: dict) -> dict:
    session = f"synapsesupply-case-{message['case_id']}-{uuid.uuid4().hex}"   # AgentCore wants >= 33 chars
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn, runtimeSessionId=session, contentType="application/json",
        accept="application/json", payload=json.dumps({"case": message, "include_trace": False}).encode())
    body = json.loads(response["response"].read())
    if "error" in body:
        if body.get("code") == "conflict":
            return {"case_id": message["case_id"], "result": "already handled"}
        raise RuntimeError(f"agent failed for {message['case_id']}: {body.get('code')}: {body.get('error')}")
    case = body["case"]
    return {"case_id": case["case_id"], "result": case["status"]}


def handler(event, context):
    import boto3
    agentcore = boto3.client("bedrock-agentcore")
    results = [dispatch(agentcore, os.environ["AGENT_RUNTIME_ARN"], json.loads(record["body"]))
               for record in event["Records"]]
    print(json.dumps(results))
    return results
