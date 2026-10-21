"""OData v2 client for S/4HANA — a real system or the mock — used by the agent's tools.

* Rows come back as Python values (date, Decimal, bool) decoded with the shared entity schema.
* Writes fetch and replay the CSRF token like any S/4 client must.
* Failover: if the primary endpoint is unreachable or returns 5xx on a read, the client switches
  to the fallback endpoint (the local mock) for the rest of its life and reports it through
  `on_failover`, so the trace shows the run as degraded. Writes are never replayed on the fallback
  after a server error — the primary may have committed them; only a connection that never reached
  the server fails over.
"""
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from synapse.sap.odata import format_key, from_wire, to_wire
from synapse.sap.schema import ENTITY_SETS, EntitySet

ODATA_ROOT = "/sap/opu/odata/sap"


class ErpError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


def decode(es: EntitySet, row: dict) -> dict:
    out = {f: from_wire(row[f], t) for f, t in es.types.items() if f in row}
    for nav_name, nav in es.navs.items():
        value = row.get(nav_name)
        if isinstance(value, dict) and "__deferred" not in value:
            target = ENTITY_SETS[nav.target]
            out[nav_name] = ([decode(target, r) for r in value.get("results", [])] if nav.many
                             else decode(target, value))
    return out


def encode(es: EntitySet, values: dict) -> dict:
    """Python values -> wire format, including deep-insert navigation properties."""
    out: dict[str, Any] = {}
    for k, v in values.items():
        if k in es.navs:
            target = ENTITY_SETS[es.navs[k].target]
            out[k] = {"results": [encode(target, r) for r in v]}
        elif k in es.types:
            out[k] = to_wire(_coerce(v, es.types[k]), es.types[k])
        else:
            raise ValueError(f"{es.name} has no property {k}")
    return out


def _coerce(v: Any, typ: str) -> Any:
    if v is None:
        return None
    if typ == "decimal" and not isinstance(v, Decimal):
        return Decimal(str(v))
    if typ == "date" and isinstance(v, str):
        return date.fromisoformat(v)
    return v


class ErpClient:
    def __init__(self, primary: httpx.Client, fallback: httpx.Client | None = None,
                 on_failover: Callable[[str], None] | None = None):
        self._primary, self._fallback, self._on_failover = primary, fallback, on_failover
        self._active = primary
        self._csrf: dict[tuple[int, str], str] = {}

    @property
    def degraded(self) -> bool:
        return self._active is not self._primary

    # --- reads ----------------------------------------------------------------------------------

    def read(self, entity_set: str, *, filter: str | None = None, select: list[str] | None = None,
             orderby: str | None = None, top: int | None = None, expand: str | None = None) -> list[dict]:
        es = ENTITY_SETS[entity_set]
        params = {k: v for k, v in {
            "$filter": filter, "$select": ",".join(select) if select else None, "$orderby": orderby,
            "$top": str(top) if top is not None else None, "$expand": expand, "$format": "json"}.items()
            if v is not None}
        data = self._send("GET", f"{ODATA_ROOT}/{es.service}/{es.name}", params=params)
        return [decode(es, r) for r in data["d"]["results"]]

    def get(self, entity_set: str, key: dict[str, str], expand: str | None = None) -> dict | None:
        es = ENTITY_SETS[entity_set]
        try:
            data = self._send("GET", f"{ODATA_ROOT}/{es.service}/{es.name}({format_key(key, es.keys)})",
                              params={"$expand": expand} if expand else None)
        except ErpError as e:
            if e.status == 404:
                return None
            raise
        return decode(es, data["d"])

    # --- writes ---------------------------------------------------------------------------------

    def create(self, entity_set: str, values: dict) -> dict:
        es = ENTITY_SETS[entity_set]
        data = self._write("POST", es, f"{ODATA_ROOT}/{es.service}/{es.name}", encode(es, values))
        return decode(es, data["d"])

    def update(self, entity_set: str, key: dict[str, str], changes: dict) -> None:
        es = ENTITY_SETS[entity_set]
        self._write("PATCH", es, f"{ODATA_ROOT}/{es.service}/{es.name}({format_key(key, es.keys)})",
                    encode(es, changes))

    # --- transport ------------------------------------------------------------------------------

    def _write(self, method: str, es: EntitySet, path: str, body: dict) -> dict:
        for attempt in (1, 2):
            headers = {"x-csrf-token": self._token(es.service), "content-type": "application/json"}
            try:
                return self._send(method, path, json=body, headers=headers, failover=False)
            except ErpError as e:
                if e.status == 403 and "CSRF" in e.message and attempt == 1:
                    self._csrf.pop((id(self._active), es.service), None)
                    continue
                raise
        raise AssertionError("unreachable")

    def _token(self, service: str) -> str:
        key = (id(self._active), service)
        if key not in self._csrf:
            r = self._request(self._active, "GET", f"{ODATA_ROOT}/{service}/", headers={"x-csrf-token": "Fetch"})
            self._raise_for(r)
            self._csrf[key] = r.headers.get("x-csrf-token", "")
        return self._csrf[key]

    def _send(self, method: str, path: str, *, failover: bool = True, **kw) -> dict:
        try:
            r = self._request(self._active, method, path, **kw)
        except httpx.TransportError as e:
            # The request never reached the server: safe to fail over, even for writes.
            return self._fail_over(f"{type(e).__name__}: {e}", method, path, **kw)
        if r.status_code >= 500 and failover and self._fallback is not None and not self.degraded:
            return self._fail_over(f"HTTP {r.status_code}", method, path, **kw)
        self._raise_for(r)
        return r.json() if r.content else {}

    def _fail_over(self, reason: str, method: str, path: str, **kw) -> dict:
        if self._fallback is None or self.degraded:
            raise ErpError(503, "SYNAPSE/UNREACHABLE", reason)
        self._active = self._fallback
        if self._on_failover:
            self._on_failover(reason)
        if "headers" in kw and "x-csrf-token" in kw["headers"]:  # token belonged to the primary
            service = path.removeprefix(ODATA_ROOT + "/").split("/")[0]
            kw["headers"] = kw["headers"] | {"x-csrf-token": self._token(service)}
        r = self._request(self._active, method, path, **kw)
        self._raise_for(r)
        return r.json() if r.content else {}

    @staticmethod
    def _request(client: httpx.Client, method: str, path: str, **kw) -> httpx.Response:
        return client.request(method, path, **kw)

    @staticmethod
    def _raise_for(r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        try:
            err = r.json()["error"]
            raise ErpError(r.status_code, err.get("code", ""), err["message"]["value"])
        except (ValueError, KeyError, TypeError):
            raise ErpError(r.status_code, "HTTP", r.text[:200]) from None


def http_client(base_url: str, *, user: str | None = None, password: str | None = None,
                timeout: float = 10.0) -> httpx.Client:
    auth = (user, password) if user else None
    return httpx.Client(base_url=base_url, auth=auth, timeout=timeout, headers={"accept": "application/json"})
