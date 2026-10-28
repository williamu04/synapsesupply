import { automatedNote, cardSummary, caseTitle } from "../caseSummary";
import type { CaseRecord } from "../types";
import { CaseStats } from "./CaseStats";

/** A case the agent handled on its own (Automated page). The whole card opens the case: the title's
 *  button stretches over it, so there is one link per card for keyboards and screen readers. */
export function IssueCard({ record, onOpen }: { record: CaseRecord; onOpen: (caseId: string) => void }) {
  return (
    <article className="panel issue-card">
      <div className="issue-text">
        <h2 className="panel-title"><button className="card-link" onClick={() => onOpen(record.case_id)}>
          {caseTitle(record)}
        </button></h2>
        <p className="clamp-2">{cardSummary(record)}</p>
        <p className="muted">{automatedNote(record)}</p>
      </div>
      <CaseStats record={record} />
    </article>
  );
}
