import { useEffect, useRef, useState } from "react";
import { plainText } from "../plainText";
import { ModelText } from "./ModelText";
import type { TraceEvent } from "../types";

function label(e: TraceEvent): string {
  if (e.kind === "TOOL_CALL") return `Calls ${e.title}`;
  if (e.kind === "TOOL_RESULT") return `${e.title} returned`;
  return plainText(e.title);
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
          Agent Trace {live && <span className="live-dot">Live</span>}
        </h2>
      </div>
      <ol className="inset timeline">
        {events.length === 0 && (
          <li className="ev-empty">No events yet. Each step the agent takes streams here as it happens.</li>
        )}
        {events.map((e) => (
          <li key={e.seq} className={`ev ev-${e.kind.toLowerCase()}`}>
            {/* A div with button semantics: the reasoning text holds paragraphs and lists, which a
                <button> may not contain. */}
            <div className="ev-row" role="button" tabIndex={0} aria-expanded={open === e.seq}
                 onClick={() => setOpen(open === e.seq ? null : e.seq)}
                 onKeyDown={(k) => {
                   if (k.key === "Enter" || k.key === " ") { k.preventDefault(); setOpen(open === e.seq ? null : e.seq); }
                 }}>
              <span className="ev-kind">{e.kind.replace("_", " ")}</span>
              <div className="ev-body">
                {/* Reasoning events are all titled "Agent"; the text says what the agent thought. */}
                {!(e.kind === "REASONING" && e.title === "Agent") && <span className="ev-title">{label(e)}</span>}
                {e.kind === "REASONING" && <ModelText className="ev-text" text={String(e.detail.text ?? "")} />}
              </div>
              <span className="ev-time">+{((Date.parse(e.ts) - t0) / 1000).toFixed(1)}s</span>
            </div>
            {open === e.seq && <pre className="ev-detail">{JSON.stringify(e.detail, null, 2)}</pre>}
          </li>
        ))}
        <li ref={end} aria-hidden />
      </ol>
    </section>
  );
}
