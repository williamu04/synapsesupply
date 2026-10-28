import type { PolicyDetail } from "../types";

const EFFECT = { ALLOW: "Allowed: the agent acts alone", ESCALATE: "Escalated to a planner", DENY: "Denied for everyone" };

/** "Cedar Policy": the decision and the policies that produced it. */
export function PolicyCard({ policy }: { policy: PolicyDetail }) {
  return (
    <section className="inset policy-card" aria-labelledby="policy-title">
      <p id="policy-title" className="label-strong">Cedar Policy</p>
      <p className="small">{EFFECT[policy.effect]}</p>
      <ul className="policy-list">{policy.policy_ids.map((id) => <li key={id}>{id}</li>)}</ul>
    </section>
  );
}
