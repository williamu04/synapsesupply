"""The agent's tools for one case.

Design rules:
  * Tools compute; the model decides and explains. Every number the agent can cite comes from a
    tool result (ERP data + the tested domain functions).
  * The only path to an ERP write is `submit_action`, which takes an `option_id` from
    `find_sourcing_options` (no free-form orders) and passes the Cedar policy before anything runs.
  * Every call is traced (TOOL_CALL / TOOL_RESULT / POLICY / ACTION) for the live UI and for audit.

The same methods serve the LLM planner (as Strands tools) and the deterministic autopilot.
"""
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from strands import tool

from synapse.contracts import (
    ActionProposal,
    ActionType,
    CaseMessage,
    CaseStatus,
    GateOutcome,
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
    ProcessType,
    RejectedAlternative,
    TraceKind,
)
from synapse.domain import compliance, inventory, supply
from synapse.domain.delays import (
    DelayEstimate,
    DelayPredictor,
    EmpiricalDelayPredictor,
    delivery_history,
    query_row,
)
from synapse.domain.options import SourcingOption, plan_confidence, sourcing_options
from synapse.erp import ErpClient, ErpError
from synapse.policy.engine import PolicyEngine
from synapse.sap.odata import literal

from .config import Settings
from .trace import Tracer, jsonable

AGENT_PRINCIPAL = "agent:synapse"
_ACTIONS = {
    "PURCHASE_ORDER": (ActionType.CREATE_PURCHASE_ORDER, PolicyAction.CREATE_PURCHASE_ORDER),
    "STOCK_TRANSFER": (ActionType.CREATE_STOCK_TRANSFER, PolicyAction.CREATE_STOCK_TRANSFER),
}


class ToolError(Exception):
    """Returned to the model as a tool error; the message tells it how to recover."""


@dataclass
class Outcome:
    status: CaseStatus
    proposal: ActionProposal | None = None
    decision: PolicyDecision | None = None
    sap_document: str | None = None
    note: str = ""


def round_up(quantity: float, step: float = 10) -> float:
    return math.ceil(quantity / step - 1e-9) * step


def execute(erp: ErpClient, proposal: ActionProposal, created_by: str = "SYNAPSE_AGENT") -> str | None:
    """Carry out an approved proposal in S/4. Returns the document number."""
    p = proposal
    if p.action_type is ActionType.NOTIFY_ONLY:
        return None
    if p.action_type is ActionType.RESCHEDULE_PO_LINE:
        po, item, line = p.reference_document.split("-")
        erp.update("A_PurchaseOrderScheduleLine",
                   {"PurchasingDocument": po, "PurchasingDocumentItem": item, "ScheduleLine": line},
                   {"ScheduleLineDeliveryDate": p.delivery_date})
        return p.reference_document
    header: dict[str, Any] = ({"PurchaseOrderType": "NB", "Supplier": p.supplier}
                              if p.action_type is ActionType.CREATE_PURCHASE_ORDER
                              else {"PurchaseOrderType": "UB", "SupplyingPlant": p.supplying_plant})
    item = {"Material": p.material, "Plant": p.plant, "OrderQuantity": p.quantity,
            "PurchaseOrderQuantityUnit": p.unit,
            "to_ScheduleLine": [{"ScheduleLineDeliveryDate": p.delivery_date, "ScheduleLineOrderQuantity": p.quantity}]}
    created = erp.create("A_PurchaseOrder", header | {"CreatedByUser": created_by[:12], "to_PurchaseOrderItem": [item]})
    return created["PurchaseOrder"]


class CaseToolkit:
    def __init__(self, case: CaseMessage, erp: ErpClient, policy: PolicyEngine, tracer: Tracer, today: date,
                 settings: Settings | None = None, delay_predictor: DelayPredictor | None = None):
        self.case, self.erp, self.policy, self.tracer, self.today = case, erp, policy, tracer, today
        self.settings = settings or Settings()
        self.delay_predictor = delay_predictor or EmpiricalDelayPredictor()
        self._delays: dict[str, DelayEstimate] = {}
        self.details: dict | None = None
        self.analyses: dict[tuple[str, str], dict] = {}
        self.options: dict[str, SourcingOption] = {}
        self._option_context: dict[str, tuple[str, str, float]] = {}
        self.outcome: Outcome | None = None

    @property
    def tools(self) -> list:
        return [self.get_case_details, self.analyze_stock_position, self.find_sourcing_options,
                self.check_supplier_compliance, self.submit_action, self.close_without_action]

    # --- tools (docstrings are the model-facing descriptions) ------------------------------------

    @tool
    def get_case_details(self) -> dict:
        """Read the case being handled: what triggered it and the ERP documents involved.

        Call this first. For a delayed delivery (ASN_DELAY) it returns the purchase order, supplier,
        plant, material, the scheduled and the newly announced delivery date, the delay in days and
        any carrier notice. For a buyer request (USER_REQUEST) it returns the request text and its
        triage (supplier, plant, material, quantity). Always includes today's business date.
        """
        return self._run("get_case_details", {}, self._case_details)

    @tool
    def analyze_stock_position(self, plant: str, material: str) -> dict:
        """Compute the stock position of one material at one plant from ERP data.

        Returns unrestricted stock on hand, daily demand and lead-time statistics from history,
        safety stock (95% service level), reorder point with the inventory position it applies to
        (on hand + open inbound; below_reorder_point), EOQ, a 7-day projection including all open
        purchase orders and announced deliveries, the first day stock falls below safety stock
        (first_breach_day, or null) and the shortfall: the quantity needed to stay at or above safety
        stock on every projected day.

        Args:
            plant: Plant code, e.g. "1100".
            material: Material number, e.g. "WC-ACACIA".
        """
        return self._run("analyze_stock_position", {"plant": plant, "material": material},
                         lambda: self._analysis(plant, material))

    @tool
    def find_sourcing_options(self, plant: str, material: str, quantity: float, needed_by: str) -> dict:
        """List every way to bring `quantity` of a material to a plant, with arrival, cost and compliance.

        Options are purchase orders from suppliers with a purchasing info record, and stock transfers
        from other plants that can spare the stock without falling below their own safety stock.
        Each option has an option_id, earliest_arrival, arrives_in_time (by needed_by), unit and
        incremental cost versus the original order price, max_quantity (transfers), for purchase orders
        a delivery-risk prediction from SAP RPT-1 (on_time_probability, predicted_delay_days), and the EUDR
        compliance gate result: PASS, HOLD (needs human review), BLOCK (must not be used) or
        NOT_APPLICABLE (own-plant transfer). Options are sorted best first.

        Args:
            plant: Receiving plant code.
            material: Material number.
            quantity: Quantity needed, in the material's base unit.
            needed_by: Latest acceptable arrival date, ISO format YYYY-MM-DD.
        """
        args = {"plant": plant, "material": material, "quantity": quantity, "needed_by": needed_by}
        return self._run("find_sourcing_options", args, lambda: self._options(plant, material, quantity, needed_by))

    @tool
    def check_supplier_compliance(self, supplier: str, quantity: float) -> dict:
        """Run the EUDR / certification compliance gate for one supplier.

        Checks certificate validity, deforestation alerts after the EUDR cut-off, plot geolocation,
        risk band and its freshness, and whether the volume is plausible against declared capacity.

        Args:
            supplier: Supplier number (e.g. "0000100003") or supplier name (e.g. "Siak Agro Wood").
            quantity: Quantity that would be sourced from this supplier.
        """
        return self._run("check_supplier_compliance", {"supplier": supplier, "quantity": quantity},
                         lambda: self._compliance(supplier, quantity))

    @tool
    def submit_action(self, option_id: str, quantity: float, rationale: str,
                      rejected_alternatives: list[dict] | None = None) -> dict:
        """Submit the chosen option for policy evaluation and, if permitted, execution in SAP S/4HANA.

        Call exactly once per case. The policy decides: ALLOW executes immediately; ESCALATE sends it
        to a human planner for approval in SAP Joule; DENY blocks it. Confidence and financial impact
        are computed from the option and the stock analysis, not supplied by you.

        Args:
            option_id: An option_id returned by find_sourcing_options.
            quantity: Quantity to order or transfer; must cover the shortfall and not exceed max_quantity.
            rationale: Why this option, in two or three sentences a planner can audit.
            rejected_alternatives: Every other option you considered, as objects with "option_id" and "reason".
        """
        args = {"option_id": option_id, "quantity": quantity, "rationale": rationale,
                "rejected_alternatives": rejected_alternatives or []}
        return self._run("submit_action", args,
                         lambda: self._submit(option_id, quantity, rationale, rejected_alternatives or []))

    @tool
    def close_without_action(self, reason: str) -> dict:
        """Close the case without any ERP change.

        Only for a delay that keeps stock at or above safety stock over the whole projection, or for a
        buyer request that is a question rather than a purchase.

        Args:
            reason: Why no action is needed, citing the projected minimum stock and safety stock.
        """
        return self._run("close_without_action", {"reason": reason}, lambda: self._close(reason))

    # --- implementation -------------------------------------------------------------------------

    def _run(self, name: str, args: dict, fn: Callable[[], dict]) -> dict:
        self.tracer.emit(TraceKind.TOOL_CALL, name, **args)
        try:
            result = jsonable(fn())
        except ToolError as e:
            self.tracer.emit(TraceKind.ERROR, f"{name} rejected", message=str(e))
            raise
        except ErpError as e:
            self.tracer.emit(TraceKind.ERROR, f"{name}: ERP error", status=e.status, message=e.message)
            raise ToolError(f"ERP error {e.status}: {e.message}") from e
        self.tracer.emit(TraceKind.TOOL_RESULT, name, **result)
        return result

    def _case_details(self) -> dict:
        base = {"case_id": self.case.case_id, "process_type": self.case.process_type.value, "today": self.today}
        raw = self.case.raw_payload
        if self.case.process_type is not ProcessType.ASN_DELAY:
            self.details = base | {"utterance": raw.get("utterance"), "triage": raw.get("triage")}
            return self.details

        po, item = self.case.case_id.rsplit("-", 1)
        row = self.erp.get("A_PurchaseOrderItem", {"PurchaseOrder": po, "PurchaseOrderItem": item},
                           expand="to_ScheduleLine,to_PurchaseOrder")
        if row is None:
            raise ToolError(f"Purchase order item {po}/{item} not found in S/4")
        supplier = row["to_PurchaseOrder"]["Supplier"]
        profile = self.erp.get("SupplierCompliance", {"Supplier": supplier}) or {}
        asn_items = self.erp.read("A_InbDeliveryItem", filter=(
            f"ReferenceSDDocument eq {literal(po)} and ReferenceSDDocumentItem eq {literal(item)}"))
        asns = [self.erp.get("A_InbDeliveryHeader", {"DeliveryDocument": a["DeliveryDocument"]}) for a in asn_items]
        scheduled = min(s["ScheduleLineDeliveryDate"] for s in row["to_ScheduleLine"])
        announced = max((h["DeliveryDate"] for h in asns if h), default=scheduled)
        self.details = base | {
            "purchase_order": po, "item": item, "supplier": supplier,
            "supplier_name": profile.get("SupplierName", supplier), "plant": row["Plant"],
            "material": row["Material"], "unit": row["PurchaseOrderQuantityUnit"],
            "ordered_quantity": row["OrderQuantity"], "net_price": row["NetPriceAmount"],
            "currency": row["DocumentCurrency"],
            "scheduled_delivery": scheduled, "announced_delivery": announced,
            "delay_days": (announced - scheduled).days,
            "inbound_deliveries": [a["DeliveryDocument"] for a in asn_items],
            "carrier_notice": raw.get("carrier_notice"),
        }
        return self.details

    def _analysis(self, plant: str, material: str) -> dict:
        key = (plant, material)
        if key in self.analyses:
            return self.analyses[key]
        s, today = self.settings, self.today
        since = today - timedelta(days=s.history_days)
        pm = f"Plant eq {literal(plant)} and Material eq {literal(material)}"
        stock = self.erp.read("A_MatlStkInAcctMod", filter=pm)
        docs = self.erp.read("A_MaterialDocumentItem", filter=f"{pm} and PostingDate ge {literal(since)}")
        pos = self.erp.read("A_PurchaseOrder", filter=f"PurchaseOrderDate ge {literal(since - timedelta(days=30))}",
                            select=["PurchaseOrder", "PurchaseOrderDate", "Supplier"])
        open_items = self.erp.read("A_PurchaseOrderItem", filter=f"{pm} and IsCompletelyDelivered eq false",
                                   expand="to_ScheduleLine")
        asn_headers = self.erp.read("A_InbDeliveryHeader", filter=f"ReceivingPlant eq {literal(plant)}",
                                    expand="to_DeliveryDocumentItem")

        consumption = supply.daily_consumption(docs, plant, material, since, today - timedelta(days=1))
        lead_samples = supply.lead_times(pos, docs, plant, material)
        if sum(consumption) == 0 or len(lead_samples) < 2:
            raise ToolError(f"Not enough history for {material} at plant {plant} to compute safety stock")
        demand, lead = inventory.series_stats(consumption), inventory.series_stats(lead_samples)
        ss = inventory.safety_stock(inventory.z_for_service_level(s.service_level), lead.mean, demand.sd,
                                    demand.mean, lead.sd)
        on_hand = supply.unrestricted_stock(stock, plant, material)
        receipts = supply.expected_receipts(
            open_items, [sl for i in open_items for sl in i.get("to_ScheduleLine", [])], asn_headers,
            [it for h in asn_headers for it in h.get("to_DeliveryDocumentItem", [])], plant, material)
        projection = inventory.project_stock(on_hand, receipts, demand.mean, today, s.horizon_days)
        breach = inventory.first_breach(projection, ss)
        prices = [float(i["NetPriceAmount"]) for i in open_items if i["NetPriceAmount"]]
        eoq = (inventory.eoq(demand.mean * 365, s.order_cost_usd, s.holding_cost_rate * (sum(prices) / len(prices)))
               if prices else None)
        lowest = min(p.closing for p in projection)
        rop = inventory.reorder_point(demand.mean, lead.mean, ss)
        open_inbound = sum(receipts.values())
        unit = (stock or docs or [{"MaterialBaseUnit": ""}])[0]["MaterialBaseUnit"]
        self.analyses[key] = {
            "plant": plant, "material": material, "unit": unit, "today": today,
            "on_hand_unrestricted": on_hand,
            "other_stock_not_available": sum(float(r["MatlWrhsStkQtyInMatlBaseUnit"]) for r in stock) - on_hand,
            "daily_demand_mean": round(demand.mean, 1), "daily_demand_sd": round(demand.sd, 1),
            "demand_samples": demand.n, "lead_time_mean_days": round(lead.mean, 2),
            "lead_time_sd_days": round(lead.sd, 2), "lead_time_samples": lead.n,
            "service_level": s.service_level, "safety_stock": round(ss, 1),
            "reorder_point": round(rop, 1),
            # A reorder point is compared with the inventory position (on hand + open inbound),
            # not with on-hand stock alone: stock already on order covers the lead time.
            "open_inbound": round(open_inbound, 1),
            "inventory_position": round(on_hand + open_inbound, 1),
            "below_reorder_point": on_hand + open_inbound < rop,
            "eoq": round(eoq, 0) if eoq else None,
            "projection": [{"day": p.day, "receipts": p.receipts, "closing": round(p.closing, 1),
                            "below_safety_stock": p.closing < ss} for p in projection],
            "projected_minimum": round(lowest, 1),
            "first_breach_day": breach.day if breach else None,
            "days_until_breach": (breach.day - today).days if breach else None,
            "shortfall": round(inventory.shortfall(projection, ss), 1),
            "status": "STOCKOUT" if lowest < 0 else "BELOW_SAFETY_STOCK" if breach else "OK",
        }
        return self.analyses[key]

    def _options(self, plant: str, material: str, quantity: float, needed_by: str) -> dict:
        try:
            needed = date.fromisoformat(needed_by)
        except ValueError:
            raise ToolError(f"needed_by must be YYYY-MM-DD, got {needed_by!r}") from None
        if quantity <= 0:
            raise ToolError("quantity must be positive")
        pm = f"Plant eq {literal(plant)} and Material eq {literal(material)}"
        infos = self.erp.read("A_PurchasingInfoRecord", filter=pm)
        profiles = {p["Supplier"]: p for p in self.erp.read("SupplierCompliance")}
        lanes = self.erp.read("TransportLane", filter=f"ToPlant eq {literal(plant)} and Material eq {literal(material)}")
        donor_spare = {}
        for lane in lanes:
            donor = self._analysis(lane["FromPlant"], material)
            donor_spare[lane["FromPlant"]] = donor["projected_minimum"] - donor["safety_stock"]
        baseline = self._baseline_price(plant, material, infos, profiles)
        options = sourcing_options(plant=plant, material=material, quantity=quantity, needed_by=needed,
                                   today=self.today, baseline_price=baseline, info_records=infos,
                                   compliance_profiles=profiles, lanes=lanes, donor_spare=donor_spare,
                                   plant_names=self.settings.plant_names)
        for o in options:
            self.options[o.option_id] = o
            self._option_context[o.option_id] = (plant, material, quantity)
        prediction = self._predict_delays(plant, material, quantity, options)
        return {"plant": plant, "material": material, "quantity": quantity, "needed_by": needed,
                "currency": "USD", "baseline_price": baseline, "delay_prediction": prediction,
                "options": [self._option_view(o, quantity, self._delays.get(o.option_id)) for o in options]}

    def _predict_delays(self, plant: str, material: str, quantity: float, options: list[SourcingOption]) -> dict:
        """Delivery risk for each candidate purchase order (SAP RPT-1, empirical fallback). Own-plant
        transfers run on the company's trucks and are not predicted."""
        candidates = [o for o in options if o.kind == "PURCHASE_ORDER"]
        if not candidates:
            return {"method": None, "history_rows": 0}
        since = self.today - timedelta(days=self.settings.history_days)
        # Every supplier's record across plants and materials: reliability is mostly a supplier trait.
        items = self.erp.read("A_PurchaseOrderItem", filter="IsCompletelyDelivered eq true", expand="to_ScheduleLine")
        pos = self.erp.read("A_PurchaseOrder", filter=f"PurchaseOrderDate ge {literal(since - timedelta(days=30))}",
                            select=["PurchaseOrder", "PurchaseOrderDate", "Supplier"])
        docs = self.erp.read("A_MaterialDocumentItem",
                             filter=f"GoodsMovementType eq '101' and PostingDate ge {literal(since)}")
        history = delivery_history(pos, items, docs)
        queries = [query_row(supplier=o.source, plant=plant, material=material, lead_days=o.lead_days,
                             quantity=quantity, arrival=o.earliest_arrival) for o in candidates]
        self.tracer.emit(TraceKind.TOOL_CALL, "predict_delivery_delay", model=self.delay_predictor.method,
                         history_rows=len(history), suppliers=[o.source for o in candidates])
        estimates = self.delay_predictor.predict(history, queries)
        for o, e in zip(candidates, estimates, strict=True):
            self._delays[o.option_id] = e
        method = estimates[0].method if estimates else self.delay_predictor.method
        self.tracer.emit(TraceKind.TOOL_RESULT, "predict_delivery_delay", method=method, predictions={
            o.option_id: {"expected_delay_days": e.expected_delay_days, "on_time_probability": e.on_time_probability}
            for o, e in zip(candidates, estimates, strict=True)})
        return {"method": method, "history_rows": len(history)}

    def _baseline_price(self, plant: str, material: str, infos: list[dict], profiles: dict) -> float:
        d = self.details or {}
        if d.get("plant") == plant and d.get("material") == material and d.get("net_price") is not None:
            return float(d["net_price"])
        passing = [float(r["NetPriceAmount"]) for r in infos
                   if compliance.outcome(compliance.evaluate(profiles.get(r["Supplier"]), 0, self.today)) == "PASS"]
        prices = passing or [float(r["NetPriceAmount"]) for r in infos]
        return min(prices) if prices else 0.0

    @staticmethod
    def _option_view(o: SourcingOption, quantity: float, delay: DelayEstimate | None = None) -> dict:
        qty = quantity if o.max_quantity is None else min(quantity, o.max_quantity)
        risk = {} if delay is None else {
            "predicted_delay_days": delay.expected_delay_days, "on_time_probability": delay.on_time_probability,
            "expected_arrival": o.earliest_arrival + timedelta(days=round(delay.expected_delay_days)),
            "prediction_method": delay.method}
        return risk | {"option_id": o.option_id, "kind": o.kind, "source": o.source, "source_name": o.source_name,
                "earliest_arrival": o.earliest_arrival, "arrives_in_time": o.arrives_in_time,
                "lead_days": o.lead_days, "unit_cost": o.unit_cost,
                "incremental_cost_per_unit": o.incremental_cost_per_unit,
                "incremental_cost_for_quantity": o.incremental_cost(qty), "max_quantity": o.max_quantity,
                "covers_quantity": o.max_quantity is None or o.max_quantity >= quantity,
                "compliance": o.compliance, "compliance_findings": o.compliance_findings}

    def _compliance(self, supplier: str, quantity: float) -> dict:
        profiles = self.erp.read("SupplierCompliance")
        matches = [p for p in profiles if p["Supplier"] == supplier] or [
            p for p in profiles if supplier.strip().lower() in p["SupplierName"].lower()]
        if len(matches) != 1:
            names = ", ".join(f"{p['Supplier']} {p['SupplierName']}" for p in (matches or profiles))
            raise ToolError(f"Supplier {supplier!r} is {'ambiguous' if matches else 'unknown'}. Candidates: {names}")
        p = matches[0]
        checks = compliance.evaluate(p, quantity, self.today)
        return {"supplier": p["Supplier"], "supplier_name": p["SupplierName"],
                "outcome": compliance.outcome(checks),
                "checks": [{"code": c.code, "passed": c.passed, "severity": c.severity, "detail": c.detail}
                           for c in checks]}

    def _submit(self, option_id: str, quantity: float, rationale: str, rejected: list[dict]) -> dict:
        if self.outcome is not None:
            raise ToolError(f"This case is already decided ({self.outcome.status.value}); do not submit again")
        option = self.options.get(option_id)
        if option is None:
            raise ToolError(f"Unknown option_id {option_id!r}. Call find_sourcing_options first; "
                            f"known options: {sorted(self.options) or 'none'}")
        plant, material, _ = self._option_context[option_id]
        if quantity <= 0:
            raise ToolError("quantity must be positive")
        if option.max_quantity is not None and quantity > option.max_quantity + 1e-9:
            raise ToolError(f"{option_id} can supply at most {option.max_quantity}")
        analysis = self._analysis(plant, material)
        confidence = plan_confidence(
            covers_shortfall=quantity + 1e-9 >= analysis["shortfall"], arrives_in_time=option.arrives_in_time,
            demand_samples=analysis["demand_samples"], lead_time_samples=analysis["lead_time_samples"],
            erp_degraded=self.erp.degraded,
            late_risk=self._delays[option_id].late_probability if option_id in self._delays else None)
        action_type, policy_action = _ACTIONS[option.kind]
        gate = None if option.compliance == "NOT_APPLICABLE" else GateOutcome(option.compliance)
        alternatives = []
        for alt in rejected:
            alt_id = str(alt.get("option_id") or alt.get("description") or "")
            known = self.options.get(alt_id)
            reason = str(alt.get("reason", ""))
            if known and known.compliance in ("BLOCK", "HOLD"):
                # Compliance facts come from the gate, never from the model's paraphrase.
                reason = f"{known.compliance}: " + "; ".join(f.split(": ", 1)[-1] for f in known.compliance_findings)
            alternatives.append(RejectedAlternative(
                description=alt_id or "unspecified", reason=reason,
                compliance_outcome=GateOutcome(known.compliance) if known and known.compliance != "NOT_APPLICABLE"
                else None,
                financial_impact_usd=known.incremental_cost(quantity) if known else None))
        proposal = ActionProposal(
            action_type=action_type, plant=plant, material=material, quantity=quantity,
            unit=analysis["unit"], delivery_date=option.earliest_arrival,
            supplier=option.source if option.kind == "PURCHASE_ORDER" else None,
            supplying_plant=option.source if option.kind == "STOCK_TRANSFER" else None,
            financial_impact_usd=option.incremental_cost(quantity), confidence=confidence,
            compliance_outcome=gate, rationale=rationale, alternatives=alternatives, option_id=option_id)
        request = PolicyRequest(principal=AGENT_PRINCIPAL, action=policy_action, resource="A_PurchaseOrder",
                                context=PolicyContext(confidence=confidence,
                                                      financial_impact_usd=proposal.financial_impact_usd,
                                                      compliance_outcome=gate))
        decision = self.policy.decide(request)
        self.tracer.emit(TraceKind.POLICY, f"Cedar: {decision.effect.value}", effect=decision.effect.value,
                         policy_ids=decision.policy_ids, reasons=decision.reasons, confidence=confidence,
                         financial_impact_usd=proposal.financial_impact_usd,
                         compliance=option.compliance, option_id=option_id)

        document = None
        if decision.effect is PolicyEffect.ALLOW:
            document = execute(self.erp, proposal)
            self.tracer.emit(TraceKind.ACTION, f"Created {action_type.value} {document} in S/4",
                             sap_document=document, degraded_erp=self.erp.degraded)
            status = CaseStatus.EXECUTED
        elif decision.effect is PolicyEffect.ESCALATE:
            status = CaseStatus.AWAITING_APPROVAL
            self.tracer.emit(TraceKind.APPROVAL, "Approval requested from a planner (SAP Joule)",
                             reasons=decision.reasons)
        else:
            status = CaseStatus.BLOCKED
        self.outcome = Outcome(status=status, proposal=proposal, decision=decision, sap_document=document)
        return {"decision": decision.effect.value, "status": status.value, "reasons": decision.reasons, "currency": "USD",
                "policy_ids": decision.policy_ids, "sap_document": document,
                "alternatives": [{"option_id": a.description, "reason": a.reason} for a in alternatives], "confidence": confidence,
                "financial_impact_usd": proposal.financial_impact_usd, "delivery_date": proposal.delivery_date}

    def _close(self, reason: str) -> dict:
        if self.outcome is not None:
            raise ToolError(f"This case is already decided ({self.outcome.status.value})")
        if self.case.process_type is ProcessType.ASN_DELAY:
            d = self.details or {}
            analysis = self.analyses.get((d.get("plant"), d.get("material")))
            if analysis is None:
                raise ToolError("Call get_case_details and analyze_stock_position for the case before closing it")
            if analysis["first_breach_day"] is not None:
                raise ToolError(f"Cannot close: stock falls below safety stock on {analysis['first_breach_day']} "
                                f"(shortfall {analysis['shortfall']}). Submit an action instead.")
        self.outcome = Outcome(status=CaseStatus.NO_ACTION_NEEDED, note=reason)
        return {"status": CaseStatus.NO_ACTION_NEEDED.value}
