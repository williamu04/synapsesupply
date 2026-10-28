import type { Pill } from "../caseSummary";

/** The design's status pill: a centered label on the tone's color (the label always carries the state). */
export function StatusPill({ tone, label }: Pill) {
  return <span className={`pill pill-${tone}`}>{label}</span>;
}
