"""Secrets and local settings for every entry point (CLI, API, Joule agent, AgentCore).

* `.env` (git-ignored) for local runs.
* AWS Secrets Manager when `SYNAPSE_SECRETS_ID` names a secret: its value is a JSON object of
  environment variables (e.g. the AI Core client id and secret). Used on AgentCore Runtime, so
  credentials never sit in the runtime's plain configuration.

Variables already set in the environment always win.
"""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)


def load_env(path: str | Path = ".env") -> bool:
    loaded = load_dotenv(path, override=False)
    load_secrets_manager()
    return loaded


def load_secrets_manager(client=None) -> list[str]:
    """Returns the names of the variables it set (never their values)."""
    secret_id = os.environ.get("SYNAPSE_SECRETS_ID")
    if not secret_id:
        return []
    try:
        if client is None:
            import boto3
            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION") or "ap-southeast-2")
        values = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    except Exception as e:  # noqa: BLE001 — a missing secret must not stop startup; the model fallback handles it
        log.warning("could not load secret %s: %s", secret_id, type(e).__name__)
        return []
    if not isinstance(values, dict):
        log.warning("secret %s is not a JSON object; ignored", secret_id)
        return []
    set_names = []
    for name, value in values.items():
        if isinstance(name, str) and isinstance(value, str) and name not in os.environ:
            os.environ[name] = value
            set_names.append(name)
    return set_names
