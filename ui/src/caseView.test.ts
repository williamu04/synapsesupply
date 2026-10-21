import { describe, expect, it } from "vitest";
import { deriveView, mergeEvent, timeToDecision } from "./caseView";
import type { TraceEvent, TraceKind } from "./types";

let seq = 0;
function ev(kind: TraceKind, title: string, detail: Record<string, unknown> = {}, ts?: string): TraceEvent {
  const n = seq++;
  return { case_id: "4500000091-10", seq: n, ts: ts ?? `2026-10-31T09:00:0${n % 10}.000Z`, kind, title, detail };
}

describe("mergeEvent", () => {
  it("orders by seq and ignores duplicates from SSE reconnects", () => {
    seq = 0;
    const a = ev("PLAN", "a");
    const b = ev("DONE", "b");
    let list = mergeEvent([], b);
    list = mergeEvent(list, a);
    list = mergeEvent(list, b);
    expect(list.map((e) => e.seq)).toEqual([0, 1]);
  });
});

describe("deriveView", () => {
  it("collects the case's analysis, options, policy and outcome", () => {
    seq = 0;
    const events = [
      ev("PLAN", "Case received", {}, "2026-10-31T09:00:00.000Z"),
      ev("TOOL_RESULT", "get_case_details", { supplier_name: "Riau Fibre Plantations", delay_days: 3 }),
      ev("TOOL_RESULT", "analyze_stock_position", { plant: "1100", safety_stock: 1195.8 }),
      ev("TOOL_RESULT", "find_sourcing_options", { options: [{ option_id: "STO:1200" }] }),
      ev("TOOL_CALL", "submit_action", { rejected_alternatives: [{ option_id: "PO:0000100003", reason: "BLOCK" }] }),
      ev("POLICY", "Cedar: ESCALATE", { effect: "ESCALATE", option_id: "STO:1200" }, "2026-10-31T09:00:01.500Z"),
      ev("DONE", "AWAITING_APPROVAL", { summary: "Waiting", planner: "autopilot" }),
      ev("APPROVAL", "Approval requested from a planner (SAP Joule)"),
      ev("ACTION", "Created", { sap_document: "4500000105" }),
      ev("DONE", "EXECUTED", { summary: "Approved", planner: null }),
    ];
    const v = deriveView(events);
    expect(v.details?.supplier_name).toBe("Riau Fibre Plantations");
    expect(v.analysis?.safety_stock).toBe(1195.8);
    expect(v.sourcing?.options[0].option_id).toBe("STO:1200");
    expect(v.policy?.effect).toBe("ESCALATE");
    expect(v.rejected).toEqual({ "PO:0000100003": "BLOCK" });
    expect(v.approval).toBeNull(); // "Approval requested" carries no approver
    expect(v.sapDocument).toBe("4500000105");
    expect(v.doneTitle).toBe("EXECUTED");
    expect(v.summary).toBe("Approved");
    expect(v.planner).toBe("autopilot"); // a later DONE without a planner keeps the earlier one
    expect(timeToDecision(v)).toBeCloseTo(1.5);
  });

  it("reads the planner's decision", () => {
    seq = 0;
    expect(deriveView([ev("APPROVAL", "Approval by Dewi: ALLOW", { approver: "Dewi" })]).approval)
      .toEqual({ approver: "Dewi", outcome: "APPROVED", reason: undefined });
    expect(deriveView([ev("APPROVAL", "Rejected by Dewi", { approver: "Dewi", reason: "Slow line 2" })]).approval)
      .toEqual({ approver: "Dewi", outcome: "REJECTED", reason: "Slow line 2" });
    expect(deriveView([ev("APPROVAL", "Approval by Ana: DENY", { approver: "Ana" })]).approval?.outcome)
      .toBe("NOT_PERMITTED");
  });

  it("flags fallbacks", () => {
    seq = 0;
    const v = deriveView([
      ev("ERROR", "DEGRADED: S/4 unreachable — switched to local mock ERP"),
      ev("ERROR", "Model unavailable — deterministic autopilot takes over"),
    ]);
    expect(v.degraded).toBe(true);
    expect(v.modelFallback).toBe(true);
    expect(timeToDecision(v)).toBeNull();
  });

  it("handles an empty trace", () => {
    const v = deriveView([]);
    expect(v.policy).toBeNull();
    expect(v.startedAt).toBeNull();
  });
});
