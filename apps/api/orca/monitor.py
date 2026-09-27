"""Proactive monitoring service (alerts do not depend on a user asking).

Every cycle:
  1. SCAN     one wave model (MFWAM) + one NWP model (GFS) at offshore stations of every coastal sector,
              GDACS cyclones, registered vessel/point watches (cheap, rate-limit friendly)
  2. EVENT    threshold crossings (small-craft limits), active cyclones, forecast jumps
              (max Hs next 24 h up > 0.75 m vs previous cycle), watch proximity to zones/boundaries
  3. VERIFY   each candidate event is re-assessed by the full multi-agent pipeline (REGIONAL_RISK /
              SAFETY_CHECK with all models + advisories + evidence agent)
  4. GENERATE alerts from the verified assessment (Alert agent rules)
  5. DELIVER  persist + publish on the SSE alert stream
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

from .agents.alert import AlertBus, _id
from .core import spatial
from .core.clock import utcnow
from .core.risk import THRESHOLDS
from .core.schemas.blackboard import QueryRequest
from .core.schemas.common import DataMode, GeoPoint, RiskLevel, UserRole, VesselClass
from .core.schemas.geo import Alert
from .runtime import Runtime
from .store.db import Store

log = logging.getLogger("orca.monitor")
SECTORS = ["gujarat_coast", "maharashtra_coast", "goa_coast", "karnataka_coast", "kerala_coast", "tamil_nadu_coast",
           "andhra_coast", "odisha_coast", "west_bengal_coast"]


class Monitor:
    def __init__(self) -> None:
        self.status: dict[str, Any] = {"enabled": False, "cycles": 0, "last_run": None, "next_run": None,
                                       "last_events": [], "alerts_generated": 0, "errors": [], "running": False}
        self._prev_max: dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._stations: Optional[list[tuple[str, str, GeoPoint]]] = None

    def start(self, interval_s: int) -> None:
        self.status["enabled"] = True
        self.status["interval_s"] = interval_s
        self._task = asyncio.create_task(self._loop(interval_s))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self, interval_s: int) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await self.cycle(DataMode.LIVE)
            except Exception as e:  # pragma: no cover
                log.exception("monitor cycle failed")
                self.status["errors"] = (self.status["errors"] + [f"{utcnow():%H:%M} {type(e).__name__}: {e}"])[-5:]
            self.status["next_run"] = (utcnow() + timedelta(seconds=interval_s)).isoformat()
            await asyncio.sleep(interval_s)

    def stations(self, ctx) -> list[tuple[str, str, GeoPoint]]:
        if self._stations is None:
            out = []
            ref = ctx.ref
            for rid in SECTORS:
                r = next(x for x in ref.regions if x["id"] == rid)
                for aid in r["anchors"]:
                    try:
                        p, _ = ref.offshore_point(ref.place(aid).point, 25)
                        out.append((rid, aid, p))
                    except ValueError:
                        continue
            self._stations = out
        return self._stations

    async def cycle(self, mode: DataMode, scenario_id: Optional[str] = None) -> dict:
        from .orchestrator import run_query
        self.status["running"] = True
        rt = Runtime.get()
        ctx = rt.context(mode, scenario_id=scenario_id)
        now = ctx.clock.now()
        stations = self.stations(ctx)
        pts = [p for _, _, p in stations]
        th = THRESHOLDS["small_craft"]
        wave_m, wx_m = ctx.registry.models["om_mfwam"], ctx.registry.models["om_gfs"]
        (waves, wf), (winds, xf), (cyc, cprov, cf) = await asyncio.gather(
            wave_m.points(pts, past_days=0, forecast_days=2, variables=["wave_height"]),
            wx_m.points(pts, past_days=0, forecast_days=2, variables=["wind_speed", "wind_gusts"]),
            ctx.registry.gdacs.cyclones())
        horizon = now + timedelta(hours=24)
        events: list[dict] = []
        sector_max: dict[str, dict] = {}
        for (rid, aid, p), wv, wd in zip(stations, waves, winds):
            hs = [v for t, v in (wv.get("wave_height").window(now, horizon) if wv.get("wave_height") else [])]
            ws = [v for t, v in (wd.get("wind_speed").window(now, horizon) if wd.get("wind_speed") else [])]
            m = sector_max.setdefault(rid, {"hs": 0.0, "ws": 0.0, "anchor": aid})
            if hs and max(hs) > m["hs"]:
                m["hs"], m["anchor"] = max(hs), aid
            if ws and max(ws) > m["ws"]:
                m["ws"] = max(ws)
        for rid, m in sector_max.items():
            if m["hs"] >= th["wave_height"].caution or m["ws"] >= th["wind_speed"].caution:
                events.append({"type": "threshold", "region": rid, "hs": round(m["hs"], 2), "ws": round(m["ws"], 1)})
            prev = self._prev_max.get(f"{mode.value}:{rid}")
            if prev is not None and m["hs"] - prev > 0.75:
                events.append({"type": "forecast_jump", "region": rid, "from": round(prev, 2), "to": round(m["hs"], 2)})
            self._prev_max[f"{mode.value}:{rid}"] = m["hs"]
        store = Store.get()
        generated = 0
        for c in cyc:
            if not c["active"]:
                continue
            key = f"{mode.value}:cyclone:{c['event_id']}:{now:%Y%m%d}"
            if store.alert_exists(key, (now - timedelta(hours=12)).isoformat()):
                continue
            a = Alert(id=_id(key), created_at=now, severity="severe" if c.get("alert_level") in ("Red", "Orange") else "warning",
                      category="cyclone", title=f"{c['name']} active — GDACS {c.get('alert_level')}",
                      message=f"{c['name']}: {c.get('severity_text') or ''}. Track source {c.get('track_source')}. "
                              f"Follow IMD (RSMC New Delhi) bulletins.",
                      region="North Indian Ocean", location=c["centroid"], level=RiskLevel.DANGER, verified=True,
                      verification="international advisory (GDACS); national bulletin: IMD", mode=mode.value, dedup_key=key,
                      evidence=[{"source": "GDACS", "report": c.get("report_url")}])
            store.save_alert(a)
            AlertBus.publish(a)
            generated += 1
        # watches: vessel / point positions vs zones & boundaries (pure geometry)
        for w in store.watches():
            spec = w["spec"]
            if w["kind"] != "point":
                continue
            p = GeoPoint(lat=spec["lat"], lon=spec["lon"])
            for z in ctx.ref.zone_hits(p, now, spec.get("vessel_class", "small_craft"), radius_km=spec.get("radius_km", 20)):
                if z.kind in ("mpa", "restricted", "maritime_boundary", "geofence") and (z.inside or z.distance_km <= spec.get("radius_km", 20)):
                    key = f"{mode.value}:watch:{w['id']}:{z.zone_id}:{now:%Y%m%d%H}"
                    if store.alert_exists(key, (now - timedelta(hours=1)).isoformat()):
                        continue
                    a = Alert(id=_id(key), created_at=now, severity="warning", category="geofence",
                              title=f"{w['name']}: {'inside' if z.inside else 'near'} {z.name}",
                              message=(f"{w['name']} is inside {z.name}." if z.inside else
                                       f"{w['name']} is {z.distance_km:.1f} km ({z.distance_nm:.1f} nm) from {z.name}."),
                              region=w["name"], location=p, level=RiskLevel.CAUTION, verified=True,
                              verification="deterministic geometry", mode=mode.value, dedup_key=key)
                    store.save_alert(a)
                    AlertBus.publish(a)
                    generated += 1
        # VERIFY threshold events with the full multi-agent pipeline (one per sector, most severe first)
        verified_runs = []
        for ev in sorted([e for e in events if e["type"] in ("threshold", "forecast_jump")], key=lambda e: -e.get("hs", e.get("to", 0)))[:3]:
            region = next(r for r in ctx.ref.regions if r["id"] == ev["region"])
            req = QueryRequest(text=f"Hazards across the {region['name']} for the next 24 hours", role=UserRole.AUTHORITY,
                               vessel_class=VesselClass.SMALL_CRAFT)
            bb = await run_query(req, mode, scenario_id=scenario_id)
            verified_runs.append({"region": ev["region"], "trace_id": bb.trace_id,
                                  "decision": bb.final_assessment.decision.value if bb.final_assessment else None,
                                  "alerts": len(bb.alerts)})
            generated += sum(1 for a in bb.alerts)
        self.status.update(cycles=self.status["cycles"] + 1, last_run=utcnow().isoformat(), last_events=events,
                           verified_runs=verified_runs, running=False,
                           alerts_generated=self.status["alerts_generated"] + generated,
                           last_failures=[f.reason for f in (wf + xf + cf)][:5], mode=mode.value)
        return {"events": events, "verified": verified_runs, "alerts_generated": generated}


MONITOR = Monitor()
