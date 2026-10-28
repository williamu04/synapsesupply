import type { Pill } from "../caseSummary";
import { plainText } from "../plainText";
import type { PolicyEffect } from "../types";
import { StatusPill } from "./StatusPill";

/** The inset box naming why Cedar escalated or denied a case (or let it run), with the case's pill. */
export function EscalationBox({ effect, reasons, pill }: { effect: PolicyEffect; reasons: string[]; pill: Pill }) {
  const met = effect !== "ALLOW";
  return (
    <div className="escalation-box">
      <div className="escalation-text">
        <p>{met ? "Escalation condition met:" : "Escalation condition not met:"}</p>
        {reasons.map((r) => <p key={r} className={met ? "reason-met" : ""}>{plainText(r)}</p>)}
      </div>
      <StatusPill {...pill} />
    </div>
  );
}
