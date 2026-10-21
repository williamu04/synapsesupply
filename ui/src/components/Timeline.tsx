import { useEffect, useRef, useState } from "react";
import type { TraceEvent } from "../types";

const ICON: Record<string, string> = {
  PLAN: "◎", TOOL_CALL: "→", TOOL_RESULT: "←", REASONING: "✎", POLICY: "⚖", APPROVAL: "⚑", ACTION: "✓",
  ERROR: "!", DONE: "■",
};

function label(e: TraceEvent): string {
  if (e.kind === "TOOL_CALL") return `Calls ${e.title}`;
  if (e.kind === "TOOL_RESULT") return `${e.title} returned`;
  return e.title;
}

export function Timeline({ events, live }: { events: TraceEvent[]; live: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (live) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [events.length, live]);
  const t0 = events.length ? Date.parse(events[0].ts) : 0;

  return (
    <section className="card" aria-labelledby="trace-title">
      <h3 id="trace-title">Agent trace {live && <span className="live-dot" aria-label="live">● live</span>}</h3>
      <ol className="timeline">
        {events.map((e) => (
          <li key={e.seq} className={`ev ev-${e.kind.toLowerCase()}`}>
            <button className="ev-row" onClick={() => setOpen(open === e.seq ? null : e.seq)}
                    aria-expanded={open === e.seq}>
              <span className="ev-icon" aria-hidden>{ICON[e.kind]}</span>
              <span className="ev-kind">{e.kind.replace("_", " ")}</span>
              <span className="ev-title">{label(e)}</span>
              <span className="ev-time muted">+{((Date.parse(e.ts) - t0) / 1000).toFixed(2)} s</span>
            </button>
            {e.kind === "REASONING" && <p className="ev-text">{String(e.detail.text ?? "")}</p>}
            {open === e.seq && <pre className="ev-detail">{JSON.stringify(e.detail, null, 2)}</pre>}
          </li>
        ))}
        <li ref={end} aria-hidden />
      </ol>
    </section>
  );
}
