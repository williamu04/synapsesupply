"""What the Joule agent does with a chat message: route it to the SynapseSupply API, answer in markdown.

  "approve 4500000091-10"                     -> POST /cases/{id}/approve
  "reject 4500000091-10 because line 2 slows" -> POST /cases/{id}/reject
  "what needs my approval?"                   -> cases AWAITING_APPROVAL
  "status of 4500000091-10" / a bare case id  -> that case
  anything else                               -> POST /requests (the agent handles it, SOP-REQ-01)

Kept free of A2A types so it is testable against the API directly.
"""
import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

CASE_ID = r"(?P<id>[A-Za-z0-9]{4,20}-\d{1,6})"
# Commands are matched anywhere in a line (Joule may wrap or prefix the user's words), newest line first.
_APPROVE = re.compile(rf"\bapprove\s+(?:the\s+)?(?:case\s+)?{CASE_ID}\b", re.IGNORECASE)
_REJECT = re.compile(rf"\breject\s+(?:the\s+)?(?:case\s+)?{CASE_ID}\b[\s,:-]*(?:because\s+)?(?P<reason>.*)$",
                     re.IGNORECASE)
_PENDING = re.compile(r"\b(pending|awaiting|waiting|needs? (?:my )?approval|to approve|approvals?)\b", re.IGNORECASE)
_STATUS_WORD = re.compile(r"\b(status|show|open|details?|what happened|progress)\b", re.IGNORECASE)
_CASE_ID_ANYWHERE = re.compile(rf"(?<![\w-]){CASE_ID}(?![\w-])")
_BARE_CASE_ID = re.compile(rf"^\s*(?:case\s+)?{CASE_ID}\s*\??\s*$", re.IGNORECASE)

ICON = {"EXECUTED": "✅", "AWAITING_APPROVAL": "⚑", "BLOCKED": "⛔", "REJECTED": "✖", "FAILED": "❗",
        "NO_ACTION_NEEDED": "✅", "NEW": "…", "ANALYZING": "…"}
LABEL = {"EXECUTED": "Executed", "AWAITING_APPROVAL": "Needs your approval", "BLOCKED": "Blocked by policy",
         "REJECTED": "Rejected", "FAILED": "Failed", "NO_ACTION_NEEDED": "No action needed", "NEW": "Queued",
         "ANALYZING": "Analyzing"}
UNITS = {"TO": "t", "M3": "m³"}


@dataclass(frozen=True)
class Command:
    kind: str  # APPROVE | REJECT | PENDING | STATUS | REQUEST
    case_id: str | None = None
    reason: str | None = None
    text: str = ""


def parse(text: str) -> Command:
    text = text.strip()
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        if m := _REJECT.search(line):
            return Command("REJECT", m["id"].upper(), (m["reason"] or "").strip() or None, text)
        if m := _APPROVE.search(line):
            return Command("APPROVE", m["id"].upper(), text=text)
        if (m := _BARE_CASE_ID.match(line)) or (_STATUS_WORD.search(line) and (m := _CASE_ID_ANYWHERE.search(line))):
            return Command("STATUS", m["id"].upper(), text=text)
    if _PENDING.search(text) and not re.search(r"\b(order|buy|purchase|source)\b", text, re.IGNORECASE):
        return Command("PENDING", text=text)
    return Command("REQUEST", text=text)


def claimed_user(headers: dict[str, str]) -> str | None:
    """The Joule user named in a forwarded bearer token — NOT signature-verified.

    Used only as the approver label. Trust comes from who can see the capability (IAS group
    visibility_condition) and the API key between this bridge and the SynapseSupply API.
    """
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or auth.count(".") < 2:
        return None
    try:
        payload = auth.split()[1].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, IndexError):
        return None
    name = claims.get("user_name") or claims.get("email") or claims.get("sub")
    return str(name)[:60] if name else None


class SynapseApi:
    """Thin client for the SynapseSupply API (docs/api.md)."""

    def __init__(self, client: httpx.Client, console_url: str | None = None):
        self.client, self.console_url = client, (console_url or "").rstrip("/") or None

    def _call(self, method: str, path: str, **kw) -> Any:
        r = self.client.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise BridgeError(r.status_code, str(detail))
        return r.json()

    def request(self, utterance: str, user: str) -> dict:
        return self._call("POST", "/requests", params={"wait": "true"}, json={"utterance": utterance, "user": user},
                          timeout=180)

    def case(self, case_id: str) -> dict:
        return self._call("GET", f"/cases/{case_id}")

    def cases(self) -> list[dict]:
        return self._call("GET", "/cases")

    def approve(self, case_id: str, approver: str) -> dict:
        return self._call("POST", f"/cases/{case_id}/approve", json={"approver": approver})

    def reject(self, case_id: str, approver: str, reason: str) -> dict:
        return self._call("POST", f"/cases/{case_id}/reject", json={"approver": approver, "reason": reason})


class BridgeError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass(frozen=True)
class Reply:
    """Markdown for the chat plus structured fields the Joule function uses for buttons."""
    text: str
    case_id: str | None = None
    status: str | None = None

    @property
    def data(self) -> dict:
        return {"case_id": self.case_id, "status": self.status,
                "awaiting_approval": self.status == "AWAITING_APPROVAL"}


def handle(text: str, user: str | None, api: SynapseApi) -> str:
    """Answer one Joule message. Never raises: errors become a readable reply."""
    return respond(text, user, api).text


def respond(text: str, user: str | None, api: SynapseApi) -> Reply:
    approver = f"joule:{user}" if user else "joule:unknown-user"
    cmd = parse(text)

    def case_reply(case: dict) -> Reply:
        return Reply(render_case(case, api.console_url), case.get("case_id"), case.get("status"))

    try:
        if cmd.kind == "APPROVE":
            return case_reply(api.approve(cmd.case_id, approver))
        if cmd.kind == "REJECT":
            if not cmd.reason:
                return Reply(f"Please give a reason, e.g. **reject {cmd.case_id} because we will slow down line 2**.")
            return case_reply(api.reject(cmd.case_id, approver, cmd.reason))
        if cmd.kind == "STATUS":
            return case_reply(api.case(cmd.case_id))
        if cmd.kind == "PENDING":
            cases = api.cases()
            waiting = [c for c in cases if c.get("status") == "AWAITING_APPROVAL"]
            # Buttons only make sense for a single waiting case; with several, the user types the number.
            only = waiting[0] if len(waiting) == 1 else {}
            return Reply(render_pending(cases, api.console_url), only.get("case_id"), only.get("status"))
        return case_reply(api.request(cmd.text, user or "joule"))
    except BridgeError as e:
        if e.status == 404:
            return Reply(f"I can't find case **{cmd.case_id}**. Ask *what needs my approval?* to see open cases.")
        if e.status == 409:
            return Reply(f"Case **{cmd.case_id}** is not waiting for a decision any more. {e.detail}")
        return Reply(f"❗ SynapseSupply could not process that ({e.status}): {e.detail}")
    except httpx.HTTPError as e:
        return Reply(f"❗ SynapseSupply is not reachable right now ({type(e).__name__}). Please try again shortly.")


def _short(text: str, limit: int = 70) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _qty(value: float, unit: str) -> str:
    return f"{value:,.0f} {UNITS.get(unit, unit)}"


def _action(p: dict) -> str:
    qty = _qty(p["quantity"], p["unit"])
    if p["action_type"] == "CREATE_STOCK_TRANSFER":
        return f"Stock transfer of {qty} from plant {p['supplying_plant']} to plant {p['plant']}"
    if p["action_type"] == "CREATE_PURCHASE_ORDER":
        return f"Purchase order for {qty} of {p['material']} from supplier {p['supplier']} for plant {p['plant']}"
    return f"{p['action_type']} {qty}"


def render_case(c: dict, console_url: str | None = None) -> str:
    status = c.get("status", "NEW")
    lines = [f"**{ICON.get(status, '•')} {LABEL.get(status, status)}** · case {c['case_id']}"]
    if c.get("summary"):
        lines += ["", c["summary"]]
    p, policy = c.get("proposal"), c.get("policy")
    if p:
        executed_or_pending = status in ("EXECUTED", "AWAITING_APPROVAL")
        lines += ["", f"- **{'Action' if executed_or_pending else 'Requested (not executed)'}:** {_action(p)}",
                  f"- **Arrives:** {p['delivery_date']}",
                  f"- **Incremental cost:** ${p['financial_impact_usd']:,.0f} (autonomous limit $5,000)",
                  f"- **Plan confidence:** {p['confidence']:.2f} (autonomous threshold 0.90)",
                  f"- **Supplier compliance:** {p['compliance_outcome'] or 'own-plant transfer'}"]
        if p.get("alternatives"):
            lines.append("- **Other options:** " + "; ".join(
                f"{a['description']} ({_short(a['reason'])})" for a in p["alternatives"][:4]))
    if policy:
        lines.append(f"- **Policy:** {policy['effect']} — " + "; ".join(policy["reasons"]))
    if c.get("sap_document"):
        lines.append(f"- **SAP document:** {c['sap_document']}")
    if c.get("approver"):
        lines.append(f"- **Decided by:** {c['approver']}")
    if status == "AWAITING_APPROVAL":
        lines += ["", f"Reply **approve {c['case_id']}** or **reject {c['case_id']} because …**."]
    if console_url:
        lines += ["", f"[Open in the SynapseSupply console]({console_url}/?case={c['case_id']})"]
    return "\n".join(lines)


def render_pending(cases: list[dict], console_url: str | None = None) -> str:
    waiting = [c for c in cases if c.get("status") == "AWAITING_APPROVAL"]
    if not waiting:
        return "✅ Nothing is waiting for your approval."
    lines = [f"**⚑ {len(waiting)} case{'s' if len(waiting) != 1 else ''} waiting for approval**", ""]
    for c in waiting:
        p = c.get("proposal") or {}
        cost = f" · ${p['financial_impact_usd']:,.0f}" if p else ""
        lines.append(f"- **{c['case_id']}** — {_action(p) if p else c.get('summary', '')}{cost}")
    lines += ["", "Reply **approve** or **reject … because …** with the case number, or ask for its **status**."]
    if console_url:
        lines.append(f"[Open the SynapseSupply console]({console_url}/)")
    return "\n".join(lines)
