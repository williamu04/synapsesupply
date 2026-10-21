"""HTTP API for the case service — the integration point for the Joule A2A bridge (M2) and the
console UI (M3). In AWS the same routes sit behind API Gateway; cases from the SQS FIFO queue reach
`POST /cases` through the agent-invoker Lambda.

  POST /cases                      CaseMessage -> 202 {case_id}; ?wait=true runs inline and returns the record
  POST /requests                   {utterance, user} -> USER_REQUEST case from Joule
  GET  /cases | /cases/{id}        case records
  GET  /cases/{id}/trace           all trace events as JSON
  GET  /cases/{id}/events          SSE: replays the trace, then streams live until the case is final.
                                   Honours Last-Event-ID; ?follow=false stops after the replay.
  POST /cases/{id}/approve         {approver}
  POST /cases/{id}/reject          {approver, reason}
  GET  /recordings/{name}          SSE replay of a recorded run (JSONL) with its original pacing; ?speed=2
  GET  /demo/scenarios             POST /demo/reset   POST /demo/scenarios/{id}/run   (demo mode only)

Cases are processed one at a time by a single worker, matching SQS FIFO semantics. If
SYNAPSE_API_KEY is set, every route except /health requires the `x-api-key` header.
"""
import asyncio
import base64
import json
import logging
import re
import secrets
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from synapse.agent.scenarios import request_message, scenario_message
from synapse.agent.service import CaseService, CaseStateError
from synapse.agent.trace import load_recording
from synapse.contracts import CaseMessage, CaseRecord, CaseStatus, TraceEvent, TraceKind

FINAL = {CaseStatus.EXECUTED, CaseStatus.REJECTED, CaseStatus.BLOCKED, CaseStatus.NO_ACTION_NEEDED,
         CaseStatus.FAILED}
POLL_SECONDS = 0.2
HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = 30 * 60
_RECORDING_NAME = re.compile(r"^[\w.-]+$")
log = logging.getLogger("uvicorn.error")
CHALLENGE = {"WWW-Authenticate": 'Basic realm="SynapseSupply"'}


class RequestIn(BaseModel):
    utterance: str = Field(min_length=1, max_length=2000)
    user: str | None = None


class ApproveIn(BaseModel):
    approver: str = Field(min_length=1, max_length=80)


class RejectIn(ApproveIn):
    reason: str = Field(min_length=1, max_length=500)


class Accepted(BaseModel):
    case_id: str
    status: CaseStatus = CaseStatus.NEW


class DemoControl:
    """Drives the mock S/4's admin endpoints (scenarios, reset). Not available against a real S/4."""

    def __init__(self, client: httpx.Client):
        self.client = client

    def as_of(self) -> date:
        return date.fromisoformat(self.client.get("/health").json()["as_of"])

    def scenarios(self) -> list[dict]:
        return self.client.get("/admin/scenarios").json()["scenarios"]

    def reset(self) -> None:
        self.client.post("/admin/reset").raise_for_status()

    def apply(self, scenario_id: str) -> dict:
        r = self.client.post(f"/admin/scenarios/{scenario_id}/apply")
        if r.status_code == 404:
            raise HTTPException(404, f"Unknown scenario {scenario_id}")
        r.raise_for_status()
        return r.json()["applied"]


def sse(event: TraceEvent) -> str:
    return f"id: {event.seq}\nevent: {event.kind.value}\ndata: {event.model_dump_json()}\n\n"


def create_api(service: CaseService, *, demo: DemoControl | None = None, api_key: str | None = None,
               recordings_dir: str | Path | None = None, cors_origins: list[str] | None = None,
               ui_dir: str | Path | None = None, boot_scenario: str | None = None,
               sleep: Callable[[float], object] = asyncio.sleep) -> FastAPI:
    """boot_scenario: in demo mode, stage this scenario (e.g. "SC-01") at startup, so a restart or
    redeploy never leaves the console and Joule without a case to show."""
    lock = threading.Lock()                       # one case operation at a time (FIFO semantics)
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="case-worker")

    def stage_boot_scenario() -> None:
        try:
            with lock:
                demo.reset()
                service.clear()
                scenario = demo.apply(boot_scenario)
            msg = scenario_message(scenario)
            queued.add(msg.case_id)
            record = run(msg)
            log.info("boot scenario %s staged: case %s %s", boot_scenario, record.case_id, record.status.value)
        except Exception as e:  # noqa: BLE001 — startup must never fail because of demo staging
            log.warning("boot scenario %s not staged: %s", boot_scenario, e)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if boot_scenario and demo is not None:
            worker.submit(stage_boot_scenario)
        yield
        worker.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="SynapseSupply API", version="0.1.0", lifespan=lifespan)
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST"],
                           allow_headers=["content-type", "x-api-key", "last-event-id"])
    queued: set[str] = set()
    recordings = Path(recordings_dir or "recordings")

    def authorized(x_api_key: str | None, api_key_param: str | None, authorization: str | None) -> bool:
        """Machine clients send x-api-key; browsers use HTTP Basic (any user, the key as password),
        which they then attach to every same-origin request, EventSource included."""
        if not api_key:
            return True
        if api_key in (x_api_key, api_key_param):
            return True
        if authorization and authorization.lower().startswith("basic "):
            try:
                _, _, password = base64.b64decode(authorization[6:]).decode().partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            return secrets.compare_digest(password, api_key)
        return False

    def require_key(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None),
                    api_key_param: str | None = Query(default=None, alias="api_key")) -> None:
        if not authorized(x_api_key, api_key_param, authorization):
            raise HTTPException(401, "Missing or invalid x-api-key", headers=CHALLENGE)

    guarded = [Depends(require_key)]

    def run(msg: CaseMessage) -> CaseRecord:
        try:
            with lock:
                return service.handle(msg)
        finally:
            queued.discard(msg.case_id)

    def submit(msg: CaseMessage, wait: bool, response: Response) -> CaseRecord | Accepted:
        if msg.case_id in queued or service.repo.get(msg.case_id) is not None:
            raise HTTPException(409, f"Case {msg.case_id} already exists")
        queued.add(msg.case_id)
        if wait:
            response.status_code = 200
            return run(msg)
        worker.submit(run, msg)
        return Accepted(case_id=msg.case_id)

    def record_or_404(case_id: str) -> CaseRecord | Accepted:
        record = service.repo.get(case_id)
        if record is not None:
            return record
        if case_id in queued:
            return Accepted(case_id=case_id)
        raise HTTPException(404, f"Unknown case {case_id}")

    @app.get("/health")
    def health():
        return {"status": "ok", "demo": demo is not None, "queued": len(queued)}

    # --- cases ----------------------------------------------------------------------------------

    @app.post("/cases", status_code=202, dependencies=guarded)
    def create_case(msg: CaseMessage, response: Response, wait: bool = False):
        return submit(msg, wait, response)

    @app.post("/requests", status_code=202, dependencies=guarded)
    def create_request(body: RequestIn, response: Response, wait: bool = False):
        return submit(request_message(body.utterance, body.user), wait, response)

    @app.get("/cases", dependencies=guarded)
    def list_cases() -> list[CaseRecord]:
        return service.repo.list()

    @app.get("/cases/{case_id}", dependencies=guarded)
    def get_case(case_id: str):
        return record_or_404(case_id)

    @app.get("/cases/{case_id}/trace", dependencies=guarded)
    def get_trace(case_id: str) -> list[TraceEvent]:
        record_or_404(case_id)
        return service.trace(case_id)

    @app.post("/cases/{case_id}/approve", dependencies=guarded)
    def approve(case_id: str, body: ApproveIn) -> CaseRecord:
        return _decide(lambda: service.approve(case_id, body.approver))

    @app.post("/cases/{case_id}/reject", dependencies=guarded)
    def reject(case_id: str, body: RejectIn) -> CaseRecord:
        return _decide(lambda: service.reject(case_id, body.approver, body.reason))

    def _decide(fn: Callable[[], CaseRecord]) -> CaseRecord:
        try:
            with lock:
                return fn()
        except KeyError as e:
            raise HTTPException(404, str(e)) from None
        except CaseStateError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/cases/{case_id}/events", dependencies=guarded)
    async def stream_events(case_id: str, request: Request, follow: bool = True):
        record_or_404(case_id)
        last = request.headers.get("last-event-id")
        start = int(last) + 1 if last and last.isdigit() else 0
        return StreamingResponse(_live(case_id, start, follow, request), media_type="text/event-stream",
                                 headers={"cache-control": "no-cache", "x-accel-buffering": "no"})

    async def _live(case_id: str, start: int, follow: bool, request: Request) -> AsyncIterator[str]:
        sent, waited, idle = start, 0.0, 0.0
        while True:
            events = service.trace(case_id)
            for event in events[sent:]:
                yield sse(event)
            sent = max(sent, len(events))
            record = service.repo.get(case_id)
            finished = (record is not None and record.status in FINAL and events
                        and events[-1].kind is TraceKind.DONE)
            if finished or not follow or waited >= MAX_STREAM_SECONDS or await request.is_disconnected():
                return
            await sleep(POLL_SECONDS)
            waited += POLL_SECONDS
            idle += POLL_SECONDS
            if idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                yield ": keep-alive\n\n"

    # --- recordings (the UI's replay toggle) ----------------------------------------------------

    @app.get("/recordings", dependencies=guarded)
    def list_recordings() -> list[str]:
        return sorted(p.stem for p in recordings.glob("*.jsonl"))

    @app.get("/recordings/{name}", dependencies=guarded)
    async def replay(name: str, speed: float = 1.0):
        if not _RECORDING_NAME.match(name) or not (recordings / f"{name}.jsonl").is_file():
            raise HTTPException(404, f"No recording {name}")
        if not 0.1 <= speed <= 50:
            raise HTTPException(422, "speed must be between 0.1 and 50")
        events = load_recording(recordings / f"{name}.jsonl")

        async def paced() -> AsyncIterator[str]:
            for prev, event in zip([None, *events], events, strict=False):
                if prev is not None:
                    await sleep(min(3.0, max(0.0, (event.ts - prev.ts).total_seconds()) / speed))
                yield sse(event)
        return StreamingResponse(paced(), media_type="text/event-stream", headers={"cache-control": "no-cache"})

    # --- demo control ---------------------------------------------------------------------------

    def need_demo() -> DemoControl:
        if demo is None:
            raise HTTPException(404, "Demo control is only available against the mock S/4")
        return demo

    @app.get("/demo/scenarios", dependencies=guarded)
    def demo_scenarios() -> list[dict]:
        return need_demo().scenarios()

    @app.post("/demo/reset", dependencies=guarded)
    def demo_reset():
        control = need_demo()
        with lock:
            control.reset()
            service.clear()
        return {"status": "reset", "at": datetime.now(UTC)}

    @app.post("/demo/scenarios/{scenario_id}/run", status_code=202, dependencies=guarded)
    def demo_run(scenario_id: str, response: Response, wait: bool = False):
        control = need_demo()
        with lock:
            control.reset()
            service.clear()
            scenario = control.apply(scenario_id)
        return submit(scenario_message(scenario), wait, response)

    if ui_dir and Path(ui_dir, "index.html").is_file():
        # The built console (ui/dist), so the demo runs from a single origin: http://host:8080/console/
        app.mount("/console", StaticFiles(directory=ui_dir, html=True), name="console")

        @app.middleware("http")
        async def protect_console(request: Request, call_next):
            if request.url.path.startswith("/console") and not authorized(
                    request.headers.get("x-api-key"), request.query_params.get("api_key"),
                    request.headers.get("authorization")):
                return Response("Authentication required", status_code=401, headers=CHALLENGE)
            return await call_next(request)

    return app


def recorded_events_json(path: str | Path) -> str:
    """Helper for the UI team: the recording as a JSON array (e.g. to bundle as a static fallback)."""
    return json.dumps([json.loads(e.model_dump_json()) for e in load_recording(path)])
