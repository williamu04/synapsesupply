"""A2A server for SAP Joule (same pattern as the event's Joule A2A sample).

Joule's `agent-request` action sends the user's message with A2A `message/send` through a BTP
destination; the reply's first artifact text is shown in the chat (see joule/ for the capability).

  uv run uvicorn synapse.joule.server:app --port 8090

  SYNAPSE_API_URL      SynapseSupply API base URL (default http://localhost:8080)
  SYNAPSE_API_KEY      x-api-key for the API, if it requires one
  SYNAPSE_CONSOLE_URL  console URL for deep links in replies (default: <SYNAPSE_API_URL>/console)
  SYNAPSE_A2A_KEY      required access key for this endpoint (x-api-key, or Basic auth password —
                       configure the BTP destination with BasicAuthentication). Set it in production.
"""
import asyncio
import base64
import json
import logging
import os
import secrets

import httpx
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    DataPart,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from synapse.env import load_env

from .bridge import SynapseApi, claimed_user, respond


def unwrap(text: str) -> str:
    """Joule sends the user's words as a JSON string literal ("\"approve 4500000091-10\"", seen in
    production); the sample also accepts {"user_request": "..."}. Plain text passes through."""
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("user_request"), str):
        return parsed["user_request"]
    return text


log = logging.getLogger("uvicorn.error")  # uvicorn configures this logger; output lands in `cf logs`


def _log_message(context: RequestContext) -> None:
    """Structure of what Joule sent (part kinds, sizes, a short prefix of each text part)."""
    message = context.message
    if message is None:
        log.info("A2A message: none")
        return
    parts = []
    for part in message.parts:
        p = getattr(part, "root", part)
        text = getattr(p, "text", None)
        parts.append({"kind": getattr(p, "kind", type(p).__name__), "len": len(text) if text else None,
                      "head": text[:200] if text else None})
    log.info("A2A message: %s", json.dumps({"parts": parts, "metadata_keys": sorted((message.metadata or {}).keys()),
                                            "context_id": context.context_id}, ensure_ascii=False))


class SynapseExecutor(AgentExecutor):
    def __init__(self, api: SynapseApi):
        self.api = api

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id, context_id=context.context_id,
            status=TaskStatus(state=TaskState.working), final=False))
        _log_message(context)
        text = context.get_user_input()
        text = unwrap(text)
        headers = context.call_context.state.get("headers", {}) if context.call_context else {}
        reply = await asyncio.to_thread(respond, str(text), claimed_user(headers), self.api)
        # parts[0]: markdown shown in the chat; parts[1]: data the Joule function uses for buttons.
        await event_queue.enqueue_event(TaskArtifactUpdateEvent(
            task_id=context.task_id, context_id=context.context_id,
            artifact=Artifact(artifactId="synapse_reply", name="synapse_reply",
                              parts=[TextPart(text=reply.text), DataPart(data=reply.data)])))
        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id, context_id=context.context_id,
            status=TaskStatus(state=TaskState.completed), final=True))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id, context_id=context.context_id,
            status=TaskStatus(state=TaskState.canceled), final=True))


def public_url() -> str:
    """Cloud Foundry route from VCAP_APPLICATION, else localhost."""
    uris = json.loads(os.environ.get("VCAP_APPLICATION", "{}")).get("application_uris", [])
    return f"https://{uris[0]}" if uris else f"http://localhost:{os.environ.get('PORT', '8090')}"


def agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="SynapseSupply",
        description=("Wood-fibre supply exception agent for pulp mills: sources compliantly (EUDR gate), "
                     "rebalances stock between mills and asks planners to approve what it may not do alone."),
        url=url, version="0.1.0", capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(id="source", name="Source wood fibre",
                       description="Order or rebalance chips and logs for a mill, with compliance and policy checks",
                       tags=["supply chain", "procurement", "EUDR", "pulp"], examples=[
                           "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood"],
                       inputModes=["text/plain"], outputModes=["text/markdown"]),
            AgentSkill(id="approve", name="Approve supply actions",
                       description="List, approve or reject actions the agent escalated to a planner",
                       tags=["approval", "human in the loop"], examples=[
                           "What needs my approval?", "approve 4500000091-10"],
                       inputModes=["text/plain"], outputModes=["text/markdown"]),
        ],
        defaultInputModes=["text/plain"], defaultOutputModes=["text/markdown"])


def _access_granted(headers, access_key: str) -> bool:
    """x-api-key, or HTTP Basic with the key as password (what a BTP destination with
    BasicAuthentication sends)."""
    if secrets.compare_digest(headers.get("x-api-key", ""), access_key):
        return True
    auth = headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            _, _, password = base64.b64decode(auth[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return secrets.compare_digest(password, access_key)
    return False


def create_app(api: SynapseApi, url: str | None = None, access_key: str | None = None) -> FastAPI:
    """access_key: when set, every route except /health requires it. The agent holds the API key, so
    an open A2A endpoint would let anyone approve cases."""
    handler = DefaultRequestHandler(agent_executor=SynapseExecutor(api), task_store=InMemoryTaskStore())
    app = A2AFastAPIApplication(agent_card=agent_card(url or public_url()), http_handler=handler).build()

    if access_key:
        @app.middleware("http")
        async def require_access(request: Request, call_next):
            if request.url.path != "/health" and not _access_granted(request.headers, access_key):
                return JSONResponse({"error": "unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="SynapseSupply Joule agent"'})
            return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def _from_env() -> FastAPI:
    load_env()
    base = os.environ.get("SYNAPSE_API_URL", "http://localhost:8080").rstrip("/")
    key = os.environ.get("SYNAPSE_API_KEY")
    client = httpx.Client(base_url=base, timeout=30, headers={"x-api-key": key} if key else {})
    return create_app(SynapseApi(client, os.environ.get("SYNAPSE_CONSOLE_URL", f"{base}/console")),
                      access_key=os.environ.get("SYNAPSE_A2A_KEY"))


app = _from_env()
