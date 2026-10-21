"""System prompt and the SOP "skill router": one SOP per process type, loaded at case start.

In AWS the SOP files live in S3 (versioned) so operations can change a rule without a deploy; the
loader takes an override directory for that. The packaged copies are the reviewed defaults.
"""
from importlib.resources import files
from pathlib import Path

from synapse.contracts import ProcessType

SOP_FILES = {
    ProcessType.ASN_DELAY: "asn_delay.md",
    ProcessType.USER_REQUEST: "user_request.md",
}

BASE_PROMPT = """\
You are SynapseSupply, an operations agent for the wood-fibre supply of pulp mills. You work inside
the company's SAP S/4HANA landscape through tools, on behalf of the supply planning team.

Always:
- Tools are your only source of facts. Never estimate or invent stock levels, dates, prices,
  suppliers or compliance results.
- Follow the standard operating procedure below exactly. Where it says MUST, there is no exception.
- ERP changes happen only through submit_action, which is checked by a policy engine you cannot
  override. A DENY or ESCALATE is a correct outcome, not a failure to work around.
- All amounts are in the currency the tools report (USD); write them with "$" or "USD", never another currency.
- Be brief. The planner reads your summary in SAP Joule or the SynapseSupply console: write plain
  sentences (bold is fine) — no headings, horizontal rules or tables.
"""


def load_sop(process_type: ProcessType, override_dir: str | Path | None = None) -> str:
    name = SOP_FILES.get(process_type)
    if name is None:
        raise KeyError(f"No SOP for process type {process_type.value}")
    if override_dir and (Path(override_dir) / name).exists():
        return (Path(override_dir) / name).read_text()
    return files("synapse.agent.sops").joinpath(name).read_text()


def system_prompt(process_type: ProcessType, override_dir: str | Path | None = None) -> str:
    return f"{BASE_PROMPT}\n{load_sop(process_type, override_dir)}"
