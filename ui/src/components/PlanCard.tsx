// "Planned By": the planner, the three figures Cedar judges, and plan confidence against its limit.
import { fmtUsdCode } from "../format";
import type { PolicyDetail } from "../types";
import { complianceLabel } from "./ComplianceBadge";

const LIMIT_CONFIDENCE = 0.9;
const LIMIT_IMPACT = 5000;
const TICKS = [0, 0.2, 0.4, 0.6, 0.8, 1];

export function PlanCard({ planner, policy }: { planner: string | null; policy: PolicyDetail }) {
  const confident = policy.confidence >= LIMIT_CONFIDENCE;
  const affordable = policy.financial_impact_usd <= LIMIT_IMPACT;
  return (
    <section className="inset plan-card" aria-labelledby="plan-title">
      <div className="plan-by">
        <p id="plan-title" className="muted">Planned By</p>
        <strong>{planner === "llm" ? "Claude" : planner ? "Autopilot (fallback)" : "Pending"}</strong>
      </div>
      <dl className="plan-figures">
        <div>
          <dt>Plan Confidence</dt>
          <dd className={confident ? "" : "over"}>{policy.confidence.toFixed(2)}</dd>
          <dd className="limit">limit ≥ {LIMIT_CONFIDENCE.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Financial Impact</dt>
          <dd className={affordable ? "" : "over"}>{fmtUsdCode(policy.financial_impact_usd)}</dd>
          <dd className="limit">limit ≤ {fmtUsdCode(LIMIT_IMPACT)}</dd>
        </div>
        <div>
          <dt>Supplier Compliance</dt>
          <dd>{complianceLabel(policy.compliance)}</dd>
        </div>
      </dl>
      <div className="confidence-meter" role="meter" aria-valuenow={policy.confidence} aria-valuemin={0}
           aria-valuemax={1} aria-label={`Plan confidence ${policy.confidence.toFixed(2)}, limit ${LIMIT_CONFIDENCE}`}>
        <span className="meter-label" aria-hidden>Plan Confidence</span>
        <div className="meter-scale" aria-hidden>
          <div className="meter-track">
            <div className={`meter-fill ${confident ? "" : "over"}`} style={{ width: `${policy.confidence * 100}%` }} />
            <div className="meter-limit" style={{ left: `${LIMIT_CONFIDENCE * 100}%` }} />
          </div>
          <div className="meter-ticks">{TICKS.map((t) => <span key={t}>{t}</span>)}</div>
        </div>
      </div>
    </section>
  );
}
