"""HTTP API (typed, documented at /docs)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import orchestrator
from ..agents.alert import AlertBus
from ..config import get_settings
from ..connectors.gibs import LAYERS as GIBS_LAYERS
from ..connectors.health import HEALTH
from ..core.clock import IST, utcnow
from ..core.schemas.blackboard import Blackboard, QueryRequest
from ..core.schemas.common import BBox, DataMode, GeoPoint, SourceStatus, UserRole, VesselClass
from ..geo.reference import ReferenceStore
from ..monitor import MONITOR
from ..runtime import Runtime
from ..services import fields as field_svc
from ..store.db import Store
from .security import Principal, principal, rate_limited, require_admin

router = APIRouter(prefix="/api")
STARTED = utcnow()
SOURCE_PROBES: dict[str, dict] = {}


def _mode(mode: Optional[str]) -> DataMode:
    m = (mode or get_settings().default_mode or "LIVE").upper()
    try:
        return DataMode(m)
    except ValueError:
        raise HTTPException(400, f"unknown mode {mode!r}; use LIVE, REPLAY or DEMO")


def _sse(obj: Any) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


# ============================================================================ query
class QueryAccepted(BaseModel):
    query_id: str
    trace_id: str
    conversation_id: str
    mode: DataMode
    scenario: Optional[str] = None
    events_url: str
    result_url: str


@router.post("/query", response_model=None, summary="Ask ORCA (starts the multi-agent pipeline)")
async def post_query(req: QueryRequest, mode: Optional[str] = None, scenario: Optional[str] = None,
                     snapshot: Optional[str] = None, wait: bool = False, p: Principal = Depends(rate_limited)):
    m = _mode(req.mode.value if req.mode else mode)
    try:
        st = orchestrator.create_run(req, m, scenario_id=scenario, snapshot=snapshot)
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))
    except KeyError as e:
        raise HTTPException(404, f"unknown scenario {e}")
    task = asyncio.create_task(orchestrator.run(st))
    if wait:
        bb = await task
        return json.loads(bb.model_dump_json())
    return QueryAccepted(query_id=st.bb.query_id, trace_id=st.bb.trace_id, conversation_id=st.bb.conversation_id,
                         mode=m, scenario=st.ctx.scenario_id, events_url=f"/api/query/{st.bb.query_id}/events",
                         result_url=f"/api/query/{st.bb.query_id}")


def _load(qid: str) -> Blackboard:
    st = orchestrator.ACTIVE.get(qid)
    if st:
        return st.bb
    blob = Store.get().load_blackboard(qid)
    if not blob:
        raise HTTPException(404, "unknown query id / trace id")
    return Blackboard.model_validate_json(blob)


@router.get("/query/{qid}", summary="Full blackboard / result for a query (by query id or trace id)")
async def get_query(qid: str, p: Principal = Depends(principal)):
    return json.loads(_load(qid).model_dump_json())


@router.get("/query/{qid}/agents")
async def get_query_agents(qid: str, p: Principal = Depends(principal)):
    bb = _load(qid)
    return {"plan": bb.plan.model_dump(mode="json"), "agents": [r.model_dump(mode="json") for r in bb.agents.values()]}


@router.get("/query/{qid}/evidence")
async def get_query_evidence(qid: str, p: Principal = Depends(principal)):
    bb = _load(qid)
    return {"claims": [c.model_dump(mode="json") for c in bb.claims],
            "evidence": [e.model_dump(mode="json") for e in bb.evidence],
            "conflicts": [c.model_dump(mode="json") for c in bb.conflicts],
            "failures": [f.model_dump(mode="json") for f in bb.failures],
            "final_assessment": bb.final_assessment.model_dump(mode="json") if bb.final_assessment else None}


@router.get("/query/{qid}/events", summary="Server-sent events: live agent / reasoning trace")
async def query_events(qid: str, request: Request):
    st = orchestrator.ACTIVE.get(qid)

    async def gen():
        if st is None:
            bb = _load(qid)
            for e in bb.events:
                yield _sse(e.model_dump(mode="json"))
            return
        q = st.subscribe()
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(ev.model_dump(mode="json"))
                if ev.type == "done" or await request.is_disconnected():
                    break
        finally:
            st.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/traces", summary="Recent query traces")
async def traces(limit: int = Query(50, le=200), p: Principal = Depends(principal)):
    return Store.get().recent_queries(limit)


# ============================================================================ agents / sources / health
@router.get("/agents", summary="Agent catalogue with tools and typed output schemas")
async def agents():
    return orchestrator.agent_catalog()


@router.get("/agents/graph", summary="Compiled LangGraph topology (nodes, edges, Mermaid)")
async def agent_graph():
    return orchestrator.graph_description()


def _source_rows(ctx) -> list[dict]:
    rows = []
    health = HEALTH.all("LIVE")
    for c in ctx.registry.all():
        d = c.descriptor
        st = c.static_status()
        h = health.get(d.id)
        pr = SOURCE_PROBES.get(d.id)
        status = st.value
        if st in (SourceStatus.UNKNOWN,):
            status = "UNKNOWN"
            if pr:
                status = pr.get("status", "UNKNOWN")
            if h:
                if h["circuit"] == "OPEN":
                    status = "DOWN"
                elif h["consecutive_failures"] > 0:
                    status = "DEGRADED"
                elif h["last_success"] and (utcnow() - h["last_success"]).total_seconds() < 3600:
                    status = "OPERATIONAL"
        rows.append({
            "id": d.id, "name": d.name, "organization": d.organization, "distributor": d.distributor,
            "authority_tier": d.authority_tier.value, "authority_weight": c.authority, "integration": d.integration,
            "access": d.access, "auth_env": d.auth_env, "configured": c.configured(), "status": status,
            "homepage": d.homepage, "docs_url": d.docs_url, "license": d.license, "rate_limit": d.rate_limit,
            "datasets": [ds.model_dump(mode="json") for ds in d.datasets], "notes": d.notes,
            "health": h, "probe": pr,
            "role": getattr(getattr(c, "spec", None), "role", None),
        })
    return rows


async def probe_all() -> None:
    ctx = Runtime.get().context(DataMode.LIVE)

    async def one(c):
        t0 = time.perf_counter()
        try:
            r = await asyncio.wait_for(c.probe(), timeout=60)
        except Exception as e:
            r = {"status": "DEGRADED", "detail": f"probe error: {type(e).__name__}"}
        r["at"] = utcnow().isoformat()
        r["probe_ms"] = round((time.perf_counter() - t0) * 1000)
        SOURCE_PROBES[c.descriptor.id] = json.loads(json.dumps(r, default=str))

    await asyncio.gather(*(one(c) for c in ctx.registry.all()))


@router.get("/sources", summary="Every integrated source with access status, health, freshness and coverage")
async def sources(probe: bool = False, p: Principal = Depends(principal)):
    if probe:
        await probe_all()
    ctx = Runtime.get().context(DataMode.LIVE)
    rows = _source_rows(ctx)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"generated_at": utcnow(), "counts": counts, "total": len(rows), "sources": rows,
            "last_probe": max((v.get("at") for v in SOURCE_PROBES.values()), default=None)}


@router.post("/sources/probe", summary="Probe all sources now")
async def sources_probe(p: Principal = Depends(require_admin)):
    await probe_all()
    return {"probed": len(SOURCE_PROBES), "at": utcnow()}


@router.get("/system/health", summary="Observability: sources, agents, queries, cache, monitor, LLM usage")
async def system_health():
    s = get_settings()
    store = Store.get()
    ctx = Runtime.get().context(DataMode.LIVE)
    rows = _source_rows(ctx)
    live_ok = [r for r in rows if r["status"] == "OPERATIONAL"]
    health = HEALTH.all("LIVE")
    calls = sum(h["calls"] for h in health.values())
    hits = sum(h["cache_hits"] for h in health.values())
    q = store.query_stats()
    return {
        "status": "ok", "time_utc": utcnow(), "uptime_s": round((utcnow() - STARTED).total_seconds()),
        "default_mode": s.default_mode, "auth_required": s.auth_required,
        "llm": {"available": s.llm_available, "model": s.llm_model if s.llm_available else None,
                "tokens_in": q.get("tin") or 0, "tokens_out": q.get("tout") or 0},
        "sources": {"total": len(rows), "operational": len(live_ok),
                    "by_status": {k: sum(1 for r in rows if r["status"] == k) for k in {r["status"] for r in rows}}},
        "agents": {"count": len(orchestrator.agent_catalog()), "stats": store.agent_stats()},
        "queries": {"total": q.get("n") or 0, "avg_ms": q.get("avg_ms"), "active": len(orchestrator.ACTIVE)},
        "http": {"calls": calls, "cache_hits": hits, "cache_hit_rate": (hits / (calls + hits)) if (calls + hits) else None,
                 "per_source": health},
        "monitor": MONITOR.status,
        "snapshots": Runtime.get().list_snapshots(),
    }


@router.get("/system/mode")
async def system_mode():
    from ..demo.scenarios import list_scenarios
    return {"default_mode": get_settings().default_mode, "modes": ["LIVE", "REPLAY", "DEMO"],
            "snapshots": Runtime.get().list_snapshots(), "scenarios": list_scenarios()}


# ============================================================================ demo
@router.get("/demo/scenarios")
async def demo_scenarios():
    from ..demo.scenarios import list_scenarios
    return list_scenarios()


@router.post("/demo/scenarios/{sid}/activate", summary="Run one monitor cycle inside a demo scenario (demo alerts)")
async def demo_activate(sid: str):
    res = await MONITOR.cycle(DataMode.DEMO, scenario_id=sid)
    return res


# ============================================================================ map
@router.get("/map/layers", summary="Map layer catalogue (NASA GIBS imagery with real dates + ORCA forecast fields)")
async def map_layers():
    ctx = Runtime.get().context(DataMode.LIVE)
    gibs = await ctx.registry.gibs.layer_catalog()
    orca = [{"id": k, "title": v["label"], "source": v["model"], "units": v["units"], "kind": "field",
             "endpoint": f"/api/map/field?layer={k}"} for k, v in field_svc.LAYERS.items()]
    vector = [{"id": "eez", "title": "Exclusive Economic Zones", "source": "Marine Regions", "kind": "vector"},
              {"id": "boundaries", "title": "International maritime boundaries", "source": "Marine Regions", "kind": "vector"},
              {"id": "zones", "title": "Protected / restricted / seasonal zones (approx.)", "source": "ORCA curated", "kind": "vector"},
              {"id": "ports", "title": "Ports & fishing harbours", "source": "ORCA gazetteer", "kind": "vector"},
              {"id": "cyclones", "title": "Tropical cyclones (GDACS)", "source": "GDACS", "kind": "vector",
               "endpoint": "/api/map/cyclones"}]
    return {"gibs": gibs, "fields": orca, "vector": vector,
            "basemaps": [{"id": "dark", "title": "Dark (CARTO)", "attribution": "© OpenStreetMap contributors © CARTO"},
                         {"id": "satellite", "title": "VIIRS true colour (NASA GIBS)", "attribution": "NASA EOSDIS GIBS"},
                         {"id": "relief", "title": "Blue Marble relief & bathymetry (NASA)", "attribution": "NASA"}]}


@router.get("/map/field", summary="Gridded forecast field (sea points only) for waves / wind / currents")
async def map_field(layer: str = Query(..., pattern="^(waves|wind|currents)$"), mode: Optional[str] = None,
                    scenario: Optional[str] = None, res: float = Query(1.5, ge=0.5, le=3.0)):
    m = _mode(mode)
    ctx = Runtime.get().context(m, scenario_id=scenario)
    return await field_svc.field(ctx, layer, res)


@router.get("/map/cyclones")
async def map_cyclones(mode: Optional[str] = None, scenario: Optional[str] = None):
    ctx = Runtime.get().context(_mode(mode), scenario_id=scenario)
    events, prov, fails = await ctx.registry.gdacs.cyclones()
    feats = []
    for ev in events:
        feats.append({"type": "Feature", "properties": {"kind": "centroid", "name": ev["name"], "active": ev["active"],
                                                         "alert": ev["alert_level"], "severity": ev["severity_text"]},
                      "geometry": {"type": "Point", "coordinates": [ev["centroid"].lon, ev["centroid"].lat]}})
        if ev["track"]:
            feats.append({"type": "Feature", "properties": {"kind": "track", "name": ev["name"], "active": ev["active"]},
                          "geometry": {"type": "LineString", "coordinates": [[t["point"].lon, t["point"].lat] for t in ev["track"]]}})
        for w in ev["wind_radii"]:
            feats.append({"type": "Feature", "properties": {"kind": "wind_radius", "threshold_kmh": w["threshold_kmh"],
                                                             "name": ev["name"], "active": ev["active"]}, "geometry": w["geometry"]})
        if ev.get("cone"):
            feats.append({"type": "Feature", "properties": {"kind": "cone", "name": ev["name"], "active": ev["active"]},
                          "geometry": ev["cone"]})
    return {"type": "FeatureCollection", "features": feats,
            "provenance": prov.model_dump(mode="json") if prov else None,
            "failures": [f.model_dump(mode="json") for f in fails]}


@router.get("/boundaries", summary="Reference geodata: EEZ, maritime boundaries, zones, ports, geofences")
async def boundaries():
    ref = ReferenceStore.get()
    return {"layers": ref.geojson_layers(), "provenance": ref.provenance()}


# ============================================================================ direct data endpoints
async def _point_series(models, lat: float, lon: float, hours: int, variables: list[str]) -> dict:
    now = utcnow()
    out: dict[str, Any] = {"lat": lat, "lon": lon, "models": {}}
    res = await asyncio.gather(*(m.point(GeoPoint(lat=lat, lon=lon), past_days=1, forecast_days=3, variables=variables)
                                 for m in models))
    for m, (series, fails) in zip(models, res):
        out["models"][m.descriptor.id] = {
            "source": m.spec.name, "failures": [f.model_dump(mode="json") for f in fails],
            "series": {v: {"units": ts.units, "times": [t.isoformat() for t in ts.times
                                                         if now - timedelta(hours=6) <= t <= now + timedelta(hours=hours)],
                           "values": [x for t, x in zip(ts.times, ts.values) if now - timedelta(hours=6) <= t <= now + timedelta(hours=hours)],
                           "provenance": ts.provenance.model_dump(mode="json")} for v, ts in series.items()}}
    return out


@router.get("/ocean", summary="Multi-model ocean point forecast (waves, swell, currents, model SST)")
async def ocean(lat: float = Query(..., ge=-40, le=40), lon: float = Query(..., ge=30, le=120), hours: int = Query(48, le=72),
                mode: Optional[str] = None, scenario: Optional[str] = None):
    ctx = Runtime.get().context(_mode(mode), scenario_id=scenario)
    return await _point_series(ctx.registry.wave_models() + ctx.registry.current_models(), lat, lon, hours,
                               ["wave_height", "wave_direction", "wave_period", "swell_height", "current_speed", "sst_model"])


@router.get("/waves", summary="Multi-model significant wave height at a point")
async def waves(lat: float = Query(..., ge=-40, le=40), lon: float = Query(..., ge=30, le=120), hours: int = Query(48, le=72),
                mode: Optional[str] = None, scenario: Optional[str] = None):
    ctx = Runtime.get().context(_mode(mode), scenario_id=scenario)
    return await _point_series(ctx.registry.wave_models(), lat, lon, hours, ["wave_height", "wave_direction", "wave_period"])


@router.get("/weather", summary="Multi-model marine weather at a point")
async def weather(lat: float = Query(..., ge=-40, le=40), lon: float = Query(..., ge=30, le=120), hours: int = Query(48, le=72),
                  mode: Optional[str] = None, scenario: Optional[str] = None):
    ctx = Runtime.get().context(_mode(mode), scenario_id=scenario)
    return await _point_series(ctx.registry.weather_models(), lat, lon, hours,
                               ["wind_speed", "wind_direction", "wind_gusts", "precipitation", "cape", "visibility", "pressure"])


@router.get("/satellite", summary="Satellite SST / SST anomaly / chlorophyll at a point")
async def satellite(lat: float = Query(..., ge=-40, le=40), lon: float = Query(..., ge=30, le=120),
                    mode: Optional[str] = None, scenario: Optional[str] = None):
    ctx = Runtime.get().context(_mode(mode), scenario_id=scenario)
    out = {}
    res = await asyncio.gather(*(ctx.registry.erddap.point(k, GeoPoint(lat=lat, lon=lon), 0.15)
                                 for k in ("sst", "sst_anomaly", "chlorophyll")))
    for k, (pv, fails) in zip(("sst", "sst_anomaly", "chlorophyll"), res):
        out[k] = {"value": pv.model_dump(mode="json") if pv else None, "failures": [f.model_dump(mode="json") for f in fails]}
    return out


@router.get("/fisheries", summary="Candidate productive zones near a location (runs the agent pipeline)")
async def fisheries(lat: float = Query(..., ge=-40, le=40), lon: float = Query(..., ge=30, le=120),
                    mode: Optional[str] = None, scenario: Optional[str] = None, p: Principal = Depends(rate_limited)):
    req = QueryRequest(text=f"Show potential fishing zones near {lat:.3f}, {lon:.3f}", location=GeoPoint(lat=lat, lon=lon))
    bb = await orchestrator.run_query(req, _mode(mode), scenario_id=scenario)
    return {"trace_id": bb.trace_id, "query_id": bb.query_id, "fisheries": bb.outputs.get("fisheries"),
            "final_assessment": bb.final_assessment.model_dump(mode="json") if bb.final_assessment else None}


class RouteRequest(BaseModel):
    origin: str | GeoPoint = Field(description="gazetteer id / name or {lat, lon}")
    destination: str | GeoPoint
    departure: Optional[datetime] = None
    vessel_class: VesselClass = VesselClass.MECHANIZED
    speed_kn: Optional[float] = Field(default=None, gt=0, le=40)
    mode: Optional[DataMode] = None
    scenario: Optional[str] = None
    conversation_id: Optional[str] = None


@router.post("/route/analyze", summary="Optimise and evaluate a route (time-dependent A* + segment risk)")
async def route_analyze(r: RouteRequest, p: Principal = Depends(rate_limited)):
    def label(x):
        if isinstance(x, GeoPoint):
            return f"{x.lat:.3f},{x.lon:.3f}"
        ref = ReferenceStore.get()
        pl = ref.place_by_id.get(x)
        return pl["name"] if pl else x
    when = ""
    if r.departure:
        when = f" departing {r.departure.astimezone(IST):%d %b %H:%M}"
    req = QueryRequest(text=f"Plan a route from {label(r.origin)} to {label(r.destination)}{when}",
                       vessel_class=r.vessel_class, speed_kn=r.speed_kn, role=UserRole.OPERATOR,
                       conversation_id=r.conversation_id)
    m = _mode(r.mode.value if r.mode else None)
    st = orchestrator.create_run(req, m, scenario_id=r.scenario)
    asyncio.create_task(orchestrator.run(st))
    return QueryAccepted(query_id=st.bb.query_id, trace_id=st.bb.trace_id, conversation_id=st.bb.conversation_id, mode=m,
                         scenario=st.ctx.scenario_id, events_url=f"/api/query/{st.bb.query_id}/events",
                         result_url=f"/api/query/{st.bb.query_id}")


# ============================================================================ geofences
class GeofenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ring: list[list[float]] = Field(min_length=4, max_length=500, description="[[lon, lat], ...] closed ring")
    note: str = ""


@router.get("/geofences")
async def list_geofences():
    return Store.get().geofences()


@router.post("/geofences")
async def create_geofence(g: GeofenceIn, p: Principal = Depends(principal)):
    for lon, lat in g.ring:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise HTTPException(422, "ring coordinates must be [lon, lat] in WGS84")
    if g.ring[0] != g.ring[-1]:
        g.ring.append(g.ring[0])
    gid = "gf_" + uuid.uuid4().hex[:8]
    ReferenceStore.get().add_geofence(gid, g.name, g.ring, {"note": g.note})
    Store.get().save_geofence(gid, g.name, g.ring, {"note": g.note})
    return {"id": gid, "name": g.name}


@router.delete("/geofences/{gid}")
async def delete_geofence(gid: str, p: Principal = Depends(principal)):
    ReferenceStore.get().remove_geofence(gid)
    Store.get().delete_geofence(gid)
    return {"deleted": gid}


# ============================================================================ alerts
@router.get("/alerts", summary="Alert centre")
async def list_alerts(mode: Optional[str] = None, status: Optional[str] = None, limit: int = Query(100, le=500)):
    return Store.get().alerts(mode=mode.upper() if mode else None, status=status, limit=limit)


class WatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(point)$", default="point")
    lat: float = Field(ge=-40, le=40)
    lon: float = Field(ge=30, le=120)
    radius_km: float = Field(default=20, gt=0, le=200)
    vessel_class: VesselClass = VesselClass.SMALL_CRAFT


@router.post("/alerts", summary="Register a monitoring watch (vessel / point); the monitor raises alerts proactively")
async def create_watch(w: WatchIn, p: Principal = Depends(principal)):
    wid = "w_" + uuid.uuid4().hex[:8]
    Store.get().save_watch(wid, w.name, w.kind, w.model_dump(mode="json"))
    return {"id": wid, "name": w.name}


@router.get("/alerts/watches")
async def list_watches():
    return Store.get().watches()


@router.post("/alerts/{aid}/ack")
async def ack_alert(aid: str, p: Principal = Depends(principal)):
    if not Store.get().set_alert_status(aid, "acknowledged"):
        raise HTTPException(404, "unknown alert")
    return {"id": aid, "status": "acknowledged"}


@router.post("/alerts/scan", summary="Run one monitoring cycle now")
async def alerts_scan(mode: Optional[str] = None, scenario: Optional[str] = None, p: Principal = Depends(rate_limited)):
    return await MONITOR.cycle(_mode(mode), scenario_id=scenario)


@router.get("/alerts/stream", summary="Server-sent events: new alerts")
async def alerts_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    AlertBus.subscribers.append(q)

    async def gen():
        try:
            while True:
                try:
                    a = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    if await request.is_disconnected():
                        break
                    continue
                yield _sse(a.model_dump(mode="json"))
        finally:
            AlertBus.subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ============================================================================ evaluation
@router.post("/eval/run", summary="Run the ORCA evaluation suite (deterministic, DEMO mode)")
async def eval_run(limit: int = Query(0, ge=0), p: Principal = Depends(require_admin)):
    from ..evaluation.runner import run_suite
    return await run_suite(limit=limit or None)


@router.get("/eval/latest")
async def eval_latest():
    r = Store.get().latest_eval()
    if not r:
        raise HTTPException(404, "no evaluation run yet")
    return r
