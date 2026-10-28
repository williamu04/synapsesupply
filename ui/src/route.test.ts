import { describe, expect, it } from "vitest";
import { parseRoute, routeQuery, streamKey, type Route } from "./route";

describe("route", () => {
  it("keeps the Joule deep link and replay links working", () => {
    expect(parseRoute("?case=4500000091-10")).toEqual({ page: "case", caseId: "4500000091-10" });
    expect(parseRoute("?replay=sc01-claude")).toEqual({ page: "replay", name: "sc01-claude", speed: 2 });
    expect(parseRoute("?replay=sc01-claude&speed=4")).toMatchObject({ speed: 4 });
  });

  it("names pages, and nothing for an empty or unknown query", () => {
    expect(parseRoute("?view=escalations")).toEqual({ page: "escalations" });
    expect(parseRoute("")).toBeNull();
    expect(parseRoute("?view=nope")).toBeNull();
  });

  it("round-trips every route through the query string", () => {
    const routes: Route[] = [
      { page: "plan" }, { page: "automated" }, { page: "statistics" },
      { page: "case", caseId: "REQ2610 1" }, { page: "replay", name: "sc03-claude", speed: 2 },
    ];
    for (const r of routes) expect(parseRoute(routeQuery(r)) ?? { page: "plan" }).toEqual(r);
  });

  it("streams only for a case or a replay", () => {
    expect(streamKey({ page: "case", caseId: "X" })).toBe("case:X");
    expect(streamKey({ page: "automated" })).toBeNull();
  });
});
