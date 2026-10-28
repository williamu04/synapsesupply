import { automatedNote, caseTitle } from "../caseSummary";
import { inlineBold } from "../inline";
import type { CaseRecord } from "../types";
import { CaseStats } from "./CaseStats";

/** A case the agent handled on its own (Automated page). The title opens the case. */
export function IssueCard({ record, onOpen }: { record: CaseRecord; onOpen: (caseId: string) => void }) {
  return (
    <article className="panel issue-card">
      <div className="issue-text">
        <h2 className="panel-title"><button className="card-link" onClick={() => onOpen(record.case_id)}>
          {caseTitle(record)}
        </button></h2>
        {record.summary && <p className="clamp-2">{inlineBold(record.summary)}</p>}
        <p className="muted">{automatedNote(record)}</p>
      </div>
      <CaseStats record={record} />
    </article>
  );
}
