import asyncio
import time

from scripted_model import FailingModel, ScriptedModel
from strands import Agent
from strands.models import ModelRouter
from strands.models.routing import RoutingAttempt, RoutingCandidate, RoutingContext
from strands.types.exceptions import ModelThrottledException

from synapse.agent import models
from synapse.agent.config import Settings
from synapse.agent.models import CooldownStrategy, retry_strategy


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _context(candidates, attempts=()):
    return RoutingContext(messages=[], system_prompt=None, tool_specs=[], candidates=candidates,
                          invocation_state={}, attempts=attempts)


def test_failed_candidate_is_skipped_until_the_cooldown_ends():
    clock = Clock()
    strategy = CooldownStrategy(300, clock=clock)
    bedrock = RoutingCandidate(ScriptedModel([]), name="bedrock")
    aicore = RoutingCandidate(ScriptedModel([]), name="aicore")
    pick = lambda attempts=(): asyncio.run(strategy.select(_context([bedrock, aicore], attempts)))

    assert pick() is bedrock
    assert pick((RoutingAttempt(candidate=bedrock, exception=ModelThrottledException("per day")),)) is aicore
    assert strategy.cooling("bedrock")
    assert pick() is aicore                      # a new case: Bedrock is not even tried
    clock.now += 301
    assert pick() is bedrock                     # quota may be back: try it again


def test_all_cooling_still_returns_a_candidate():
    clock = Clock()
    strategy = CooldownStrategy(300, clock=clock)
    a, b = RoutingCandidate(ScriptedModel([]), name="a"), RoutingCandidate(ScriptedModel([]), name="b")
    asyncio.run(strategy.select(_context([a, b], (RoutingAttempt(candidate=a, exception=RuntimeError()),))))
    asyncio.run(strategy.select(_context([a, b], (RoutingAttempt(candidate=b, exception=RuntimeError()),))))
    assert asyncio.run(strategy.select(_context([a, b]))) is a


def test_throttled_provider_fails_over_at_once_and_is_skipped_next_case():
    strategy = CooldownStrategy(300)
    throttled = FailingModel(ModelThrottledException("Too many tokens per day"))
    backup = ScriptedModel(["first answer", "second answer"])

    def run():
        router = ModelRouter([RoutingCandidate(throttled, name="bedrock"), RoutingCandidate(backup, name="aicore")],
                             strategy=strategy)
        return str(Agent(model=router, callback_handler=None, retry_strategy=retry_strategy(router))("hi"))

    start = time.monotonic()
    assert "first answer" in run()
    assert time.monotonic() - start < 3           # no 4/8/16 s throttling backoff before failover
    calls_to_throttled = len(throttled.calls)
    assert "second answer" in run()
    assert len(throttled.calls) == calls_to_throttled   # second case went straight to AI Core


def test_defaults_target_the_accounts_model_and_region(monkeypatch):
    for name in ("AWS_REGION", "SYNAPSE_REASONING_MODEL_ID", "SYNAPSE_TRIAGE_MODEL_ID", "SYNAPSE_MODEL_PROVIDERS"):
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert s.aws_region == "ap-southeast-2"
    assert s.reasoning_model_id == s.triage_model_id == "global.anthropic.claude-sonnet-4-6"
    assert s.model_providers == ("bedrock", "aicore")
    b = models.bedrock(s.reasoning_model_id, s)
    assert b.client.meta.region_name == "ap-southeast-2"
    assert b.client.meta.config.retries["total_max_attempts"] == 1


def test_single_model_keeps_default_backoff():
    assert retry_strategy(ScriptedModel([]))._max_attempts == 6
