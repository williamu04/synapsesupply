"""A Strands `Model` that replays a fixed script instead of calling an LLM.

Each turn is either a list of tool calls `[(tool_name, input_dict), ...]` or a final text string.
It lets tests drive the real Strands agent loop (tool dispatch, hooks, our policy gate) without
Bedrock credentials. A turn may also be a callable `(messages) -> turn` to react to tool results.
"""
import json
from collections.abc import AsyncIterable, Callable
from typing import Any

from strands.models.model import Model

Turn = str | list[tuple[str, dict]] | Callable[[list], "Turn"]


class ScriptedModel(Model):
    def __init__(self, turns: list[Turn], model_id: str = "scripted"):
        self.turns = list(turns)
        self.config = {"model_id": model_id}
        self.calls: list[list] = []
        self.tool_specs: list[dict] = []

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("ScriptedModel does not do structured output")
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncIterable[dict]:
        self.calls.append(list(messages))
        self.tool_specs = list(tool_specs or [])
        if not self.turns:
            raise RuntimeError("ScriptedModel ran out of turns")
        turn = self.turns.pop(0)
        if callable(turn):
            turn = turn(messages)
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(turn, str):
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": turn}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            return
        for n, (name, tool_input) in enumerate(turn):
            tool_id = f"tool-{len(self.calls)}-{n}"
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tool_id, "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


class FailingModel(ScriptedModel):
    """Simulates an unreachable model endpoint (expired credentials, region outage)."""

    def __init__(self, error: Exception | None = None):
        super().__init__([])
        self.error = error or ConnectionError("model endpoint unreachable")

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        raise self.error
        yield  # pragma: no cover


def tool_results(messages: list) -> list[dict]:
    """All toolResult blocks in the conversation so far, parsed from their JSON text."""
    out = []
    for m in messages:
        for block in m.get("content", []):
            if "toolResult" in block:
                for c in block["toolResult"].get("content", []):
                    if "text" in c:
                        try:
                            out.append(json.loads(c["text"]))
                        except ValueError:
                            out.append({"text": c["text"]})
                    elif "json" in c:
                        out.append(c["json"])
    return out
