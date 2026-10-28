import { actionLabel, sourceLabel, statusPill } from "../caseSummary";
import { fmtDateTime, fmtUsdCode } from "../format";
import type { CaseRecord } from "../types";
import { Stats, type Stat } from "./Stats";

/** The standard stats of a case record; `extra` appends detail-page stats. */
export function CaseStats({ record, extra = [] }: { record: CaseRecord; extra?: Stat[] }) {
  const [date, time] = fmtDateTime(record.created_at);
  const cost = record.proposal?.financial_impact_usd;
  return (
    <Stats items={[
      { label: "Issue ID", value: record.case_id, sub: sourceLabel(record.payload_source) },
      { label: "Date", value: date, sub: time },
      { label: "Affected Object", value: record.material ?? "Not specified", sub: record.plant ? `plant ${record.plant}` : undefined },
      { label: "Estimated Cost", value: cost === undefined ? "None" : fmtUsdCode(cost) },
      { label: "Status", value: statusPill(record).label },
      { label: "Action", value: actionLabel(record) },
      ...extra,
    ]} />
  );
}
