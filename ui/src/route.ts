// Console routes <-> URL query. `?case=` is the deep link Joule replies carry; keep it stable.
import type { Page } from "./components/Sidebar";

export type Route =
  | { page: Page }
  | { page: "case"; caseId: string }
  | { page: "replay"; name: string; speed: number };

const PAGES: ReadonlySet<string> = new Set(["plan", "automated", "escalations", "statistics"]);

/** The route a URL names, or null when it names none (the console may then open a case by itself). */
export function parseRoute(search: string): Route | null {
  const q = new URLSearchParams(search);
  const caseId = q.get("case");
  if (caseId) return { page: "case", caseId };
  const replay = q.get("replay");
  if (replay) return { page: "replay", name: replay, speed: Number(q.get("speed")) || 2 };
  const view = q.get("view");
  if (view && PAGES.has(view)) return { page: view as Page };
  return null;
}

export function routeQuery(route: Route): string {
  if (route.page === "case") return `?case=${encodeURIComponent(route.caseId)}`;
  if (route.page === "replay") return `?replay=${encodeURIComponent(route.name)}&speed=${route.speed}`;
  return route.page === "plan" ? "" : `?view=${route.page}`;
}

/** The trace stream a route needs, as a stable key (null: no stream). */
export function streamKey(route: Route): string | null {
  if (route.page === "case") return `case:${route.caseId}`;
  if (route.page === "replay") return `replay:${route.name}:${route.speed}`;
  return null;
}
