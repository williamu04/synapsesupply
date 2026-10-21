"""Triage of free-text requests (Joule utterances, carrier e-mails) into a structured request.

The small model does this when it is reachable; a rule-based parser covers the demo fail-safe and
keeps triage working without any model. Either way, nothing here can act — triage only routes.
"""
import logging
import re
from typing import Literal

from pydantic import BaseModel
from strands import Agent
from strands.models import Model

log = logging.getLogger(__name__)

MATERIAL_KEYWORDS = {"chip": "WC-ACACIA", "acacia": "WC-ACACIA", "log": "LOG-EUCA", "eucalyptus": "LOG-EUCA"}
_QTY = re.compile(r"(\d[\d,.]*)\s*(?:t\b|tonnes?|tons?|m3|m³|cubic)", re.IGNORECASE)
_PURCHASE = re.compile(r"\b(order|buy|purchase|source|procure|get)\b", re.IGNORECASE)


class TriageResult(BaseModel):
    intent: Literal["PURCHASE_REQUEST", "QUESTION", "OTHER"]
    supplier_name: str | None = None
    plant: str | None = None
    material: str | None = None
    quantity: float | None = None
    method: Literal["model", "rules"] = "rules"


def triage(text: str, *, suppliers: list[str], plants: dict[str, str], model: Model | None = None) -> TriageResult:
    """suppliers: known supplier names; plants: plant code -> plant name."""
    if model is not None:
        try:
            return _triage_with_model(text, suppliers, plants, model)
        except Exception as e:  # noqa: BLE001 — any model failure falls back to rules; triage must not block a case
            log.warning("model triage failed, using rules: %s", e)
    return triage_rules(text, suppliers=suppliers, plants=plants)


def _triage_with_model(text: str, suppliers: list[str], plants: dict[str, str], model: Model) -> TriageResult:
    prompt = (
        "Extract the request below into the schema. Use only these values: suppliers "
        f"{suppliers}; plants {plants} (answer with the code); materials WC-ACACIA (acacia wood chips) "
        "or LOG-EUCA (eucalyptus logs). Leave a field empty if the request does not say.\n\n"
        f"Request: {text}")
    agent = Agent(model=model, callback_handler=None, structured_output_model=TriageResult)
    result = agent(prompt).structured_output
    if not isinstance(result, TriageResult):
        raise TypeError("model returned no structured output")
    return result.model_copy(update={"method": "model"})


def triage_rules(text: str, *, suppliers: list[str], plants: dict[str, str]) -> TriageResult:
    lowered = text.lower()
    supplier = next((s for s in suppliers if s.lower() in lowered), None)
    plant = next((code for code, name in plants.items() if name.lower() in lowered or re.search(rf"\b{code}\b", text)),
                 None)
    material = next((m for kw, m in MATERIAL_KEYWORDS.items() if kw in lowered), None)
    qty = _QTY.search(text)
    quantity = float(qty.group(1).replace(",", "")) if qty else None
    intent = "PURCHASE_REQUEST" if _PURCHASE.search(text) else "QUESTION" if "?" in text else "OTHER"
    return TriageResult(intent=intent, supplier_name=supplier, plant=plant, material=material, quantity=quantity)
