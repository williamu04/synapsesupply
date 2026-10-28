// "Plan": ask the agent in plain language (the same /requests path SAP Joule uses), plus the demo
// controls the stage script relies on: trigger a scenario, replay a recorded run, reset.
import { useRef, useState, type FormEvent } from "react";
import type { Scenario } from "../types";

// Requests tested against the live system: DENY (Siak), ESCALATE (Kampar, over $5,000), options only.
const TEMPLATES = [
  "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood, they're the cheapest.",
  "Order 3,620 TO of WC-ACACIA from Kampar Timber Cooperative for plant 1100.",
  "What suppliers can deliver WC-ACACIA to plant 1100?",
];

export function PlanPage({ onAsk, demo, scenarios, onRunScenario, recordings, onReplay, onReset, error }: {
  onAsk: (utterance: string) => Promise<void>;
  demo: boolean;
  scenarios: Scenario[];
  onRunScenario: (id: string) => void;
  recordings: string[];
  onReplay: (name: string) => void;
  onReset: () => void;
  error: string | null;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    try { await onAsk(text.trim()); } finally { setBusy(false); }
  }

  return (
    <div className="plan">
      <h1 className="wordmark plan-title"><strong>SynapseSupply</strong> Console</h1>
      <div className="plan-body">
        <form className="ask" onSubmit={submit}>
          <input ref={input} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask SynapseSupply"
                 aria-label="Ask SynapseSupply" />
          <button type="submit" className="ask-send" disabled={!text.trim() || busy} aria-label="Send request">
            <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden><path d="M4 12l16-8-6 16-2-7-8-1z" /></svg>
          </button>
        </form>
        {error && <p className="error-text plan-error" role="alert">{error}</p>}
        <ul className="templates" aria-label="Example requests">
          {TEMPLATES.map((t) => (
            <li key={t}>
              <button className="template" onClick={() => { setText(t); input.current?.focus(); }}>{t}</button>
            </li>
          ))}
        </ul>

        {(demo || recordings.length > 0) && (
          <div className="demo-controls">
            {demo && scenarios.length > 0 && (
              <section>
                <h2 className="nav-heading">Simulate a disruption</h2>
                <ul className="templates">
                  {scenarios.map((s) => (
                    <li key={s.scenario_id}>
                      <button className="template" onClick={() => onRunScenario(s.scenario_id)}>
                        <strong>{s.scenario_id}</strong> {s.title}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {recordings.length > 0 && (
              <section>
                <h2 className="nav-heading">Replay a recorded run</h2>
                <ul className="templates">
                  {recordings.map((name) => (
                    <li key={name}><button className="template" onClick={() => onReplay(name)}>{name}</button></li>
                  ))}
                </ul>
              </section>
            )}
            {demo && <button className="btn btn-outlined" onClick={onReset}>Reset demo</button>}
          </div>
        )}
      </div>
    </div>
  );
}
