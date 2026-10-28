import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, streamEvents } from "./api";
import { lane } from "./caseSummary";
import { deriveView, mergeEvent, pickInitialCase } from "./caseView";
import { Header } from "./components/Header";
import { Sidebar, type Page } from "./components/Sidebar";
import { EmptyState } from "./components/EmptyState";
import { CaseDetail } from "./pages/CaseDetail";
import { CaseListPage } from "./pages/CaseListPage";
import { PlanPage } from "./pages/PlanPage";
import { StatisticsPage } from "./pages/StatisticsPage";
import { parseRoute, routeQuery, streamKey, type Route } from "./route";
import { applyTheme, followSystem, loadTheme, saveTheme, type ThemePref } from "./theme";
import { FINAL_STATUSES, type CaseRecord, type Scenario, type TraceEvent } from "./types";

const isFinalDone = (e: TraceEvent) => e.kind === "DONE" && FINAL_STATUSES.has(e.title);

export default function App() {
  const [demo, setDemo] = useState(false);
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [recordings, setRecordings] = useState<string[]>([]);
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.search) ?? { page: "plan" });
  const autoOpened = useRef(parseRoute(window.location.search) !== null);  // a link counts as the user's choice
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [record, setRecord] = useState<CaseRecord | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missingCase, setMissingCase] = useState<string | null>(null);
  const [theme, setTheme] = useState<ThemePref>(loadTheme);

  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
    return theme.mode === "system" ? followSystem(theme) : undefined;
  }, [theme]);

  const navigate = useCallback((next: Route, replace = false) => {
    setRoute(next);
    const url = window.location.pathname + routeQuery(next);
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.search) ?? { page: "plan" });
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const refreshCases = useCallback(() => {
    api.cases().then((list) => {
      setCases(list);
      // Open on the case that matters (waiting for approval, else the newest) the first time cases
      // are seen, so the console never greets the jury with an empty page.
      if (!autoOpened.current) {
        const id = pickInitialCase(list);
        if (id) {
          autoOpened.current = true;
          navigate({ page: "case", caseId: id }, true);
        }
      }
    }).catch(() => undefined);
  }, [navigate]);

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
    api.getCase(caseId).then((r) => setRecord("created_at" in r ? r : null)).catch((e) => {
      if (e instanceof ApiError && e.status === 404) setMissingCase(caseId);
    });
  }, []);

  // One stream per case or replay; live streams also refresh the case record when a DONE arrives.
  // A case the API does not know (e.g. cleared by Reset demo) gets no stream: it would never end.
  const stream = streamKey(route);
  const missing = route.page === "case" && missingCase === route.caseId;
  useEffect(() => {
    setEvents([]);
    setRecord(null);
    setStreaming(false);
    if ((route.page !== "case" && route.page !== "replay") || missing) return;
    setStreaming(true);
    if (route.page === "case") {
      const { caseId } = route;
      loadRecord(caseId);
      return streamEvents(`/cases/${caseId}/events`, (e) => {
        setEvents((prev) => mergeEvent(prev, e));
        if (e.kind === "DONE") {
          loadRecord(caseId);
          refreshCases();
        }
      }, isFinalDone, () => setStreaming(false));
    }
    return streamEvents(`/recordings/${route.name}?speed=${route.speed}`,
      (e) => setEvents((prev) => mergeEvent(prev, e)), () => false, () => setStreaming(false), true);
    // Keyed on `stream`, not `route`: navigating between pages must not restart a case's stream.
  }, [stream, missing, loadRecord, refreshCases]);

  const view = useMemo(() => deriveView(events), [events]);
  const status = record?.status ?? view.doneTitle ?? (events.length ? "ANALYZING" : "NEW");
  const newestFirst = useMemo(
    () => [...cases].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)), [cases]);
  const approvals = newestFirst.filter((c) => c.status === "AWAITING_APPROVAL");

  async function guarded(fn: () => Promise<void>) {
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); }
  }
  const openCase = (caseId: string) => navigate({ page: "case", caseId });
  const toPlan = () => navigate({ page: "plan" });
  const runScenario = (id: string) => guarded(async () => {
    const { case_id } = await api.runScenario(id);
    openCase(case_id);
    refreshCases();
  });
  const ask = (utterance: string) => guarded(async () => {
    const { case_id } = await api.request(utterance, "console");
    openCase(case_id);
  });
  const reset = () => guarded(async () => {
    await api.reset();
    navigate({ page: "plan" });
    refreshCases();
  });
  // A decided case resumes streaming (APPROVAL, ACTION, DONE) on the open connection.
  const decide = async (fn: () => Promise<CaseRecord>) => {
    setRecord(await fn());
    refreshCases();
  };

  // A case highlights the lane it belongs to, as in the design's Escalations detail.
  const policyLane = record ? lane(record) : view.policy ? lane({ policy: view.policy, approver: null }) : null;
  const activeNav: Page | null = route.page === "case"
    ? (policyLane === "escalation" ? "escalations" : policyLane ? "automated" : null)
    : route.page === "replay" ? null : route.page;

  return (
    <div className="shell">
      <Sidebar active={activeNav} onNavigate={(page) => navigate({ page })} approvals={approvals}
               openCaseId={route.page === "case" ? route.caseId : null} onOpenCase={openCase}
               theme={theme} onThemeChange={setTheme} />
      <div className="content">
        {route.page !== "plan" && (
          <Header>
            {apiUp === false && <span className="chip error">API unreachable</span>}
            {apiUp && <span className="chip">{demo ? "Demo · mock S/4" : "Connected to S/4"}</span>}
            {route.page === "replay" && <span className="chip warn">⏵ Replay</span>}
          </Header>
        )}
        {error && route.page !== "plan" && <p className="error-banner" role="alert">{error}</p>}
        <main className="page">
          {route.page === "plan" && (
            <PlanPage onAsk={ask} demo={demo} scenarios={scenarios} onRunScenario={runScenario}
                      recordings={recordings} onReplay={(name) => navigate({ page: "replay", name, speed: 2 })}
                      onReset={reset} error={apiUp === false ? "API unreachable" : error} />
          )}
          {route.page === "automated" && (
            <CaseListPage kind="automated" cases={newestFirst} onOpen={openCase} onPlan={toPlan} />
          )}
          {route.page === "escalations" && (
            <CaseListPage kind="escalation" cases={newestFirst} onOpen={openCase} onPlan={toPlan} />
          )}
          {route.page === "statistics" && <StatisticsPage cases={cases} onPlan={toPlan} />}
          {route.page === "case" && missing && (
            <EmptyState title="Case not found" action={{ label: "Go to Plan", onClick: toPlan }}>
              The API holds no case {route.caseId}. Reset demo clears every case, so a link from before a reset
              no longer opens.
            </EmptyState>
          )}
          {(route.page === "case" && !missing || route.page === "replay") && (
            <CaseDetail label={route.page === "case" ? route.caseId : `Recording: ${route.name}`}
                        replay={route.page === "replay"}
                        record={record} view={view} events={events} status={status} streaming={streaming}
                        onApprove={(who) => decide(() => api.approve(record!.case_id, who))}
                        onReject={(who, why) => decide(() => api.reject(record!.case_id, who, why))} />
          )}
        </main>
      </div>
    </div>
  );
}
