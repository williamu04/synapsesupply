import { describe, expect, it } from "vitest";
import { cardSummary } from "./caseSummary";
import { plainText } from "./plainText";
import type { ActionProposal } from "./types";

describe("plainText", () => {
  it("turns em dashes into commas and drops emoji status marks", () => {
    expect(plainText("Case 4500000091-10 — Summary for planner")).toBe("Case 4500000091-10, Summary for planner");
    expect(plainText("arrives 2026-11-03, late ❌ — rejected")).toBe("arrives 2026-11-03, late, rejected");
    expect(plainText("up to 1,500 TO available. ✅ Best option right now.")).toBe("up to 1,500 TO available. Best option right now.");
    expect(plainText("⚠️ HOLD — 🚫 BLOCK")).toBe("HOLD, BLOCK");
  });

  it("keeps line breaks, bullets and bold markers for the trace", () => {
    expect(plainText("Options:\n- **PO:1** — late\n- **STO:1200** ✅")).toBe("Options:\n- **PO:1**, late\n- **STO:1200**");
  });
});

describe("cardSummary", () => {
  const proposal = {
    action_type: "CREATE_STOCK_TRANSFER", quantity: 920, unit: "TO", supplying_plant: "1200", supplier: null,
    delivery_date: "2026-11-01", financial_impact_usd: 8280,
  } as ActionProposal;

  it("says what was proposed and where it stands", () => {
    expect(cardSummary({ proposal, status: "AWAITING_APPROVAL", approver: null, sap_document: null, summary: "" }))
      .toBe("Stock transfer of 920 t from plant 1200, arriving Sun 1 Nov, USD 8,280 incremental. "
        + "Waiting for a planner's approval.");
    expect(cardSummary({ proposal, status: "EXECUTED", approver: "joule:unknown-user", sap_document: "4500000105", summary: "" }))
      .toMatch(/Approved by joule:unknown-user\. S\/4 document 4500000105\.$/);
  });

  it("falls back to the first plain sentence of the model's summary", () => {
    const summary = "Here is the current sourcing picture for **WC-ACACIA at plant 1100**. Five suppliers — varied ✅.";
    expect(cardSummary({ proposal: null, status: "NO_ACTION_NEEDED", approver: null, sap_document: null, summary }))
      .toBe("Here is the current sourcing picture for WC-ACACIA at plant 1100.");
  });
});
