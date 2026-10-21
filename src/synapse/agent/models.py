"""Model routing.

  * Triage (free text -> structured request): Claude Haiku on Bedrock. Cheap and fast; same
    AI Core failover as planning.
  * Planning (the tool-use loop): Claude Sonnet on Bedrock, with automatic failover to Claude on
    SAP AI Core (Generative AI Hub) through LiteLLM when AI Core credentials are configured.

Sampling parameters (temperature, top_p) are left unset: current Claude models reject non-default
values. Determinism comes from tools and SOPs, not from temperature.
"""
import logging

from strands.models import BedrockModel, Model, ModelRouter

from .config import Settings

log = logging.getLogger(__name__)


def bedrock(model_id: str, settings: Settings) -> BedrockModel:
    return BedrockModel(model_id=model_id, region_name=settings.aws_region, max_tokens=settings.max_tokens)


def aicore(settings: Settings) -> Model | None:
    if not settings.aicore_enabled:
        return None
    try:
        from strands.models.litellm import LiteLLMModel
    except ImportError:
        log.warning("AI Core fallback disabled: install the 'aicore' extra (strands-agents[litellm])")
        return None
    return LiteLLMModel(model_id=settings.aicore_model_id, params={"max_tokens": settings.max_tokens})


def _route(bedrock_model_id: str, settings: Settings) -> Model | ModelRouter:
    candidates = []
    if "bedrock" in settings.model_providers:
        candidates.append(bedrock(bedrock_model_id, settings))
    if "aicore" in settings.model_providers and (m := aicore(settings)) is not None:
        candidates.append(m)
    if not candidates:
        raise RuntimeError(f"No usable model provider in SYNAPSE_MODEL_PROVIDERS={','.join(settings.model_providers)}")
    return candidates[0] if len(candidates) == 1 else ModelRouter(candidates)


def reasoning_model(settings: Settings | None = None) -> Model | ModelRouter:
    settings = settings or Settings()
    return _route(settings.reasoning_model_id, settings)


def triage_model(settings: Settings | None = None) -> Model | ModelRouter:
    settings = settings or Settings()
    return _route(settings.triage_model_id, settings)
