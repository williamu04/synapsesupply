import { lane, type Lane } from "../caseSummary";
import { EmptyState } from "../components/EmptyState";
import { EscalatedCard } from "../components/EscalatedCard";
import { IssueCard } from "../components/IssueCard";
import type { CaseRecord } from "../types";

const EMPTY: Record<Lane, [string, string]> = {
  automated: ["Nothing automated yet",
    "Cases the agent settles alone, within Cedar's limits, land here. SC-02 is one: a one-day delay fixed for $2,150."],
  escalation: ["No escalations",
    "Cases over $5,000, below 0.90 confidence or with a non-compliant supplier land here for a planner. SC-01 is one."],
};

/** Automated or Escalations: the lane's cases, newest first. */
export function CaseListPage({ kind, cases, onOpen, onPlan }: {
  kind: Lane;
  /** Newest first. */
  cases: CaseRecord[];
  onOpen: (caseId: string) => void;
  onPlan: () => void;
}) {
  const shown = cases.filter((c) => lane(c) === kind);
  if (shown.length === 0) {
    const [title, text] = EMPTY[kind];
    return <EmptyState title={title} action={{ label: "Go to Plan", onClick: onPlan }}>{text}</EmptyState>;
  }
  return (
    <div className="card-list">
      {shown.map((c) => kind === "escalation"
        ? <EscalatedCard key={c.case_id} record={c} onOpen={onOpen} />
        : <IssueCard key={c.case_id} record={c} onOpen={onOpen} />)}
    </div>
  );
}
