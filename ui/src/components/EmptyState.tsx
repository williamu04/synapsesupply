import type { ReactNode } from "react";

/** A page or list with nothing to show: what is missing, why, and where to go instead. */
export function EmptyState({ title, children, action }: {
  title: string;
  children: ReactNode;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <section className="panel empty-state">
      <h2 className="panel-title">{title}</h2>
      <p>{children}</p>
      {action && <button className="btn btn-filled" onClick={action.onClick}>{action.label}</button>}
    </section>
  );
}
