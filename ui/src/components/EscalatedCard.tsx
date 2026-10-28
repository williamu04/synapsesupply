import { approverRow, cardSummary, caseTitle, statusPill } from "../caseSummary";
import type { CaseRecord } from "../types";
import { CaseStats } from "./CaseStats";
import { EscalationBox } from "./EscalationBox";

/** A case Cedar escalated to a planner or denied (Escalations page). The whole card opens the case. */
export function EscalatedCard({ record, onOpen }: { record: CaseRecord; onOpen: (caseId: string) => void }) {
  const row = approverRow(record);
  return (
    <article className="panel escalated-card">
      <div className="escalated-main">
        <div className="issue-text">
          <h2 className="panel-title"><button className="card-link" onClick={() => onOpen(record.case_id)}>
            {caseTitle(record)}
          </button></h2>
          <p className="clamp-2">{cardSummary(record)}</p>
        </div>
        <CaseStats record={record} />
      </div>
      <aside className="escalated-aside">
        {record.policy && (
          <EscalationBox effect={record.policy.effect} reasons={record.policy.reasons} pill={statusPill(record)} />
        )}
        {row && (
          <div className="approvers">
            <p className="muted">Requiring Approval</p>
            <p className="approver"><span>{row.who}</span> <strong>{row.role}</strong></p>
          </div>
        )}
      </aside>
    </article>
  );
}
