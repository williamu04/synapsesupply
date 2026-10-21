"""Mock S/4HANA OData v2 server — the demo's system of record and the fail-safe on stage.

Run:  uv run uvicorn synapse.mock_s4.app:app --port 8000

OData:  /sap/opu/odata/sap/<SERVICE>/<EntitySet>[(key)][/<nav>|/$count]
        query options: $filter $orderby $top $skip $select $expand $inlinecount=allpages
        writes: POST A_PurchaseOrder (deep insert), PATCH A_PurchaseOrderScheduleLine(...)
        writes need the CSRF token from a GET with header `x-csrf-token: Fetch`, as on S/4.
Admin:  /admin/reset, /admin/audit, /admin/faults, /admin/scenarios[/{id}/apply]
"""
import asyncio
import random
import re
import secrets

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from synapse.sap.odata import (
    ODataError,
    apply_orderby,
    bad_request,
    format_key,
    parse_expand,
    parse_filter,
    parse_key,
    parse_orderby,
    to_wire,
)
from synapse.sap.schema import ENTITY_SETS, SERVICES, EntitySet

from .store import Store, load_seed

ODATA_ROOT = "/sap/opu/odata/sap"
_RESOURCE = re.compile(r"^(?P<set>\w+)(?:\((?P<key>[^)]*)\))?(?:/(?P<nav>\$count|\w+))?/?$")


class Faults(BaseModel):
    error_rate: float = Field(0.0, ge=0, le=1)
    latency_ms: int = Field(0, ge=0, le=30_000)


def _entity_set(service: str, name: str) -> EntitySet:
    if service not in SERVICES:
        raise ODataError(404, "/IWFND/MED/170", f"No service found for namespace '', name '{service}'")
    if name not in SERVICES[service]:
        raise ODataError(404, "/IWBEP/CM_MGW_RT/021", f"Resource not found for segment '{name}'")
    return ENTITY_SETS[name]


def _int_option(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    if not raw.isdigit():
        raise bad_request(f"Invalid {name}: {raw!r}")
    return int(raw)


def create_app(seed: dict | None = None, rng_seed: int | None = None) -> FastAPI:
    app = FastAPI(title="SynapseSupply mock S/4HANA", version="0.1.0")
    store = Store(seed or load_seed())
    csrf_token = secrets.token_urlsafe(16)
    faults = Faults()
    rng = random.Random(rng_seed)
    app.state.store = store

    @app.exception_handler(ODataError)
    async def _odata_error(_: Request, exc: ODataError):
        return JSONResponse(exc.body(), status_code=exc.status)

    async def _inject_faults() -> None:
        if faults.latency_ms:
            await asyncio.sleep(faults.latency_ms / 1000)
        if faults.error_rate and rng.random() < faults.error_rate:
            raise ODataError(503, "SYNAPSE/INJECTED", "Injected fault: service temporarily unavailable")

    def _require_csrf(request: Request) -> None:
        if request.headers.get("x-csrf-token") != csrf_token:
            raise ODataError(403, "/IWFND/CM_BEC/026", "CSRF token validation failed")

    def _serialize(es: EntitySet, row: dict, base: str, expand: dict, select: set[str] | None) -> dict:
        uri = f"{base}/{es.name}({format_key(row, es.keys)})"
        out: dict = {"__metadata": {"id": uri, "uri": uri, "type": f"{es.namespace}.{es.name}Type"}}
        for f, t in es.types.items():
            if select is None or f in select:
                out[f] = to_wire(row[f], t)
        for nav_name, nav in es.navs.items():
            if nav_name in expand:
                target = ENTITY_SETS[nav.target]
                related = [_serialize(target, r, base, expand[nav_name], None)
                           for r in store.navigate(es, row, nav_name)]
                out[nav_name] = {"results": related} if nav.many else (related[0] if related else None)
            elif select is None:
                out[nav_name] = {"__deferred": {"uri": f"{uri}/{nav_name}"}}
        return out

    def _expand_tree(es: EntitySet, text: str | None) -> dict:
        tree = parse_expand(text or "")

        def check(es: EntitySet, node: dict) -> None:
            for nav_name, sub in node.items():
                if nav_name not in es.navs:
                    raise bad_request(f"Property '{nav_name}' is not a navigation property of {es.name}")
                check(ENTITY_SETS[es.navs[nav_name].target], sub)
        check(es, tree)
        return tree

    def _collection(request: Request, es: EntitySet, rows: list[dict], base: str, count_only: bool):
        q = request.query_params
        if f := q.get("$filter"):
            pred = parse_filter(f, es.types)
            rows = [r for r in rows if pred(r)]
        if count_only:
            return PlainTextResponse(str(len(rows)))
        if ob := q.get("$orderby"):
            rows = apply_orderby(rows, parse_orderby(ob, es.types))
        total = len(rows)
        skip, top = _int_option(request, "$skip") or 0, _int_option(request, "$top")
        rows = rows[skip:] if top is None else rows[skip:skip + top]
        select = None
        if s := q.get("$select"):
            select = {p.strip() for p in s.split(",") if p.strip()}
            if unknown := select - set(es.types) - set(es.navs):
                raise bad_request(f"Property '{min(unknown)}' not found")
        expand = _expand_tree(es, q.get("$expand"))
        d: dict = {"results": [_serialize(es, r, base, expand, select) for r in rows]}
        if q.get("$inlinecount") == "allpages":
            d["__count"] = str(total)
        return {"d": d}

    # --- OData ----------------------------------------------------------------------------------

    @app.get(ODATA_ROOT + "/{service}/")
    @app.get(ODATA_ROOT + "/{service}")
    async def service_document(service: str, request: Request, response: Response):
        if service not in SERVICES:
            raise ODataError(404, "/IWFND/MED/170", f"No service found for name '{service}'")
        if request.headers.get("x-csrf-token", "").lower() == "fetch":
            response.headers["x-csrf-token"] = csrf_token
        return {"d": {"EntitySets": SERVICES[service]}}

    @app.get(ODATA_ROOT + "/{service}/{resource:path}")
    async def read(service: str, resource: str, request: Request, response: Response):
        await _inject_faults()
        if request.headers.get("x-csrf-token", "").lower() == "fetch":
            response.headers["x-csrf-token"] = csrf_token
        m = _RESOURCE.match(resource)
        if not m:
            raise bad_request(f"Unsupported resource path: {resource}")
        es = _entity_set(service, m["set"])
        base = f"{str(request.base_url).rstrip('/')}{ODATA_ROOT}/{service}"
        nav = m["nav"]

        if m["key"] is None:
            if nav not in (None, "$count"):
                raise bad_request("Navigation requires a key")
            return _collection(request, es, store.rows[es.name], base, nav == "$count")

        row = store.get(es.name, parse_key(m["key"], es.keys))
        if nav is None:
            return {"d": _serialize(es, row, base, _expand_tree(es, request.query_params.get("$expand")), None)}
        if nav == "$count" or nav not in es.navs:
            raise bad_request(f"Property '{nav}' is not a navigation property of {es.name}")
        target = ENTITY_SETS[es.navs[nav].target]
        related = store.navigate(es, row, nav)
        if not es.navs[nav].many:
            return {"d": _serialize(target, related[0], base, {}, None) if related else None}
        return _collection(request, target, related, base, False)

    @app.post(ODATA_ROOT + "/{service}/{entity_set}")
    async def create(service: str, entity_set: str, request: Request):
        await _inject_faults()
        _require_csrf(request)
        es = _entity_set(service, entity_set)
        if es.name != "A_PurchaseOrder":
            raise ODataError(405, "SY/METHOD", f"Create is not supported for {es.name}")
        body = await _json_body(request)
        header = store.create_purchase_order(body)
        base = f"{str(request.base_url).rstrip('/')}{ODATA_ROOT}/{service}"
        entity = _serialize(es, header, base, {"to_PurchaseOrderItem": {"to_ScheduleLine": {}}}, None)
        return JSONResponse({"d": entity}, status_code=201, headers={"location": entity["__metadata"]["uri"]})

    @app.patch(ODATA_ROOT + "/{service}/{resource:path}")
    async def update(service: str, resource: str, request: Request):
        await _inject_faults()
        _require_csrf(request)
        m = _RESOURCE.match(resource)
        if not m or m["key"] is None or m["nav"]:
            raise bad_request("PATCH needs an entity key and no navigation")
        es = _entity_set(service, m["set"])
        if es.name != "A_PurchaseOrderScheduleLine":
            raise ODataError(405, "SY/METHOD", f"Update is not supported for {es.name}")
        store.patch_schedule_line(parse_key(m["key"], es.keys), await _json_body(request))
        return Response(status_code=204)

    @app.delete(ODATA_ROOT + "/{service}/{resource:path}")
    async def delete(service: str, resource: str):
        # Defence in depth: Cedar Policy-ForbidDelete stops this first; the ERP refuses too.
        raise ODataError(403, "SYNAPSE/DELETE_FORBIDDEN", "Deleting ERP records is not permitted")

    async def _json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            raise bad_request("Request body is not valid JSON") from None
        if not isinstance(body, dict):
            raise bad_request("Request body must be a JSON object")
        return body

    # --- admin (demo control; not part of the S/4 surface) --------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok", "as_of": store.meta["as_of"], "applied_scenarios": store.applied_scenarios}

    @app.post("/admin/reset")
    async def reset():
        store.reset()
        faults.error_rate, faults.latency_ms = 0.0, 0
        return {"status": "reset", "as_of": store.meta["as_of"]}

    @app.get("/admin/audit")
    async def audit():
        return {"writes": store.audit}

    @app.get("/admin/faults")
    async def get_faults():
        return faults

    @app.post("/admin/faults")
    async def set_faults(new: Faults):
        faults.error_rate, faults.latency_ms = new.error_rate, new.latency_ms
        return faults

    @app.get("/admin/scenarios")
    async def scenarios():
        return {"scenarios": store.scenarios, "applied": store.applied_scenarios}

    @app.post("/admin/scenarios/{scenario_id}/apply")
    async def apply_scenario(scenario_id: str):
        return {"applied": store.apply_scenario(scenario_id)}

    return app


app = create_app()
