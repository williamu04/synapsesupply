import { fmtDay, fmtQty, fmtUsd } from "../format";
import type { PolicyEffect, SourcingResult } from "../types";
import { ComplianceBadge } from "./ComplianceBadge";

const SUBMITTED = {
  ALLOW: ["chosen", "★ Chosen"], ESCALATE: ["chosen", "★ Proposed"], DENY: ["denied", "⛔ Requested · denied"],
} as const;

export function OptionsTable({ sourcing, chosen, effect, approved, rejected, unit }: {
  sourcing: SourcingResult;
  chosen: string | null;
  effect: PolicyEffect | null;
  approved: boolean;
  rejected: Record<string, string>;
  unit: string;
}) {
  return (
    <section className="panel" aria-labelledby="options-title">
      <div className="panel-text">
        <h2 className="panel-title" id="options-title">Sourcing Options</h2>
        <p>
          {fmtQty(sourcing.quantity, unit)} needed at plant {sourcing.plant} by {fmtDay(sourcing.needed_by)} ·
          incremental cost vs. a baseline price of {fmtUsd(sourcing.baseline_price)} per unit
        </p>
        {sourcing.delay_prediction?.method && (
          <p className="muted small">
            On-time probability: {sourcing.delay_prediction.method === "sap-rpt-1.6"
              ? "predicted by SAP RPT-1"
              : `${sourcing.delay_prediction.method} estimate`} from {sourcing.delay_prediction.history_rows} past
            deliveries in S/4
          </p>
        )}
      </div>
      <div className="inset table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Option</th><th>Arrives</th><th>Compliance</th>
              <th className="num">Cost</th><th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {sourcing.options.map((o) => {
              const isChosen = o.option_id === chosen;
              return (
                <tr key={o.option_id} className={isChosen ? SUBMITTED[effect ?? "ALLOW"][0] : ""}>
                  <td>
                    <div className="opt-name">{o.source_name}</div>
                    <div className="muted small">
                      {o.kind === "STOCK_TRANSFER" ? "Stock transfer" : "Purchase order"} · {o.option_id}
                      {o.max_quantity !== null && ` · max ${fmtQty(o.max_quantity, unit)}`}
                    </div>
                  </td>
                  <td className="arrives">
                    {fmtDay(o.earliest_arrival)}
                    <div className={`small ${o.arrives_in_time ? "muted" : "status serious"}`}>
                      {o.arrives_in_time ? "✓ in time" : "✗ too late"}
                    </div>
                    {o.on_time_probability !== undefined && (
                      <div className={`small ${o.on_time_probability < 0.5 ? "status serious" : "muted"}`}
                           title={`Expected delay ${o.predicted_delay_days} days (${o.prediction_method})`}>
                        {o.on_time_probability < 0.5 ? "⚠ " : ""}{Math.round(o.on_time_probability * 100)}% on time
                      </div>
                    )}
                  </td>
                  <td>
                    <ComplianceBadge value={o.compliance} />
                    {o.compliance_findings.map((f) => <div key={f} className="muted small finding">{f}</div>)}
                  </td>
                  <td className="num">{fmtUsd(o.incremental_cost_for_quantity)}</td>
                  <td>
                    {isChosen ? <span className={`tag ${effect === "DENY" ? "tag-denied" : ""}`}>{approved ? "★ Chosen · approved" : SUBMITTED[effect ?? "ALLOW"][1]}</span>
                      : <span className="muted small">{rejected[o.option_id] || "–"}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
