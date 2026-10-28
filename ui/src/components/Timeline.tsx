import { useEffect, useRef, useState } from "react";
import { inlineBold } from "../inline";
import type { TraceEvent } from "../types";

function label(e: TraceEvent): string {
  if (e.kind === "TOOL_CALL") return `Calls ${e.title}`;
  if (e.kind === "TOOL_RESULT") return `${e.title} returned`;
  return e.title;
}

/** "Agent Trace": one row per event (kind, what happened, time since start); a row opens its raw detail. */
export function Timeline({ events, live }: { events: TraceEvent[]; live: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (live) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [events.length, live]);
  const t0 = events.length ? Date.parse(events[0].ts) : 0;

  return (
    <section className="panel" aria-labelledby="trace-title">
      <div className="panel-text">
        <h2 className="panel-title" id="trace-title">
          Agent Trace {live && <span className="live-dot" aria-label="live">● live</span>}
        </h2>
      </div>
      <ol className="inset timeline">
        {events.length === 0 && (
          <li className="ev-empty">No events yet. Each step the agent takes streams here as it happens.</li>
        )}
        {events.map((e) => (
          <li key={e.seq} className={`ev ev-${e.kind.toLowerCase()}`}>
            <button className="ev-row" onClick={() => setOpen(open === e.seq ? null : e.seq)}
                    aria-expanded={open === e.seq}>
              <span className="ev-kind">{e.kind.replace("_", " ")}</span>
              <span className="ev-body">
                <span className="ev-title">{label(e)}</span>
                {e.kind === "REASONING" && <span className="ev-text">{inlineBold(String(e.detail.text ?? ""))}</span>}
              </span>
              <span className="ev-time">+{((Date.parse(e.ts) - t0) / 1000).toFixed(1)}s</span>
            </button>
            {open === e.seq && <pre className="ev-detail">{JSON.stringify(e.detail, null, 2)}</pre>}
          </li>
        ))}
        <li ref={end} aria-hidden />
      </ol>
    </section>
  );
}
