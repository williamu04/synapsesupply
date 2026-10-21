"""Turning demo scenarios and free-text requests into case messages (shared by the CLI and the API)."""
from datetime import UTC, datetime

from synapse.contracts import CaseMessage, PayloadSource, ProcessType, make_case_id


def new_request_case_id(now: datetime | None = None) -> str:
    """`REQ` + timestamp to 1/100 ms: unique per request, fits the 20-character document limit."""
    now = now or datetime.now(UTC)
    return make_case_id(f"REQ{now:%y%m%d%H%M%S}{now.microsecond // 10:05d}"[:20], 1)


def scenario_message(scenario: dict, now: datetime | None = None) -> CaseMessage:
    now = now or datetime.now(UTC)
    raw = {k: scenario[k] for k in ("scenario_id", "title", "plant", "material", "carrier_notice", "utterance")
           if scenario.get(k)}
    return CaseMessage(case_id=scenario["case_id"] or new_request_case_id(now), process_type=scenario["process_type"],
                       payload_source=scenario["payload_source"], timestamp=now, raw_payload=raw)


def request_message(utterance: str, user: str | None = None, now: datetime | None = None) -> CaseMessage:
    now = now or datetime.now(UTC)
    raw = {"utterance": utterance} | ({"requested_by": user} if user else {})
    return CaseMessage(case_id=new_request_case_id(now), process_type=ProcessType.USER_REQUEST,
                       payload_source=PayloadSource.JOULE_A2A, timestamp=now, raw_payload=raw)
