import type { Pill } from "../caseSummary";
import { StatusPill } from "./StatusPill";

const COMPLIANCE: Record<string, Pill> = {
  PASS: { tone: "success", label: "PASS" },
  HOLD: { tone: "warning", label: "HOLD" },
  BLOCK: { tone: "error", label: "BLOCK" },
  NOT_APPLICABLE: { tone: "neutral", label: "Own plant" },
};

/** EUDR gate outcome as a status pill. */
export function ComplianceBadge({ value }: { value: string }) {
  return <StatusPill {...(COMPLIANCE[value] ?? { tone: "neutral", label: value })} />;
}

export const complianceLabel = (value: string): string => COMPLIANCE[value]?.label ?? value;
