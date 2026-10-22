"""Model routing.

  * Planning (the tool-use loop) and triage (free text -> structured request): Claude Sonnet 4.6 on
    Bedrock, with automatic failover to Claude on SAP AI Core (Generative AI Hub) through LiteLLM
    when AI Core credentials are configured.
  * Failover is fast: no boto3 retries and no throttling backoff when another provider can answer,
    and a provider that fails is skipped process-wide for a cooldown (`CooldownStrategy`). So
    "bedrock,aicore" is safe to configure before Bedrock has quota: cases run on AI Core, and Bedrock
    takes over by itself within one cooldown of the quota arriving.

Sampling parameters (temperature, top_p) are left unset: current Claude models reject non-default
values. Determinism comes from tools and SOPs, not from temperature.
"""
import logging
import threading
import time

from botocore.config import Config as BotocoreConfig
from strands.event_loop._retry import ModelRetryStrategy
from strands.models import BedrockModel, Model, ModelRouter
from strands.models.routing import FallbackStrategy, RoutingCandidate, RoutingContext

from .config import Settings

log = logging.getLogger(__name__)

# One attempt per call: the router, not boto3, decides what happens after a failure.
_BEDROCK_CLIENT = BotocoreConfig(retries={"total_max_attempts": 1, "mode": "standard"},
                                 connect_timeout=5, read_timeout=120)


def bedrock(model_id: str, settings: Settings) -> BedrockModel:
    return BedrockModel(model_id=model_id, region_name=settings.aws_region, max_tokens=settings.max_tokens,
                        boto_client_config=_BEDROCK_CLIENT)


def aicore(settings: Settings) -> Model | None:
    if not settings.aicore_enabled:
        return None
    try:
        from strands.models.litellm import LiteLLMModel
    except ImportError:
        log.warning("AI Core fallback disabled: install the 'aicore' extra (strands-agents[litellm])")
        return None
    return LiteLLMModel(model_id=settings.aicore_model_id, params={"max_tokens": settings.max_tokens})


class CooldownStrategy:
    """Ordered failover that remembers failures across cases.

    Strands' `FallbackStrategy` forgets failures when an invocation ends, so every new case would
    try a provider that is out of quota again. Here a candidate that fails is skipped, by name and
    process-wide, for `cooldown_s`; after that it is tried again. If every candidate is cooling down,
    plain failover applies, so a case is never refused for that reason.
    """

    def __init__(self, cooldown_s: float, clock=time.monotonic):
        self.cooldown_s, self._clock = cooldown_s, clock
        self._fallback = FallbackStrategy()
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def cooling(self, name: str) -> bool:
        with self._lock:
            return self._until.get(name, 0.0) > self._clock()

    async def select(self, context: RoutingContext, **kwargs) -> RoutingCandidate | None:
        now = self._clock()
        if context.attempts and (last := context.attempts[-1]).exception is not None and last.candidate.name:
            with self._lock:
                self._until[last.candidate.name] = now + self.cooldown_s
            log.warning("model provider %s failed (%s); skipping it for %.0f s", last.candidate.name,
                        type(last.exception).__name__, self.cooldown_s)
        with self._lock:
            ready = [c for c in context.candidates if self._until.get(c.name or "", 0.0) <= now]
        if ready and len(ready) < len(context.candidates):
            narrowed = RoutingContext(messages=context.messages, system_prompt=context.system_prompt,
                                      tool_specs=context.tool_specs, candidates=ready,
                                      invocation_state=context.invocation_state, attempts=context.attempts)
            if (choice := await self._fallback.select(narrowed, **kwargs)) is not None:
                return choice
        return await self._fallback.select(context, **kwargs)


_strategies: dict[float, CooldownStrategy] = {}  # one per cooldown, shared by all routers


def _strategy(settings: Settings) -> CooldownStrategy:
    return _strategies.setdefault(settings.model_cooldown_s, CooldownStrategy(settings.model_cooldown_s))


def _route(bedrock_model_id: str, settings: Settings) -> Model | ModelRouter:
    candidates = []
    if "bedrock" in settings.model_providers:
        candidates.append(RoutingCandidate(bedrock(bedrock_model_id, settings), name="bedrock"))
    if "aicore" in settings.model_providers and (m := aicore(settings)) is not None:
        candidates.append(RoutingCandidate(m, name="aicore"))
    if not candidates:
        raise RuntimeError(f"No usable model provider in SYNAPSE_MODEL_PROVIDERS={','.join(settings.model_providers)}")
    if len(candidates) == 1:
        return candidates[0].model
    return ModelRouter(candidates, strategy=_strategy(settings))


def retry_strategy(model: Model | ModelRouter) -> ModelRetryStrategy:
    """With a router, a throttled call fails over at once instead of backing off (4, 8, 16 s …)
    first; the next provider is the retry. A single model keeps Strands' default backoff."""
    return ModelRetryStrategy(max_attempts=1) if isinstance(model, ModelRouter) else ModelRetryStrategy()


def reasoning_model(settings: Settings | None = None) -> Model | ModelRouter:
    settings = settings or Settings()
    return _route(settings.reasoning_model_id, settings)


def triage_model(settings: Settings | None = None) -> Model | ModelRouter:
    settings = settings or Settings()
    return _route(settings.triage_model_id, settings)
