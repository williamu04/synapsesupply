import pytest

from synapse.contracts import PolicyEffect, PolicyRequest
from synapse.policy.engine import PolicyEngine, PolicyError, _load

ENGINE = PolicyEngine()


def req(action="sap:create_purchase_order", confidence=0.95, impact=1_000.0, compliance="PASS"):
    return PolicyRequest(principal="agent:synapse", action=action, resource="A_PurchaseOrder",
                         context={"confidence": confidence, "financial_impact_usd": impact,
                                  "compliance_outcome": compliance})


@pytest.mark.parametrize("kw, effect, policy", [
    ({}, "ALLOW", "Policy-WriteGating"),
    ({"action": "sap:create_stock_transfer", "compliance": None}, "ALLOW", "Policy-WriteGating"),
    ({"action": "sap:reschedule_po_line"}, "ALLOW", "Policy-WriteGating"),
    ({"confidence": 0.90, "impact": 5_000.0}, "ALLOW", "Policy-WriteGating"),  # boundaries are inclusive
    ({"confidence": 0.8999}, "ESCALATE", "Policy-HumanApproval"),
    ({"impact": 5_000.01}, "ESCALATE", "Policy-HumanApproval"),
    ({"compliance": "HOLD"}, "ESCALATE", "Policy-HumanApproval"),
    ({"compliance": "BLOCK"}, "DENY", "Policy-ComplianceBlock"),
    ({"compliance": "BLOCK", "impact": 1_000_000.0, "confidence": 0.1}, "DENY", "Policy-ComplianceBlock"),
    ({"action": "sap:delete"}, "DENY", "Policy-ForbidDelete"),
    ({"action": "sap:read"}, "ALLOW", "Policy-ReadPermit"),
])
def test_agent_decisions(kw, effect, policy):
    d = ENGINE.decide(req(**kw))
    assert d.effect == PolicyEffect(effect)
    assert policy in d.policy_ids
    assert d.reasons


def test_escalation_reasons_name_every_failed_limit():
    reasons = " ".join(ENGINE.decide(req(confidence=0.5, impact=9_000.0, compliance="HOLD")).reasons)
    assert "0.50" in reasons and "$9,000" in reasons and "HOLD" in reasons


@pytest.mark.parametrize("kw, effect", [
    ({"impact": 50_000.0}, "ALLOW"),
    ({"compliance": "HOLD", "confidence": 0.2}, "ALLOW"),
    ({"compliance": "BLOCK"}, "DENY"),
    ({"action": "sap:delete"}, "DENY"),
])
def test_human_approver(kw, effect):
    d = ENGINE.decide(req(**kw), principal='Dewi "the planner"')  # quotes must not break the entity id
    assert d.effect == PolicyEffect(effect)


def test_policies_must_validate_against_schema():
    bad = _load("synapse.cedar").replace("context.confidence_bp", "context.confidence_pct", 1)
    with pytest.raises(PolicyError, match="schema"):
        PolicyEngine(policies=bad)


def test_every_policy_needs_an_id():
    with pytest.raises(PolicyError, match="@id"):
        PolicyEngine(policies=_load("synapse.cedar") + '\npermit (principal, action, resource);\n')
