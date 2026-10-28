import { describe, expect, it } from "vitest";
import { actionLabel, approverRow, automatedNote, caseTitle, lane, statusPill } from "./caseSummary";
import { fmtDateTime, fmtUsdCode } from "./format";
import { themeClass } from "./theme";
import type { ActionProposal, PolicyDecision } from "./types";

const policy = (effect: PolicyDecision["effect"]): PolicyDecision => ({ effect, policy_ids: [], reasons: [] });

describe("lane", () => {
  it("sends escalated and denied cases to Escalations, the rest to Automated", () => {
    expect(lane({ policy: policy("ESCALATE"), approver: null })).toBe("escalation");
    expect(lane({ policy: policy("DENY"), approver: null })).toBe("escalation");
    expect(lane({ policy: policy("ALLOW"), approver: null })).toBe("automated");
    expect(lane({ policy: null, approver: null })).toBe("automated");  // still analyzing, or nothing to do
  });

  it("keeps a planner-decided case in Escalations after Cedar re-checks the approver as ALLOW", () => {
    expect(lane({ policy: policy("ALLOW"), approver: "joule:unknown-user" })).toBe("escalation");
  });
});

describe("case card text", () => {
  it("titles a case by its process, material and plant", () => {
    expect(caseTitle({ process_type: "ASN_DELAY", material: "WC-ACACIA", plant: "1100" }))
      .toBe("Late delivery: WC-ACACIA at plant 1100");
    expect(caseTitle({ process_type: "USER_REQUEST", material: null, plant: null })).toBe("Buyer request");
  });

  it("maps status to the design's pills, with Approved for a human-approved execution", () => {
    expect(statusPill({ status: "AWAITING_APPROVAL", approver: null })).toEqual({ tone: "warning", label: "Pending" });
    expect(statusPill({ status: "BLOCKED", approver: null })).toEqual({ tone: "error", label: "Blocked" });
    expect(statusPill({ status: "EXECUTED", approver: "joule:planner" }).label).toBe("Approved");
    expect(statusPill({ status: "EXECUTED", approver: null }).label).toBe("Executed");
  });

  it("explains why an automated case needed no human", () => {
    expect(automatedNote({ status: "EXECUTED" })).toBe("Escalation condition not met, human approval not needed");
    expect(automatedNote({ status: "ANALYZING" })).toMatch(/still analyzing/);
  });

  it("names who decides an escalated case without inventing people", () => {
    expect(approverRow({ status: "AWAITING_APPROVAL", approver: null, policy: policy("ESCALATE") }))
      .toMatchObject({ who: "SAP Joule or console", role: "Supply planner", pill: { label: "Pending" } });
    expect(approverRow({ status: "EXECUTED", approver: "joule:unknown-user", policy: policy("ESCALATE") }))
      .toMatchObject({ who: "joule:unknown-user", pill: { label: "Approved" } });
    expect(approverRow({ status: "BLOCKED", approver: null,
      policy: { effect: "DENY", policy_ids: ["Policy-ComplianceBlock"], reasons: [] } }))
      .toMatchObject({ role: "Policy-ComplianceBlock", pill: { label: "Blocked" } });
    expect(approverRow({ status: "EXECUTED", approver: null, policy: policy("ALLOW") })).toBeNull();
  });

  it("labels the proposed action with its quantity", () => {
    const proposal = { action_type: "CREATE_STOCK_TRANSFER", quantity: 920, unit: "TO" } as ActionProposal;
    expect(actionLabel({ proposal })).toBe("Stock transfer · 920 t");
    expect(actionLabel({ proposal: null })).toBe("None");
  });
});

describe("format additions", () => {
  it("formats money the design's way and splits date from time", () => {
    expect(fmtUsdCode(8280)).toBe("USD 8,280");
    const [date, time] = fmtDateTime("2026-10-27T09:17:00Z");
    expect(date).toMatch(/^Oct 2\d, 2026$/);
    expect(time).toMatch(/^\d{2}:\d{2} (AM|PM)$/);
  });
});

describe("themeClass", () => {
  it("resolves system mode and contrast to a style-guide class", () => {
    expect(themeClass({ mode: "light", contrast: "standard" }, true)).toBe("light");
    expect(themeClass({ mode: "system", contrast: "high" }, true)).toBe("dark-high-contrast");
    expect(themeClass({ mode: "system", contrast: "medium" }, false)).toBe("light-medium-contrast");
  });
});
