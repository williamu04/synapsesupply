// Statistics: headline numbers over the cases the API currently holds (a demo reset clears them).
// A handful of counts is a KPI row, not a chart: one hero figure, then stat tiles.
import { lane } from "../caseSummary";
import { EmptyState } from "../components/EmptyState";
import { StatTile } from "../components/StatTile";
import { fmtUsdCode } from "../format";
import type { CaseRecord } from "../types";

export function StatisticsPage({ cases, onPlan }: { cases: CaseRecord[]; onPlan: () => void }) {
  if (cases.length === 0) {
    return (
      <EmptyState title="No cases yet" action={{ label: "Go to Plan", onClick: onPlan }}>
        Statistics count the cases the API currently holds. Simulate a disruption or ask the agent to start one.
      </EmptyState>
    );
  }
  const count = (pred: (c: CaseRecord) => boolean) => cases.filter(pred).length;
  const autonomous = count((c) => lane(c) === "automated" && c.status === "EXECUTED");
  const decided = count((c) => c.policy !== null);
  const rate = decided ? Math.round((autonomous / decided) * 100) : null;
  const executedUsd = cases.filter((c) => c.status === "EXECUTED")
    .reduce((sum, c) => sum + (c.proposal?.financial_impact_usd ?? 0), 0);

  return (
    <div className="card-list">
      <section className="panel" aria-labelledby="decisions-title">
        <div className="panel-text">
          <h2 className="panel-title" id="decisions-title">Decisions</h2>
          <p>How Cedar routed the {cases.length} {cases.length === 1 ? "case" : "cases"} the API holds. Reset demo clears them.</p>
        </div>
        <div className="stats-hero-row">
          <div className="hero-figure">
            <span className="hero-value">{rate === null ? "–" : `${rate}%`}</span>
            <span className="tile-label">decided without a human</span>
            <span className="tile-sub">{autonomous} of {decided} decided {decided === 1 ? "case" : "cases"}</span>
          </div>
          <div className="tile-grid">
            <StatTile label="Handled autonomously" value={autonomous} sub="Cedar ALLOW" />
            <StatTile label="Escalated to a planner" value={count((c) => c.policy?.effect === "ESCALATE" || c.approver !== null)}
                      sub="Cedar ESCALATE" />
            <StatTile label="Denied for everyone" value={count((c) => c.policy?.effect === "DENY")} sub="Cedar DENY" />
            <StatTile label="No action needed" value={count((c) => c.status === "NO_ACTION_NEEDED")} />
          </div>
        </div>
      </section>
      <section className="panel" aria-labelledby="outcomes-title">
        <div className="panel-text">
          <h2 className="panel-title" id="outcomes-title">Outcomes in SAP S/4HANA</h2>
          <p>What the agent and the planners wrote back to the ERP.</p>
        </div>
        <div className="tile-grid">
          <StatTile label="S/4 documents created" value={count((c) => c.sap_document !== null)} />
          <StatTile label="Approved by a planner" value={count((c) => c.status === "EXECUTED" && c.approver !== null)} />
          <StatTile label="Awaiting approval" value={count((c) => c.status === "AWAITING_APPROVAL")} />
          <StatTile label="Executed cost" value={fmtUsdCode(executedUsd)} sub="incremental, executed cases" />
        </div>
      </section>
    </div>
  );
}
