// How a case record maps onto the console's list cards: which lane it belongs to, its title, its
// status pill and its action. Pure and unit-tested.
import { fmtDay, fmtQty, fmtUsdCode } from "./format";
import { plainText } from "./plainText";
import type { CaseRecord } from "./types";

/** "escalation": Cedar sent it to a human (ESCALATE) or refused it (DENY); everything else ran alone. */
export type Lane = "automated" | "escalation";
export type Tone = "success" | "warning" | "error" | "neutral";
export interface Pill { tone: Tone; label: string }

export function lane(c: Pick<CaseRecord, "policy" | "approver">): Lane {
  // After a planner decides, the record carries Cedar's re-check of the approver (ALLOW), so the
  // recorded approver is what marks the case as escalated.
  return c.approver || (c.policy && c.policy.effect !== "ALLOW") ? "escalation" : "automated";
}

const PROCESS: Record<string, string> = {
  ASN_DELAY: "Late delivery",
  STOCK_BELOW_SAFETY: "Stock below safety stock",
  SUPPLIER_COMPLIANCE_ALERT: "Supplier compliance alert",
  USER_REQUEST: "Buyer request",
};

export function caseTitle(c: Pick<CaseRecord, "process_type" | "material" | "plant">): string {
  const what = PROCESS[c.process_type] ?? c.process_type;
  if (c.material && c.plant) return `${what}: ${c.material} at plant ${c.plant}`;
  return what;
}

const SOURCE: Record<string, string> = {
  // JOULE_A2A covers every chat request: SAP Joule and the console's Plan page share /requests.
  ODATA_POLLER: "From S/4 poller", CARRIER_WEBHOOK: "From carrier", JOULE_A2A: "Chat request", MANUAL: "From console",
};
export const sourceLabel = (source: string): string => SOURCE[source] ?? source;

export function statusPill(c: Pick<CaseRecord, "status" | "approver">): Pill {
  switch (c.status) {
    case "EXECUTED": return { tone: "success", label: c.approver ? "Approved" : "Executed" };
    case "NO_ACTION_NEEDED": return { tone: "success", label: "No action" };
    case "AWAITING_APPROVAL": return { tone: "warning", label: "Pending" };
    case "BLOCKED": return { tone: "error", label: "Blocked" };
    case "REJECTED": return { tone: "error", label: "Rejected" };
    case "FAILED": return { tone: "error", label: "Failed" };
    case "ANALYZING": return { tone: "neutral", label: "Analyzing" };
    default: return { tone: "neutral", label: "Queued" };
  }
}

/** The line under an automated card's summary: why no human was needed (or what is still going on). */
export function automatedNote(c: Pick<CaseRecord, "status">): string {
  switch (c.status) {
    case "EXECUTED": return "Escalation condition not met, human approval not needed";
    case "NO_ACTION_NEEDED": return "No action was needed, so no approval was needed";
    case "FAILED": return "The agent could not finish this case; see the agent trace";
    default: return "The agent is still analyzing this case";
  }
}

/** Who decides an escalated case. The console has no directory of people: an open case names the role
 *  and where to approve; a decided one names the recorded approver. */
export interface ApproverRow { who: string; role: string; pill: Pill }

export function approverRow(c: Pick<CaseRecord, "status" | "approver" | "policy">): ApproverRow | null {
  const pill = statusPill(c);
  switch (c.status) {
    case "AWAITING_APPROVAL": return { who: "SAP Joule or console", role: "Supply planner", pill };
    case "EXECUTED": return c.approver ? { who: c.approver, role: "Supply planner", pill } : null;
    case "REJECTED": return { who: c.approver ?? "Unknown", role: "Supply planner", pill };
    case "BLOCKED": return { who: "Not permitted for anyone", role: c.policy?.policy_ids.join(", ") ?? "Cedar", pill };
    default: return null;
  }
}

const ACTION: Record<string, string> = {
  CREATE_STOCK_TRANSFER: "Stock transfer",
  CREATE_PURCHASE_ORDER: "Purchase order",
  RESCHEDULE_PO_LINE: "Reschedule PO",
  NOTIFY_ONLY: "Notify only",
};

/** The card's one-line description: what the agent proposed and where it stands, from the record's
 *  fields (the model's summary runs to paragraphs). Without a proposal, the summary's first sentence. */
export function cardSummary(c: Pick<CaseRecord, "proposal" | "status" | "approver" | "sap_document" | "summary">): string {
  const p = c.proposal;
  if (!p) {
    const text = plainText(c.summary).replace(/\*\*/g, "").replace(/^[-#>\s]+/gm, "").replace(/\s+/g, " ");
    return text.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? text;
  }
  const from = p.supplying_plant ? ` from plant ${p.supplying_plant}` : p.supplier ? ` from supplier ${p.supplier}` : "";
  const what = `${ACTION[p.action_type] ?? p.action_type} of ${fmtQty(p.quantity, p.unit)}${from}, arriving `
    + `${fmtDay(p.delivery_date)}, ${fmtUsdCode(p.financial_impact_usd)} incremental.`;
  const doc = c.sap_document ? ` S/4 document ${c.sap_document}.` : "";
  switch (c.status) {
    case "EXECUTED": return `${what} ${c.approver ? `Approved by ${c.approver}.` : "Executed autonomously."}${doc}`;
    case "AWAITING_APPROVAL": return `${what} Waiting for a planner's approval.`;
    case "BLOCKED": return `${what} Blocked by Cedar; no one may approve it.`;
    case "REJECTED": return `${what} Rejected by ${c.approver ?? "a planner"}.`;
    default: return what;
  }
}

export function actionLabel(c: Pick<CaseRecord, "proposal">): string {
  const p = c.proposal;
  if (!p) return "None";
  const what = ACTION[p.action_type] ?? p.action_type;
  return p.quantity ? `${what} · ${fmtQty(p.quantity, p.unit)}` : what;
}
