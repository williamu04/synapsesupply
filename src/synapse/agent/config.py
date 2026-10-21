"""Runtime settings, read from the environment once per process."""
import json
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Settings:
    # Model routing: a cheap model triages free text, a stronger one plans. Bedrock IDs are
    # cross-region inference profiles; confirm availability in the Bedrock console for the region.
    reasoning_model_id: str = field(default_factory=lambda: _env(
        "SYNAPSE_REASONING_MODEL_ID", "global.anthropic.claude-sonnet-5-5"))
    triage_model_id: str = field(default_factory=lambda: _env(
        "SYNAPSE_TRIAGE_MODEL_ID", "global.anthropic.claude-haiku-5-5"))
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "us-west-2"))
    # Fallback reasoning model on SAP AI Core (Generative AI Hub) via LiteLLM's "sap/" provider.
    # Enabled when AICORE_CLIENT_ID is set (see the Joule A2A sample's .env for the variables).
    aicore_model_id: str = field(default_factory=lambda: _env(
        "SYNAPSE_AICORE_MODEL_ID", "sap/anthropic--claude-4.6-sonnet"))
    max_tokens: int = 16_000
    # Order of model providers to try. "aicore" alone skips Bedrock (e.g. on Cloud Foundry while the
    # AWS account is unverified), avoiding a failed Bedrock call before every model request.
    model_providers: tuple[str, ...] = field(default_factory=lambda: tuple(
        p.strip() for p in _env("SYNAPSE_MODEL_PROVIDERS", "bedrock,aicore").split(",") if p.strip()))

    # Planning parameters
    service_level: float = 0.95
    horizon_days: int = 7
    history_days: int = 90
    order_cost_usd: float = 250.0           # fixed cost per purchase order, for EOQ
    holding_cost_rate: float = 0.25         # per year, fraction of unit price, for EOQ
    plant_names: dict[str, str] = field(default_factory=lambda: json.loads(_env(
        "SYNAPSE_PLANT_NAMES", '{"1100": "Mill Riau-1", "1200": "Mill Jambi-2"}')))

    @property
    def aicore_enabled(self) -> bool:
        return bool(os.environ.get("AICORE_CLIENT_ID"))
