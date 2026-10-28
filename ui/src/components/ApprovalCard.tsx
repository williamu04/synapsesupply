// "Requiring Approval": who decides the case, and the approve / reject form while it waits on a planner.
import { useState } from "react";
import type { ApproverRow } from "../caseSummary";
import { StatusPill } from "./StatusPill";

export function ApprovalCard({ row, awaiting, reason, onApprove, onReject }: {
  row: ApproverRow | null;
  awaiting: boolean;
  /** The planner's rejection reason, once decided. */
  reason?: string;
  onApprove: (approver: string) => Promise<void>;
  onReject: (approver: string, reason: string) => Promise<void>;
}) {
  const [approver, setApprover] = useState(() => {
    try { return localStorage.getItem("approver") ?? ""; } catch { return ""; }
  });
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <section className="inset approval-card" aria-labelledby="approval-title">
      <p id="approval-title" className="muted">Requiring Approval</p>
      {row ? (
        <div className="approver-row">
          <StatusPill {...row.pill} />
          <p className="approver"><span>{row.who}</span> <strong>{row.role}</strong></p>
        </div>
      ) : <p className="muted small">No human approval needed: Cedar let the agent act alone.</p>}
      {reason && <p className="small">Reason: {reason}</p>}

      {awaiting && (
        <form className="approval-form" onSubmit={(ev) => ev.preventDefault()}>
          <label>Planner
            <input value={approver} onChange={(ev) => setApprover(ev.target.value)} placeholder="Your name" required />
          </label>
          <label>Reason (for rejection)
            <input value={why} onChange={(ev) => setWhy(ev.target.value)} placeholder="Optional for approval" />
          </label>
          <div className="actions">
            <button className="btn btn-filled" disabled={busy || !approver.trim()}
                    onClick={() => act(() => onApprove(approver.trim()))}>Approve and execute</button>
            <button className="btn btn-outlined" disabled={busy || !approver.trim() || !why.trim()}
                    onClick={() => act(() => onReject(approver.trim(), why.trim()))}>Reject</button>
          </div>
          {error && <p className="error-text" role="alert">{error}</p>}
        </form>
      )}
    </section>
  );
}
