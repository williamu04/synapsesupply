"""Amazon Bedrock AgentCore Runtime entry point.

The same case service as the HTTP API, served the way AgentCore Runtime expects: `POST /invocations`
with a JSON payload, `GET /ping` for health, port 8080 (bedrock-agentcore SDK). Deploy steps:
docs/agentcore.md.

  uv run --extra agentcore python -m synapse.agentcore      # local, http://localhost:8080

Payloads (one key decides the operation):
  {"case": <CaseMessage>}                       handle a case (from the ERP poller / queue)
  {"request": "<utterance>", "user": "..."}     a buyer request, as from Joule
  {"approve": "<case_id>", "approver": "..."}   a planner decision
  {"reject": "<case_id>", "approver": "...", "reason": "..."}
  {"status": "<case_id>"}                       the case record and its trace
  {"scenario": "SC-01"}                         demo mode only: reset the mock S/4, apply, handle

Every reply is {"case": CaseRecord, "trace": [TraceEvent...]} or {"error": "...", "code": ...}.
State lives in memory for the life of the runtime session; persistence (DynamoDB) is planned.
"""
import threading

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError

from synapse.agent.scenarios import request_message, scenario_message
from synapse.agent.service import CaseService, CaseStateError
from synapse.contracts import CaseMessage, CaseRecord


def _reply(service: CaseService, record: CaseRecord, include_trace: bool) -> dict:
    out: dict = {"case": record.model_dump(mode="json")}
    if include_trace:
        out["trace"] = [e.model_dump(mode="json") for e in service.trace(record.case_id)]
    return out


def _error(code: str, message: str) -> dict:
    return {"error": message, "code": code}


def handle_payload(payload: dict, service: CaseService, demo=None, lock: "threading.Lock | None" = None) -> dict:
    """Dispatch one invocation. Never raises: AgentCore returns whatever this returns."""
    lock = lock or threading.Lock()
    if not isinstance(payload, dict):
        return _error("bad_request", "payload must be a JSON object")
    trace = bool(payload.get("include_trace", True))
    try:
        with lock:  # one case operation at a time, as in the API (FIFO per runtime session)
            if "case" in payload:
                return _reply(service, service.handle(CaseMessage.model_validate(payload["case"])), trace)
            if "request" in payload:
                text = str(payload["request"]).strip()
                if not text:
                    return _error("bad_request", "request text is empty")
                return _reply(service, service.handle(request_message(text, payload.get("user"))), trace)
            if "approve" in payload:
                return _reply(service, service.approve(str(payload["approve"]),
                                                       str(payload.get("approver") or "agentcore:unknown")), trace)
            if "reject" in payload:
                if not str(payload.get("reason", "")).strip():
                    return _error("bad_request", "reject needs a reason")
                return _reply(service, service.reject(str(payload["reject"]),
                                                      str(payload.get("approver") or "agentcore:unknown"),
                                                      str(payload["reason"])), trace)
            if "status" in payload:
                record = service.repo.get(str(payload["status"]))
                if record is None:
                    return _error("not_found", f"Unknown case {payload['status']}")
                return _reply(service, record, trace)
            if "scenario" in payload:
                if demo is None:
                    return _error("not_available", "scenarios run only against the mock S/4 (demo mode)")
                demo.reset()
                service.clear()
                scenario = demo.apply(str(payload["scenario"]))
                return _reply(service, service.handle(scenario_message(scenario)), trace)
    except ValidationError as e:
        return _error("bad_request", f"invalid case message: {e.errors()[0]['msg']}")
    except KeyError as e:
        return _error("not_found", str(e).strip("'"))
    except CaseStateError as e:
        return _error("conflict", str(e))
    except Exception as e:  # noqa: BLE001 — e.g. unknown scenario from the mock; report, don't crash the runtime
        return _error("failed", f"{type(e).__name__}: {e}")
    return _error("bad_request", "expected one of: case, request, approve, reject, status, scenario")


def create_app(service: CaseService, demo=None) -> BedrockAgentCoreApp:
    app = BedrockAgentCoreApp()
    lock = threading.Lock()

    @app.entrypoint
    def invoke(payload):
        return handle_payload(payload, service, demo, lock)

    return app


def main() -> None:
    from synapse.api.main import build_service

    service, demo = build_service()
    create_app(service, demo).run(port=8080)


if __name__ == "__main__":
    main()
