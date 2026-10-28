// Number, date and scale helpers. Pure and unit-tested.

const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export const fmtUsd = (v: number): string => usd0.format(v);
/** The design's money style: "USD 8,280". */
export const fmtUsdCode = (v: number): string => `USD ${int.format(v)}`;

/** ISO timestamp -> ["Oct 27, 2026", "04:17 PM"] in the viewer's time zone. */
export function fmtDateTime(iso: string): [string, string] {
  const d = new Date(iso);
  return [
    d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
    d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true }),
  ];
}
export const fmtQty = (v: number, unit?: string): string => `${int.format(v)}${unit ? ` ${unitLabel(unit)}` : ""}`;

/** S/4 base units to readable labels. */
export function unitLabel(unit: string): string {
  return ({ TO: "t", M3: "m³" } as Record<string, string>)[unit] ?? unit;
}

/** "2026-11-02" -> "Mon 2 Nov" (dates are business days, no timezone shift). */
export function fmtDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

export function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

/** Clean axis: a "nice" step so there are about `count` ticks covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (max <= min) max = min + 1;
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let t = start; t <= max + step * 0.5; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  return ticks;
}
