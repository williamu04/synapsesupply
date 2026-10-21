// The policy decision: effect, why, the two limits as meters, and approve/reject when it waits on a human.
import { useState } from "react";
import { fmtUsd } from "../format";
import type { CaseView } from "../caseView";
import type { CaseRecord, PolicyDetail } from "../types";

const LIMIT_CONFIDENCE = 0.9;
const LIMIT_IMPACT = 5000;

const EFFECT = {
  ALLOW: { icon: "✓", label: "Executed autonomously", cls: "good" },
  ESCALATE: { icon: "⚑", label: "Needs planner approval", cls: "warning" },
  DENY: { icon: "⛔", label: "Denied by policy", cls: "critical" },
} as const;

function Meter({ label, value, display, limit, limitLabel, max, higherIsBetter }: {
  label: string; value: number; display: string; limit: number; limitLabel: string; max: number;
  higherIsBetter: boolean;
}) {
  const ok = higherIsBetter ? value >= limit : value <= limit;
  const pct = Math.min(100, (value / max) * 100);
  const tick = (limit / max) * 100;
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <span className="meter-value">{display}</span>
      </div>
      <div className={`meter-track ${ok ? "" : "over"}`} role="meter" aria-valuenow={value} aria-valuemin={0}
           aria-valuemax={max} aria-label={`${label} ${display}, limit ${limitLabel}`}>
        <div className="meter-fill" style={{ width: `${pct}%` }} />
        <div className="meter-tick" style={{ left: `${tick}%` }} />
      </div>
      <div className="meter-foot muted">
        <span>{ok ? "✓ within" : "✗ outside"} autonomous limit</span>
        <span>limit {limitLabel}</span>
      </div>
    </div>
  );
}

const HUMAN = {
  APPROVED: { icon: "✓", label: "Approved by", cls: "good" },
  REJECTED: { icon: "✗", label: "Rejected by", cls: "neutral" },
  NOT_PERMITTED: { icon: "⛔", label: "Approval not permitted for", cls: "critical" },
} as const;

export function DecisionCard({ policy, approval, record, onApprove, onReject }: {
  policy: PolicyDetail;
  approval: CaseView["approval"];
  record: CaseRecord | null;
  onApprove: (approver: string) => Promise<void>;
  onReject: (approver: string, reason: string) => Promise<void>;
}) {
  const [approver, setApprover] = useState(() => {
    try { return localStorage.getItem("approver") ?? ""; } catch { return ""; }
  });
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const e = EFFECT[policy.effect];
  const awaiting = record?.status === "AWAITING_APPROVAL";

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      try { localStorage.setItem("approver", approver); } catch { /* storage unavailable */ }
      await fn();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card decision" aria-labelledby="decision-title">
      <h3 id="decision-title">Policy decision</h3>
      {approval && (
        <div className={`effect status ${HUMAN[approval.outcome].cls}`}>
          <span aria-hidden>{HUMAN[approval.outcome].icon}</span> {HUMAN[approval.outcome].label} {approval.approver}
        </div>
      )}
      <div className={`effect status ${e.cls} ${approval ? "superseded" : ""}`}>
        <span aria-hidden>{e.icon}</span> {approval ? `Agent: ${e.label.toLowerCase()}` : e.label}
      </div>
      {approval?.reason && <p className="muted small">Reason: {approval.reason}</p>}
      <ul className="reasons">{policy.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      <p className="muted small">Cedar: {policy.policy_ids.join(" · ")}</p>

      <Meter label="Plan confidence" value={policy.confidence} display={policy.confidence.toFixed(2)}
             limit={LIMIT_CONFIDENCE} limitLabel="≥ 0.90" max={1} higherIsBetter />
      <Meter label="Financial impact" value={policy.financial_impact_usd} display={fmtUsd(policy.financial_impact_usd)}
             limit={LIMIT_IMPACT} limitLabel={`≤ ${fmtUsd(LIMIT_IMPACT)}`}
             max={Math.max(LIMIT_IMPACT * 2, policy.financial_impact_usd * 1.1)} higherIsBetter={false} />
      <div className="compliance-line">
        Supplier compliance: <ComplianceBadge value={policy.compliance} />
      </div>

      {awaiting && (
        <form className="approval" onSubmit={(ev) => ev.preventDefault()}>
          <label>Planner
            <input value={approver} onChange={(ev) => setApprover(ev.target.value)} placeholder="Your name" required />
          </label>
          <label>Reason (for rejection)
            <input value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="Optional for approval" />
          </label>
          <div className="actions">
            <button className="primary" disabled={busy || !approver.trim()}
                    onClick={() => act(() => onApprove(approver.trim()))}>Approve and execute</button>
            <button disabled={busy || !approver.trim() || !reason.trim()}
                    onClick={() => act(() => onReject(approver.trim(), reason.trim()))}>Reject</button>
          </div>
          {error && <p className="status critical" role="alert">✗ {error}</p>}
        </form>
      )}
    </section>
  );
}

export function ComplianceBadge({ value }: { value: string }) {
  const map: Record<string, [string, string, string]> = {
    PASS: ["good", "✓", "PASS"],
    HOLD: ["warning", "⚠", "HOLD"],
    BLOCK: ["critical", "⛔", "BLOCK"],
    NOT_APPLICABLE: ["neutral", "◇", "Own plant"],
  };
  const [cls, icon, label] = map[value] ?? ["neutral", "?", value];
  return <span className={`badge ${cls}`}><span aria-hidden>{icon}</span> {label}</span>;
}
