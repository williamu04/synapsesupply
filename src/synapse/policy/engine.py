"""Cedar policy evaluation for proposed ERP actions.

Cedar answers Allow/Deny. We need three outcomes, so we ask twice:

  1. as the Agent  -> Allow                     => ALLOW    (execute autonomously)
  2. as a planner  -> Allow                     => ESCALATE (a human may approve)
                   -> Deny                      => DENY     (forbidden for everyone)

Locally this runs on `cedarpy` (the Rust Cedar engine). In AWS the same policy file is attached to
the AgentCore Gateway's policy engine; entity and action names may need mapping to the names
AgentCore generates for the gateway's tools — check that when wiring the gateway.
"""
import json
import re
from importlib.resources import files

import cedarpy

from synapse.contracts import (
    AUTO_EXECUTE_MAX_IMPACT_USD,
    AUTO_EXECUTE_MIN_CONFIDENCE,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
)

AGENT = 'Synapse::Agent::"synapse-agent"'
ANY_APPROVER = 'Synapse::Approver::"planner"'
_STATEMENT = re.compile(r"^\s*(permit|forbid)\s*\(", re.MULTILINE)
_ID = re.compile(r'@id\("([^"]+)"\)')


class PolicyError(RuntimeError):
    pass


def _load(name: str) -> str:
    return files("synapse.policy").joinpath(name).read_text()


class PolicyEngine:
    def __init__(self, policies: str | None = None, schema: str | None = None):
        self.policies = policies or _load("synapse.cedar")
        self.schema = json.loads(schema or _load("synapse.cedarschema.json"))
        ids = _ID.findall(self.policies)
        if len(ids) != len(_STATEMENT.findall(self.policies)):
            raise PolicyError("every Cedar policy needs an @id annotation")
        self._ids = {f"policy{n}": pid for n, pid in enumerate(ids)}  # cedarpy numbers policies in file order
        result = cedarpy.validate_policies(self.policies, self.schema)
        if not result.validation_passed:
            raise PolicyError(f"Cedar policies do not validate against the schema: {result.errors}")

    def decide(self, request: PolicyRequest, principal: str | None = None) -> PolicyDecision:
        """principal=None: evaluate as the agent (three-way outcome). Otherwise evaluate as that
        human approver: ALLOW or DENY only."""
        if principal is not None:
            allowed, ids = self._authorize(f'Synapse::Approver::"{_escape(principal)}"', request)
            effect = PolicyEffect.ALLOW if allowed else PolicyEffect.DENY
            return PolicyDecision(effect=effect, policy_ids=ids, reasons=self._deny_reasons(request) if not allowed else
                                  [f"Approved by {principal}"])

        allowed, ids = self._authorize(AGENT, request)
        if allowed:
            reason = ("Read access" if request.action.value == "sap:read"
                      else "Within autonomous limits: confidence, financial impact and compliance")
            return PolicyDecision(effect=PolicyEffect.ALLOW, policy_ids=ids, reasons=[reason])
        if ids:  # a forbid matched for the agent itself: nobody can approve this
            return PolicyDecision(effect=PolicyEffect.DENY, policy_ids=ids, reasons=self._deny_reasons(request))
        human_allowed, human_ids = self._authorize(ANY_APPROVER, request)
        if human_allowed:
            return PolicyDecision(effect=PolicyEffect.ESCALATE, policy_ids=["Policy-WriteGating", *human_ids],
                                  reasons=self._escalation_reasons(request))
        return PolicyDecision(effect=PolicyEffect.DENY, policy_ids=human_ids, reasons=self._deny_reasons(request))

    def _authorize(self, principal: str, request: PolicyRequest) -> tuple[bool, list[str]]:
        ctx = request.context
        context = {} if request.action.value in ("sap:read", "sap:delete") else {
            "confidence_bp": round(ctx.confidence * 10_000),
            "impact_usd_cents": round(ctx.financial_impact_usd * 100),
            "compliance": ctx.compliance_outcome.value if ctx.compliance_outcome else "NOT_APPLICABLE",
        }
        result = cedarpy.is_authorized({
            "principal": principal, "action": f'Synapse::Action::"{request.action.value}"',
            "resource": f'Synapse::EntitySet::"{_escape(request.resource)}"', "context": context,
        }, self.policies, [], schema=self.schema)
        if result.diagnostics.errors:
            raise PolicyError(f"Cedar evaluation error: {result.diagnostics.errors}")
        return result.allowed, [self._ids.get(r, r) for r in result.diagnostics.reasons]

    @staticmethod
    def _escalation_reasons(request: PolicyRequest) -> list[str]:
        c, reasons = request.context, []
        if c.confidence < AUTO_EXECUTE_MIN_CONFIDENCE:
            reasons.append(f"Plan confidence {c.confidence:.2f} is below the {AUTO_EXECUTE_MIN_CONFIDENCE:.2f} "
                           "autonomous threshold")
        if c.financial_impact_usd > AUTO_EXECUTE_MAX_IMPACT_USD:
            reasons.append(f"Financial impact ${c.financial_impact_usd:,.0f} exceeds the "
                           f"${AUTO_EXECUTE_MAX_IMPACT_USD:,.0f} autonomous limit")
        if c.compliance_outcome and c.compliance_outcome.value == "HOLD":
            reasons.append("Supplier compliance is on HOLD and needs human review of the evidence")
        return reasons or ["Not within autonomous limits"]

    @staticmethod
    def _deny_reasons(request: PolicyRequest) -> list[str]:
        if request.action.value == "sap:delete":
            return ["Deleting ERP records is never permitted"]
        c = request.context
        if c.compliance_outcome and c.compliance_outcome.value == "BLOCK":
            return ["Supplier is BLOCKED by the EUDR compliance gate; no one may source from it"]
        return ["Not permitted by policy"]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
