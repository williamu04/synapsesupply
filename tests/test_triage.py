from scripted_model import FailingModel

from synapse.agent.triage import triage, triage_rules

SUPPLIERS = ["Riau Fibre Plantations", "Siak Agro Wood", "Jambi Pulpwood Estate"]
PLANTS = {"1100": "Mill Riau-1", "1200": "Mill Jambi-2"}


def test_sc03_utterance():
    t = triage_rules("Order 1,300 tonnes of acacia chips for Mill Riau-1 from Siak Agro Wood, they're the cheapest.",
                     suppliers=SUPPLIERS, plants=PLANTS)
    assert (t.intent, t.supplier_name, t.plant, t.material, t.quantity) == (
        "PURCHASE_REQUEST", "Siak Agro Wood", "1100", "WC-ACACIA", 1300.0)


def test_question_with_plant_code_and_logs():
    t = triage_rules("How many m3 of eucalyptus logs does plant 1200 have?", suppliers=SUPPLIERS, plants=PLANTS)
    assert (t.intent, t.plant, t.material, t.supplier_name, t.quantity) == ("QUESTION", "1200", "LOG-EUCA", None, None)


def test_unclear_request():
    t = triage_rules("hello", suppliers=SUPPLIERS, plants=PLANTS)
    assert t.intent == "OTHER" and t.plant is None


def test_model_failure_falls_back_to_rules():
    t = triage("Buy 500 t chips for Mill Jambi-2", suppliers=SUPPLIERS, plants=PLANTS, model=FailingModel())
    assert t.method == "rules" and t.plant == "1200" and t.quantity == 500
