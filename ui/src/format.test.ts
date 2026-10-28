import { describe, expect, it } from "vitest";
import { fmtDay, fmtDuration, fmtQty, fmtUsd, niceTicks, unitLabel } from "./format";

describe("format", () => {
  it("formats money, quantities and units", () => {
    expect(fmtUsd(8280)).toBe("$8,280");
    expect(fmtQty(1195.8, "TO")).toBe("1,196 t");
    expect(fmtQty(430, "M3")).toBe("430 m³");
    expect(unitLabel("KG")).toBe("KG");
  });

  it("formats business days without timezone drift", () => {
    expect(fmtDay("2026-11-02")).toBe("Mon 2 Nov");
  });

  it("formats durations", () => {
    expect(fmtDuration(1.234)).toBe("1.2 s");
    expect(fmtDuration(42)).toBe("42 s");
    expect(fmtDuration(150)).toBe("2 min 30 s");
  });
});

describe("niceTicks", () => {
  it("covers the range with clean steps", () => {
    expect(niceTicks(0, 4200, 4)).toEqual([0, 2000, 4000, 6000].filter((t) => t <= 4200 + 1000));
    const t = niceTicks(-300, 3900, 4);
    expect(t[0]).toBeLessThanOrEqual(-300);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(3900 - (t[1] - t[0]) / 2);
    const steps = t.slice(1).map((v, i) => v - t[i]);
    expect(new Set(steps).size).toBe(1);
  });

  it("survives a flat range", () => {
    expect(niceTicks(5, 5).length).toBeGreaterThan(1);
  });
});
