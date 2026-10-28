import type { Pill } from "../caseSummary";

/** The design's status pill: a dot and a label on the tone's color (the label always carries the state). */
export function StatusPill({ tone, label }: Pill) {
  return <span className={`pill pill-${tone}`}><span className="pill-dot" aria-hidden />{label}</span>;
}
