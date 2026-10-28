import type { ReactNode } from "react";

/** "SynapseSupply Console" bar above every page except Plan, with connection badges on the right. */
export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="page-header">
      <p className="wordmark"><strong>SynapseSupply</strong> Console</p>
      <div className="header-right">{children}</div>
    </header>
  );
}
