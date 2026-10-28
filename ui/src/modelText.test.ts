import { describe, expect, it } from "vitest";
import { modelBlocks } from "./modelText";

describe("modelBlocks", () => {
  it("splits paragraphs and bullet lists the way Claude writes them", () => {
    const text = "The analysis is clear. Let me submit the action:\n\n"
      + "- **Only one option arrives in time:** `PO:0000100004`\n"
      + "- Riau Fibre (`PO:0000100001`) also arrives 2026-11-02, too late.\n\n"
      + "Summary for the planner:\nsecond line";
    expect(modelBlocks(text)).toEqual([
      { kind: "p", lines: ["The analysis is clear. Let me submit the action:"] },
      { kind: "ul", items: ["**Only one option arrives in time:** `PO:0000100004`",
        "Riau Fibre (`PO:0000100001`) also arrives 2026-11-02, too late."] },
      { kind: "p", lines: ["Summary for the planner:", "second line"] },
    ]);
  });

  it("returns one paragraph for plain text and nothing for blank text", () => {
    expect(modelBlocks("Case closed.")).toEqual([{ kind: "p", lines: ["Case closed."] }]);
    expect(modelBlocks("  \n\n")).toEqual([]);
  });
});
