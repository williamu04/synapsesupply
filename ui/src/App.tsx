import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, streamEvents } from "./api";
import { deriveView, mergeEvent, pickInitialCase, timeToDecision } from "./caseView";
import { DecisionCard } from "./components/DecisionCard";
import { OptionsTable } from "./components/OptionsTable";
import { ProjectionChart } from "./components/ProjectionChart";
import { Timeline } from "./components/Timeline";
import { fmtDuration } from "./format";
import { inlineBold } from "./inline";
import { FINAL_STATUSES, type CaseRecord, type Scenario, type TraceEvent } from "./types";

type Selection = { mode: "live"; caseId: string } | { mode: "replay"; name: string; speed: number } | null;

const MANUAL_BASELINE_MIN = 150; // average manual handling time per logistics incident (pitch, source [2])

const STATUS: Record<string, [string, string, string]> = {
  EXECUTED: ["good", "✓", "Executed"],
  NO_ACTION_NEEDED: ["good", "✓", "No action needed"],
  AWAITING_APPROVAL: ["warning", "⚑", "Awaiting approval"],
  BLOCKED: ["critical", "⛔", "Blocked"],
  FAILED: ["critical", "!", "Failed"],
  REJECTED: ["neutral", "✗", "Rejected"],
  ANALYZING: ["neutral", "…", "Analyzing"],
  NEW: ["neutral", "…", "Queued"],
};

function StatusBadge({ status }: { status: string }) {
  const [cls, icon, label] = STATUS[status] ?? ["neutral", "•", status];
  return <span className={`badge ${cls}`}><span aria-hidden>{icon}</span> {label}</span>;
}

const isFinalDone = (e: TraceEvent) => e.kind === "DONE" && FINAL_STATUSES.has(e.title);

/** Deep links: ?case=<case_id> opens a live case (e.g. from the Joule approval card), ?replay=<name> a recording. */
function initialSelection(): Selection {
  const q = new URLSearchParams(window.location.search);
  const caseId = q.get("case");
  if (caseId) return { mode: "live", caseId };
  const replay = q.get("replay");
  if (replay) return { mode: "replay", name: replay, speed: Number(q.get("speed")) || 2 };
  return null;
}

export default function App() {
  const [demo, setDemo] = useState(false);
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [recordings, setRecordings] = useState<string[]>([]);
  const [selection, setSelection] = useState<Selection>(initialSelection);
  const autoOpened = useRef(selection !== null);  // a deep link counts as the user's choice
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [record, setRecord] = useState<CaseRecord | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [utterance, setUtterance] = useState(
    "Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood, they're the cheapest.");
  const [error, setError] = useState<string | null>(null);

  const refreshCases = useCallback(() => {
    api.cases().then((list) => {
      setCases(list);
      // Open on the case that matters (waiting for approval, else the newest) the first time
      // cases are seen, so the console never greets the jury with an empty page.
      if (!autoOpened.current) {
        const id = pickInitialCase(list);
        if (id) {
          autoOpened.current = true;
          setSelection({ mode: "live", caseId: id });
        }
      }
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.health().then((h) => {
      setApiUp(true);
      setDemo(h.demo);
      if (h.demo) api.scenarios().then(setScenarios).catch(() => undefined);
    }).catch(() => setApiUp(false));
    api.recordings().then(setRecordings).catch(() => undefined);
    refreshCases();
    const timer = window.setInterval(refreshCases, 3000);
    return () => window.clearInterval(timer);
  }, [refreshCases]);

  const loadRecord = useCallback((caseId: string) => {
    api.getCase(caseId).then((r) => setRecord("created_at" in r ? r : null)).catch(() => undefined);
  }, []);

  // One stream per selection; live streams also refresh the case record when a DONE arrives.
  useEffect(() => {
    setEvents([]);
    setRecord(null);
    if (!selection) return;
    setStreaming(true);
    if (selection.mode === "live") {
      loadRecord(selection.caseId);
      return streamEvents(`/cases/${selection.caseId}/events`, (e) => {
        setEvents((prev) => mergeEvent(prev, e));
        if (e.kind === "DONE") {
          loadRecord(selection.caseId);
          refreshCases();
        }
      }, isFinalDone, () => setStreaming(false));
    }
    return streamEvents(`/recordings/${selection.name}?speed=${selection.speed}`,
      (e) => setEvents((prev) => mergeEvent(prev, e)), () => false, () => setStreaming(false), true);
  }, [selection, loadRecord, refreshCases]);

  const view = useMemo(() => deriveView(events), [events]);
  const status = record?.status ?? view.doneTitle ?? (events.length ? "ANALYZING" : "NEW");
  const ttd = timeToDecision(view);

  async function guarded(fn: () => Promise<void>) {
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); }
  }
  const runScenario = (id: string) => guarded(async () => {
    const { case_id } = await api.runScenario(id);
    setSelection({ mode: "live", caseId: case_id });
    refreshCases();
  });
  const sendRequest = () => guarded(async () => {
    const { case_id } = await api.request(utterance, "console");
    setSelection({ mode: "live", caseId: case_id });
  });
  const reset = () => guarded(async () => {
    await api.reset();
    setSelection(null);
    refreshCases();
  });
  const decide = (fn: () => Promise<CaseRecord>) => async () => {
    const updated = await fn();
    setRecord(updated);
    refreshCases();
    // A decided case resumes streaming (APPROVAL, ACTION, DONE) on the open connection.
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>◈</span>
          <div>
            <strong>SynapseSupply</strong>
            <span className="muted small">Fibre supply exception console</span>
          </div>
        </div>
        <div className="topbar-right">
          {apiUp === false && <span className="badge critical">! API unreachable</span>}
          {apiUp && <span className="badge neutral">{demo ? "Demo · mock S/4" : "Connected to S/4"}</span>}
          {selection?.mode === "replay" && <span className="badge warning">⏵ Replay</span>}
          {demo && <button onClick={reset}>Reset demo</button>}
        </div>
      </header>

      <aside className="sidebar">
        {demo && (
          <section>
            <h2>Trigger a disruption</h2>
            {scenarios.map((s) => (
              <button key={s.scenario_id} className="scenario" onClick={() => runScenario(s.scenario_id)}>
                <span className="scenario-id">{s.scenario_id}</span>
                <span>{s.title}</span>
              </button>
            ))}
          </section>
        )}

        <section>
          <h2>Ask like Joule</h2>
          <textarea value={utterance} onChange={(e) => setUtterance(e.target.value)} rows={4}
                    aria-label="Request to the agent" />
          <button className="primary" disabled={!utterance.trim()} onClick={sendRequest}>Send request</button>
        </section>

        <section>
          <h2>Cases</h2>
          {cases.length === 0 && <p className="muted small">No cases yet.</p>}
          <ul className="case-list">
            {[...cases].reverse().map((c) => (
              <li key={c.case_id}>
                <button className={selection?.mode === "live" && selection.caseId === c.case_id ? "active" : ""}
                        onClick={() => setSelection({ mode: "live", caseId: c.case_id })}>
                  <span className="case-id">{c.case_id}</span>
                  <StatusBadge status={c.status} />
                </button>
              </li>
            ))}
          </ul>
        </section>

        {recordings.length > 0 && (
          <section>
            <h2>Replay a recorded run</h2>
            <p className="muted small">Fallback if the network or model is slow on stage.</p>
            {recordings.map((name) => (
              <button key={name} className="link-row" onClick={() => setSelection({ mode: "replay", name, speed: 2 })}>
                ⏵ {name}
              </button>
            ))}
          </section>
        )}
        {error && <p className="status critical" role="alert">✗ {error}</p>}
      </aside>

      <main className="main">
        {!selection && (
          <div className="empty">
            <h1>When wood fibre is late, the agent rebalances supply — compliantly.</h1>
            <p className="muted">
              Trigger a disruption on the left. The agent reads SAP S/4HANA, projects stock against safety stock,
              compares every option, runs the EUDR compliance gate, and lets Cedar decide whether it may act alone.
            </p>
          </div>
        )}

        {selection && (
          <>
            <section className="case-head">
              <div>
                <p className="muted small">
                  {selection.mode === "live" ? selection.caseId : `Recording: ${selection.name}`}
                  {view.details && ` · ${String(view.details.process_type)}`}
                </p>
                <h1>
                  {view.details?.supplier_name
                    ? `${String(view.details.supplier_name)}: delivery ${Number(view.details.delay_days)} ${
                      Number(view.details.delay_days) === 1 ? "day" : "days"} late`
                    : view.details?.utterance ? `“${String(view.details.utterance)}”` : "Case"}
                </h1>
                <div className="chips">
                  <StatusBadge status={status} />
                  {view.planner && (
                    <span className="badge neutral">{view.planner === "llm" ? "Planner: Claude" : "Planner: autopilot"}</span>
                  )}
                  {view.degraded && <span className="badge warning">⚠ S/4 unreachable — mock ERP fallback</span>}
                  {view.modelFallback && <span className="badge warning">⚠ Model unavailable — autopilot</span>}
                  {streaming && <span className="live-dot">● live</span>}
                </div>
              </div>
              <div className="kpi">
                <span className="muted small">Time to decision</span>
                <span className="hero">{ttd === null ? "—" : fmtDuration(ttd)}</span>
                <span className="muted small">vs. ~{MANUAL_BASELINE_MIN} min handled manually</span>
              </div>
            </section>

            {(Boolean(view.summary) || Boolean(view.details?.carrier_notice)) && (
              <section className="card summary">
                {Boolean(view.details?.carrier_notice) && (
                  <p><strong>Carrier notice:</strong> {String(view.details?.carrier_notice)}</p>
                )}
                {view.summary && <p>{inlineBold(view.summary)}</p>}
                {(record?.sap_document ?? view.sapDocument) && (
                  <p className="status good">✓ S/4 document {record?.sap_document ?? view.sapDocument}</p>
                )}
              </section>
            )}

            <div className="grid">
              {view.analysis ? <section className="card"><ProjectionChart analysis={view.analysis} /></section>
                : <section className="card placeholder muted">Waiting for the stock analysis…</section>}
              {view.policy ? (
                <DecisionCard policy={view.policy} approval={view.approval} record={record}
                              onApprove={(who) => decide(() => api.approve(record!.case_id, who))()}
                              onReject={(who, why) => decide(() => api.reject(record!.case_id, who, why))()} />
              ) : <section className="card placeholder muted">No decision yet.</section>}
            </div>

            {view.sourcing && (
              <OptionsTable sourcing={view.sourcing} chosen={view.policy?.option_id ?? null}
                            effect={view.policy?.effect ?? null}
                            approved={view.approval?.outcome === "APPROVED"}
                            rejected={view.rejected}
                            unit={view.analysis?.unit ?? ""} />
            )}
            <Timeline events={events} live={streaming} />
          </>
        )}
      </main>
    </div>
  );
}
