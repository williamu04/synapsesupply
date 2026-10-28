// One case as the design's report: overview, decision (approval / plan / Cedar), stock chart, sourcing
// options and the live agent trace. Also renders replays, which have a trace but no case record.
import { approverRow, caseTitle, statusPill } from "../caseSummary";
import { timeToDecision, type CaseView } from "../caseView";
import { ApprovalCard } from "../components/ApprovalCard";
import { CaseStats } from "../components/CaseStats";
import { EscalationBox } from "../components/EscalationBox";
import { OptionsTable } from "../components/OptionsTable";
import { PlanCard } from "../components/PlanCard";
import { PolicyCard } from "../components/PolicyCard";
import { ProjectionChart } from "../components/ProjectionChart";
import { Stats, type Stat } from "../components/Stats";
import { PendingPanel } from "../components/PendingPanel";
import { Timeline } from "../components/Timeline";
import { fmtDuration } from "../format";
import { inlineBold } from "../inline";
import { FINAL_STATUSES, type CaseRecord, type TraceEvent } from "../types";

const MANUAL_BASELINE_MIN = 150; // industry estimate of manual handling time per incident (pitch, source [2])

/** The headline the trace gives us: the late supplier, or the buyer's own words. */
function headline(view: CaseView): string | null {
  const d = view.details;
  if (d?.supplier_name) {
    const days = Number(d.delay_days);
    return `${String(d.supplier_name)}: delivery ${days} ${days === 1 ? "day" : "days"} late`;
  }
  return d?.utterance ? `“${String(d.utterance)}”` : null;
}

export function CaseDetail({ label, replay, record, view, events, status, streaming, onApprove, onReject }: {
  /** Case id, or "Recording: <name>" for a replay. */
  label: string;
  replay: boolean;
  record: CaseRecord | null;
  view: CaseView;
  events: TraceEvent[];
  status: string;
  streaming: boolean;
  onApprove: (approver: string) => Promise<void>;
  onReject: (approver: string, reason: string) => Promise<void>;
}) {
  const ttd = timeToDecision(view);
  const finished = FINAL_STATUSES.has(status) || status === "AWAITING_APPROVAL";
  const sapDocument = record?.sap_document ?? view.sapDocument;
  const approver = record?.approver ?? (view.approval?.outcome === "APPROVED" ? view.approval.approver : null);
  const pill = statusPill({ status: status as CaseRecord["status"], approver });
  const extra: Stat[] = [
    { label: "Time to decision", value: ttd === null ? "–" : fmtDuration(ttd), sub: `vs ~${MANUAL_BASELINE_MIN} min manual` },
    ...(sapDocument ? [{ label: "S/4 Document", value: sapDocument }] : []),
  ];

  return (
    <div className="card-list">
      <section className="panel overview" aria-labelledby="case-title">
        <div className="overview-main">
          <div className="issue-text">
            <p className="muted small">{label}{view.details && ` · ${String(view.details.process_type)}`}</p>
            <h1 className="panel-title" id="case-title">
              {headline(view) ?? (record ? caseTitle(record) : replay ? "Loading the recorded run…" : "Waiting for the agent…")}
            </h1>
            {Boolean(view.details?.carrier_notice) && (
              <p><strong>Carrier notice:</strong> {String(view.details?.carrier_notice)}</p>
            )}
            {view.summary && <p>{inlineBold(view.summary)}</p>}
            <div className="chips">
              {view.modelFallback && <span className="chip warn">Model unavailable: autopilot</span>}
              {view.degraded && <span className="chip warn">S/4 unreachable: mock ERP fallback</span>}
              {streaming && <span className="live-dot">● live</span>}
            </div>
          </div>
          {record ? <CaseStats record={record} extra={extra} />
            : <Stats items={[{ label: "Status", value: pill.label }, ...extra]} />}
        </div>
        {view.policy && (
          <aside className="overview-aside">
            <EscalationBox effect={view.policy.effect} reasons={view.policy.reasons} pill={pill} />
          </aside>
        )}
      </section>

      {view.policy ? (
        <section className="panel decision-row" aria-label="Decision">
          <ApprovalCard row={approverRow({ status: status as CaseRecord["status"], approver, policy: view.policy })}
                        awaiting={record?.status === "AWAITING_APPROVAL"} reason={view.approval?.reason}
                        onApprove={onApprove} onReject={onReject} />
          <PlanCard planner={view.planner} policy={view.policy} />
          <PolicyCard policy={view.policy} />
        </section>
      ) : finished ? (
        <section className="panel"><p className="muted closed-note">
          {status === "FAILED"
            ? "No decision: the agent stopped before submitting a plan. The agent trace shows where."
            : "No decision: the agent closed this case without proposing an action, so Cedar had nothing to judge."}
        </p></section>
      ) : <PendingPanel title="Decision" shape="cards"
                        caption="Cedar decides once the agent submits a plan; a planner approves anything risky." />}

      {view.analysis ? <ProjectionChart analysis={view.analysis} />
        : !finished && <PendingPanel title="Stock projection" shape="chart"
                                     caption="Waiting for the stock analysis from SAP S/4HANA." />}

      {view.sourcing && (
        <OptionsTable sourcing={view.sourcing} chosen={view.policy?.option_id ?? null}
                      effect={view.policy?.effect ?? null}
                      approved={view.approval?.outcome === "APPROVED"}
                      rejected={view.rejected}
                      unit={view.analysis?.unit ?? ""} />
      )}
      <Timeline events={events} live={streaming} />
    </div>
  );
}
