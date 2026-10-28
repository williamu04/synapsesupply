import avatarDark from "../assets/avatar-dark.svg";
import avatarLight from "../assets/avatar-light.svg";
import { caseTitle } from "../caseSummary";
import type { ThemePref } from "../theme";
import type { CaseRecord } from "../types";
import { ThemeMenu } from "./ThemeMenu";

export type Page = "plan" | "automated" | "escalations" | "statistics";

const NAV: [Page, string][] = [
  ["plan", "Plan"], ["automated", "Automated"], ["escalations", "Escalations"], ["statistics", "Statistics"],
];

export function Sidebar({ active, onNavigate, approvals, openCaseId, onOpenCase, theme, onThemeChange }: {
  active: Page | null;
  onNavigate: (page: Page) => void;
  /** Cases waiting on a planner, newest first. */
  approvals: CaseRecord[];
  openCaseId: string | null;
  onOpenCase: (caseId: string) => void;
  theme: ThemePref;
  onThemeChange: (pref: ThemePref) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">SynSupply</div>
      <nav className="sidebar-body" aria-label="Console">
        <ul className="nav">
          {NAV.map(([page, label]) => (
            <li key={page}>
              <button className={`nav-link ${active === page ? "active" : ""}`}
                      aria-current={active === page ? "page" : undefined} onClick={() => onNavigate(page)}>
                {label}
              </button>
            </li>
          ))}
        </ul>
        <div className="approval-nav">
          <p className="nav-heading">Requiring your approval</p>
          {approvals.length === 0 ? <p className="nav-empty">Nothing is waiting on you.</p> : (
            <ul className="nav nested">
              {approvals.map((c) => (
                <li key={c.case_id}>
                  <button className={`nav-link ${openCaseId === c.case_id ? "active" : ""}`}
                          title={caseTitle(c)} onClick={() => onOpenCase(c.case_id)}>
                    {c.case_id}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </nav>
      <div className="profile">
        <img className="only-light" src={avatarLight} width={32} height={32} alt="" />
        <img className="only-dark" src={avatarDark} width={32} height={32} alt="" />
        <div className="profile-text">
          <span className="profile-name">Synapse Admin</span>
          <span className="profile-role">Admin</span>
        </div>
        <ThemeMenu pref={theme} onChange={onThemeChange} />
      </div>
    </aside>
  );
}
