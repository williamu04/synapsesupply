// Pure derivation of what the console shows from a case's trace events. No React, unit-tested.
import type {
  PolicyDetail, SourcingResult, StockAnalysis, TraceEvent,
} from "./types";

export interface CaseView {
  details: Record<string, unknown> | null;
  analysis: StockAnalysis | null;
  sourcing: SourcingResult | null;
  policy: PolicyDetail | null;
  /** option_id -> why the agent rejected it (from the submit_action call). */
  rejected: Record<string, string>;
  /** The planner's decision on an escalated case, if any. */
  approval: { approver: string; outcome: "APPROVED" | "NOT_PERMITTED" | "REJECTED"; reason?: string } | null;
  sapDocument: string | null;
  doneTitle: string | null;
  summary: string | null;
  planner: string | null;
  degraded: boolean;
  modelFallback: boolean;
  startedAt: string | null;
  decidedAt: string | null;
}

/** Merge a new event into a seq-ordered list; duplicates (SSE reconnects) are ignored. */
export function mergeEvent(events: TraceEvent[], event: TraceEvent): TraceEvent[] {
  if (events.some((e) => e.seq === event.seq)) return events;
  const next = [...events, event];
  next.sort((a, b) => a.seq - b.seq);
  return next;
}

export function deriveView(events: TraceEvent[]): CaseView {
  const view: CaseView = {
    details: null, analysis: null, sourcing: null, policy: null, rejected: {}, approval: null, sapDocument: null, doneTitle: null,
    summary: null, planner: null, degraded: false, modelFallback: false,
    startedAt: events[0]?.ts ?? null, decidedAt: null,
  };
  for (const e of events) {
    const d = e.detail;
    switch (e.kind) {
      case "TOOL_RESULT":
        if (e.title === "get_case_details") view.details = d;
        // The case's own position; donor-plant analyses are computed silently and never traced.
        if (e.title === "analyze_stock_position") view.analysis = d as unknown as StockAnalysis;
        if (e.title === "find_sourcing_options") view.sourcing = d as unknown as SourcingResult;
        // The tool's result carries the checked reasons (compliance facts from the gate).
        if (e.title === "submit_action" && Array.isArray(d.alternatives)) {
          for (const alt of d.alternatives as { option_id?: string; reason?: string }[]) {
            if (alt.option_id) view.rejected[alt.option_id] = alt.reason ?? "";
          }
        }
        break;
      case "TOOL_CALL":
        if (e.title === "submit_action" && Array.isArray(d.rejected_alternatives)) {
          for (const alt of d.rejected_alternatives as { option_id?: string; reason?: string }[]) {
            if (alt.option_id) view.rejected[alt.option_id] = alt.reason ?? "";
          }
        }
        break;
      case "POLICY":
        view.policy = d as unknown as PolicyDetail;
        view.decidedAt = e.ts;
        break;
      case "APPROVAL":
        if (typeof d.approver === "string") {
          const outcome = e.title.startsWith("Rejected") ? "REJECTED"
            : e.title.endsWith("ALLOW") ? "APPROVED" : "NOT_PERMITTED";
          view.approval = { approver: d.approver, outcome, reason: d.reason as string | undefined };
        }
        break;
      case "ACTION":
        view.sapDocument = (d.sap_document as string | undefined) ?? view.sapDocument;
        break;
      case "ERROR":
        if (e.title.startsWith("DEGRADED")) view.degraded = true;
        if (e.title.startsWith("Model unavailable") || e.title.startsWith("Agent ended without")) {
          view.modelFallback = true;
        }
        break;
      case "DONE":
        view.doneTitle = e.title;
        view.summary = (d.summary as string | undefined) ?? null;
        view.planner = (d.planner as string | undefined) ?? view.planner;
        if (!view.decidedAt) view.decidedAt = e.ts;
        break;
      default:
        break;
    }
  }
  return view;
}

/** Seconds from case start to the policy decision (or completion). */
export function timeToDecision(view: CaseView): number | null {
  if (!view.startedAt || !view.decidedAt) return null;
  return Math.max(0, (Date.parse(view.decidedAt) - Date.parse(view.startedAt)) / 1000);
}
