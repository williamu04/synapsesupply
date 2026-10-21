import re

import pytest

from synapse.agent.prompts import BASE_PROMPT, SOP_FILES, load_sop, system_prompt
from synapse.agent.toolkit import CaseToolkit
from synapse.contracts import ProcessType

TOOL_NAMES = {"get_case_details", "analyze_stock_position", "find_sourcing_options", "check_supplier_compliance",
              "submit_action", "close_without_action"}


def test_toolkit_exposes_the_documented_tools():
    names = {name for name in dir(CaseToolkit) if name in TOOL_NAMES}
    assert names == TOOL_NAMES


@pytest.mark.parametrize("process_type", list(SOP_FILES))
def test_sops_reference_only_real_tools(process_type):
    sop = load_sop(process_type)
    assert "MUST" in sop and "MUST NOT" in sop
    tool_like = {n for n in re.findall(r"`([a-z_]+)`", sop)
                 if n.startswith(("get_", "analyze_", "find_", "check_", "submit_", "close_"))}
    assert tool_like and tool_like <= TOOL_NAMES
    assert "submit_action" in sop


def test_system_prompt_combines_base_and_sop():
    prompt = system_prompt(ProcessType.ASN_DELAY)
    assert prompt.startswith(BASE_PROMPT) and "SOP-ASN-01" in prompt


def test_sop_override_directory(tmp_path):
    (tmp_path / "asn_delay.md").write_text("# SOP-ASN-02 override")
    assert load_sop(ProcessType.ASN_DELAY, tmp_path) == "# SOP-ASN-02 override"
    assert "SOP-REQ-01" in load_sop(ProcessType.USER_REQUEST, tmp_path)  # falls back to packaged copy


def test_unknown_process_type_has_no_sop():
    with pytest.raises(KeyError):
        load_sop(ProcessType.SUPPLIER_COMPLIANCE_ALERT)


def test_model_providers_setting(monkeypatch):
    from strands.models import BedrockModel

    from synapse.agent import models
    from synapse.agent.config import Settings
    monkeypatch.delenv("AICORE_CLIENT_ID", raising=False)
    monkeypatch.setenv("SYNAPSE_MODEL_PROVIDERS", "aicore")
    with pytest.raises(RuntimeError, match="No usable model provider"):
        models.reasoning_model(Settings())
    monkeypatch.setenv("SYNAPSE_MODEL_PROVIDERS", "bedrock")
    assert isinstance(models.reasoning_model(Settings()), BedrockModel)
