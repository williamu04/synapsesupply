// SynapseSupply guardrails. Evaluated before every ERP write the agent proposes.
//
// Principals: Synapse::Agent (acting autonomously) and Synapse::Approver (a human planner).
// The engine asks as the Agent first; if that is not permitted it asks as an Approver to decide
// between ESCALATE (a human may approve) and DENY (nobody may).
//
// Context is integer-only so it maps 1:1 onto AgentCore Policy:
//   confidence_bp     plan confidence in basis points (0.90 -> 9000)
//   impact_usd_cents  incremental cost of the action in US cents ($5,000 -> 500000)
//   compliance        PASS | HOLD | BLOCK | NOT_APPLICABLE (stock transfers between own plants)

@id("Policy-ReadPermit")
permit (
  principal,
  action == Synapse::Action::"sap:read",
  resource
);

@id("Policy-WriteGating")
permit (
  principal is Synapse::Agent,
  action in [
    Synapse::Action::"sap:reschedule_po_line",
    Synapse::Action::"sap:create_purchase_order",
    Synapse::Action::"sap:create_stock_transfer"
  ],
  resource
)
when {
  context.confidence_bp >= 9000 &&
  context.impact_usd_cents <= 500000 &&
  (context.compliance == "PASS" || context.compliance == "NOT_APPLICABLE")
};

@id("Policy-HumanApproval")
permit (
  principal is Synapse::Approver,
  action in [
    Synapse::Action::"sap:reschedule_po_line",
    Synapse::Action::"sap:create_purchase_order",
    Synapse::Action::"sap:create_stock_transfer"
  ],
  resource
);

@id("Policy-ForbidDelete")
forbid (
  principal,
  action == Synapse::Action::"sap:delete",
  resource
);

@id("Policy-ComplianceBlock")
forbid (
  principal,
  action in [
    Synapse::Action::"sap:reschedule_po_line",
    Synapse::Action::"sap:create_purchase_order",
    Synapse::Action::"sap:create_stock_transfer"
  ],
  resource
)
when { context.compliance == "BLOCK" };
