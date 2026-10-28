// A section the agent has not produced yet: its title, a skeleton in the shape of what will appear,
// and one line saying what it waits for. The skeleton is decorative; the caption carries the state.

type Shape = "cards" | "chart";

export function PendingPanel({ title, caption, shape }: { title: string; caption: string; shape: Shape }) {
  return (
    <section className="panel pending" aria-busy="true" aria-label={`${title}: ${caption}`}>
      <div className="panel-text">
        <h2 className="panel-title muted-title">{title}</h2>
        <p className="muted">{caption}</p>
      </div>
      {shape === "cards" ? (
        <div className="skeleton-cards" aria-hidden>
          {[0, 1, 2].map((i) => <div key={i} className="inset skeleton-card"><span /><span /><span /></div>)}
        </div>
      ) : (
        <div className="inset skeleton-chart" aria-hidden>
          {[62, 48, 20, 46, 70, 92, 70, 90].map((h, i) => <span key={i} style={{ height: `${h}%` }} />)}
        </div>
      )}
    </section>
  );
}
