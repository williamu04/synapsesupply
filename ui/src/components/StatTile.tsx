import type { ReactNode } from "react";

/** One headline number: label, value, optional context line. Text tokens only; no status colors. */
export function StatTile({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="inset stat-tile">
      <span className="tile-label">{label}</span>
      <strong className="tile-value">{value}</strong>
      {sub && <span className="tile-sub">{sub}</span>}
    </div>
  );
}
