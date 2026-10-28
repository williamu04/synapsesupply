import type { ReactNode } from "react";

export interface Stat { label: string; value: ReactNode; sub?: ReactNode }

/** The design's "Stats" row: a muted label over a bold value with an optional regular-weight detail. */
export function Stats({ items }: { items: Stat[] }) {
  return (
    <dl className="stats">
      {items.map((s) => (
        <div key={s.label} className="stat">
          <dt>{s.label}</dt>
          <dd><strong>{s.value}</strong>{s.sub && <span>{s.sub}</span>}</dd>
        </div>
      ))}
    </dl>
  );
}
