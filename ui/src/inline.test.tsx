import { isValidElement, type ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { inlineBold } from "./inline";

// "b" for a <strong> span, the string itself otherwise.
const shape = (nodes: ReactNode[]) =>
  nodes.map((n) => (isValidElement<{ children: string }>(n) && n.type === "strong" ? { b: n.props.children } : n));

describe("inlineBold", () => {
  it("leaves plain text alone", () => {
    expect(shape(inlineBold("Stock falls below safety stock."))).toEqual(["Stock falls below safety stock."]);
  });

  it("renders one bold span", () => {
    expect(shape(inlineBold("Plan: **STO:1200** from Jambi"))).toEqual(["Plan: ", { b: "STO:1200" }, " from Jambi"]);
  });

  it("renders several bold spans", () => {
    expect(shape(inlineBold("**ESCALATE**: $8,280 > **$5,000**"))).toEqual([
      { b: "ESCALATE" }, ": $8,280 > ", { b: "$5,000" },
    ]);
  });

  it("keeps an unmatched ** as plain text", () => {
    expect(shape(inlineBold("**a** and **b"))).toEqual([{ b: "a" }, " and ", "**b"]);
    expect(shape(inlineBold("2 ** 3"))).toEqual(["2 ", "** 3"]);
  });

  it("returns nothing for an empty string", () => {
    expect(inlineBold("")).toEqual([]);
  });
});
