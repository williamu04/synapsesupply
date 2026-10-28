import { approverRow, caseTitle, statusPill } from "../caseSummary";
import { inlineBold } from "../inline";
import type { CaseRecord } from "../types";
import { CaseStats } from "./CaseStats";
import { EscalationBox } from "./EscalationBox";

/** A case Cedar escalated to a planner or denied (Escalations page). The title opens the case. */
export function EscalatedCard({ record, onOpen }: { record: CaseRecord; onOpen: (caseId: string) => void }) {
  const row = approverRow(record);
  return (
    <article className="panel escalated-card">
      <div className="escalated-main">
        <div className="issue-text">
          <h2 className="panel-title"><button className="card-link" onClick={() => onOpen(record.case_id)}>
            {caseTitle(record)}
          </button></h2>
          {record.summary && <p className="clamp-2">{inlineBold(record.summary)}</p>}
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
