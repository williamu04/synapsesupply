"""Per-case execution trace: what the UI streams over SSE and what replay mode re-plays."""
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from synapse.contracts import TraceEvent, TraceKind

Sink = Callable[[TraceEvent], None]


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class Tracer:
    def __init__(self, case_id: str, sinks: list[Sink] | None = None, events: list[TraceEvent] | None = None):
        """`events`: the case's earlier events (e.g. from another process), so numbering continues."""
        self.case_id = case_id
        self.events: list[TraceEvent] = list(events or [])
        self.sinks = list(sinks or [])

    def emit(self, kind: TraceKind, title: str, **detail: Any) -> TraceEvent:
        event = TraceEvent(case_id=self.case_id, seq=len(self.events), ts=datetime.now(UTC), kind=kind,
                           title=title, detail=jsonable(detail))
        self.events.append(event)
        for sink in self.sinks:
            sink(event)
        return event


class JsonlRecorder:
    """Appends events to a JSONL file — the recording format for the UI's replay mode."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def __call__(self, event: TraceEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")


def load_recording(path: str | Path) -> list[TraceEvent]:
    return [TraceEvent.model_validate_json(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def format_event(event: TraceEvent) -> str:
    detail = json.dumps(event.detail, default=str)
    if len(detail) > 160:
        detail = detail[:157] + "..."
    return f"[{event.seq:02d}] {event.kind.value:<11} {event.title}  {detail if event.detail else ''}".rstrip()
