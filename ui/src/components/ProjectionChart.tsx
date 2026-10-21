// Seven-day stock projection: closing stock per day as columns against the safety-stock line.
// One series (no legend; the title names it). Days below safety stock use the reserved critical
// status color AND carry an icon + label, so state never rides on color alone.
import { useState } from "react";
import { fmtCompact, fmtDay, fmtQty, niceTicks, unitLabel } from "../format";
import type { StockAnalysis } from "../types";

const W = 640;
const H = 260;
const M = { top: 28, right: 112, bottom: 48, left: 48 };
const BAR_MAX = 24;
const R = 4;

interface Column { day: string; closing: number; receipts: number; below: boolean; today: boolean }

/** Column path with a 4px rounded data-end and a square baseline end; negative values grow down. */
function columnPath(x: number, w: number, y0: number, y1: number): string {
  const up = y1 < y0;
  const h = Math.abs(y1 - y0);
  const r = Math.min(R, h, w / 2);
  if (h === 0) return "";
  if (up) {
    return `M${x},${y0} V${y1 + r} Q${x},${y1} ${x + r},${y1} H${x + w - r} Q${x + w},${y1} ${x + w},${y1 + r} V${y0} Z`;
  }
  return `M${x},${y0} V${y1 - r} Q${x},${y1} ${x + r},${y1} H${x + w - r} Q${x + w},${y1} ${x + w},${y1 - r} V${y0} Z`;
}

export function ProjectionChart({ analysis }: { analysis: StockAnalysis }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const unit = unitLabel(analysis.unit);
  const ss = analysis.safety_stock;

  const columns: Column[] = [
    { day: analysis.today, closing: analysis.on_hand_unrestricted, receipts: 0,
      below: analysis.on_hand_unrestricted < ss, today: true },
    ...analysis.projection.map((p) => ({
      day: p.day, closing: p.closing, receipts: p.receipts, below: p.below_safety_stock, today: false })),
  ];
  const values = columns.map((c) => c.closing);
  const ticks = niceTicks(Math.min(0, ...values), Math.max(ss, ...values) * 1.08, 4);
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const y = (v: number) => M.top + plotH - ((v - lo) / (hi - lo)) * plotH;
  const band = plotW / columns.length;
  const barW = Math.min(BAR_MAX, band * 0.55);
  const x = (i: number) => M.left + band * i + (band - barW) / 2;
  const minIndex = values.indexOf(Math.min(...values.slice(1)));
  const breach = analysis.first_breach_day;

  const title = `Projected ${analysis.material} stock at plant ${analysis.plant}`;
  return (
    <figure className="viz" aria-labelledby="proj-title">
      <figcaption className="viz-head">
        <div>
          <h3 id="proj-title">{title}</h3>
          <p className="muted">
            Closing stock per day, next 7 days · unrestricted stock only
            {analysis.other_stock_not_available > 0 &&
              ` (${fmtQty(analysis.other_stock_not_available, analysis.unit)} in quality inspection excluded)`}
          </p>
        </div>
        <button className="link" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
          {asTable ? "Chart" : "Table"}
        </button>
      </figcaption>

      {asTable ? (
        <table className="data">
          <thead><tr><th>Day</th><th className="num">Receipts</th><th className="num">Closing</th><th>Status</th></tr></thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.day}>
                <td>{c.today ? "Today" : fmtDay(c.day)}</td>
                <td className="num">{c.receipts ? fmtQty(c.receipts) : "–"}</td>
                <td className="num">{fmtQty(c.closing, analysis.unit)}</td>
                <td>{c.below ? <span className="status critical">▼ Below safety stock</span> : "OK"}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td colSpan={4} className="muted">Safety stock {fmtQty(ss, analysis.unit)}</td></tr></tfoot>
        </table>
      ) : (
        <div className="viz-plot">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. Safety stock ${fmtQty(ss, analysis.unit)}.${
            breach ? ` Falls below safety stock on ${fmtDay(breach)}.` : " Stays above safety stock."}`}>
            {ticks.map((t) => (
              <g key={t}>
                <line className="gridline" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
                <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{fmtCompact(t)}</text>
              </g>
            ))}
            <line className="baseline" x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)} />

            {columns.map((c, i) => (
              <g key={c.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                {/* hit target larger than the mark */}
                <rect x={M.left + band * i} y={M.top} width={band} height={plotH} fill="transparent" />
                <path d={columnPath(x(i), barW, y(0), y(c.closing))}
                      className={c.below ? "col col-critical" : "col"} opacity={hover === null || hover === i ? 1 : 0.55} />
                <text className="tick" x={x(i) + barW / 2} y={H - M.bottom + 16} textAnchor="middle">
                  {c.today ? "Today" : fmtDay(c.day).split(" ").slice(0, 2).join(" ")}
                </text>
                {c.below && (
                  <text className="tick critical-ink" x={x(i) + barW / 2} y={H - M.bottom + 32} textAnchor="middle">▼ below</text>
                )}
                {(i === minIndex || c.today) && (
                  <text className="value" x={x(i) + barW / 2} y={y(Math.max(c.closing, 0)) - 8} textAnchor="middle">
                    {fmtCompact(Math.round(c.closing))}
                  </text>
                )}
              </g>
            ))}

            <line className="reference" x1={M.left} x2={W - M.right} y1={y(ss)} y2={y(ss)} />
            <text className="ref-label" x={W - M.right + 8} y={y(ss)} dy="-0.2em">Safety stock</text>
            <text className="ref-value" x={W - M.right + 8} y={y(ss)} dy="1.1em">{fmtQty(ss, analysis.unit)}</text>
          </svg>

          {hover !== null && (
            <div className="tooltip" style={{
              left: `${((x(hover) + barW / 2) / W) * 100}%`, top: `${(y(Math.max(columns[hover].closing, ss)) / H) * 100}%` }}>
              <strong>{columns[hover].today ? "Today (on hand)" : fmtDay(columns[hover].day)}</strong>
              <span>Closing {fmtQty(columns[hover].closing, analysis.unit)}</span>
              {columns[hover].receipts > 0 && <span>Receipts +{fmtQty(columns[hover].receipts, analysis.unit)}</span>}
              <span className={columns[hover].below ? "status critical" : "muted"}>
                {columns[hover].below ? `▼ ${fmtQty(ss - columns[hover].closing)} ${unit} under safety stock` : "Above safety stock"}
              </span>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
