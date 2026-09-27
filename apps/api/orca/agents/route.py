"""Agent 8 — Route optimisation agent.

Builds a conservative (worst-of-models) hourly risk cube from the ocean and
weather agents' gridded forecasts, then runs time-dependent A* three times
(shortest α=0, recommended α=3, safest α=8) over a land-masked grid with
zone constraints, smooths each path without increasing risk, and evaluates
every segment at the vessel's ETA. All coordinates come from the search —
none from a language model.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import shapely
from pydantic import BaseModel, Field
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator

from ..core import routing, spatial
from ..core.clock import IST
from ..core.risk import THRESHOLDS, level_for, risk_cube
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, GeoPoint, RiskLevel
from ..core.schemas.geo import RouteOption, RouteResult, RouteSegment, ZoneHit
from ..core.units import km_to_nm
from .base import Agent, AgentOutcome, RunState

DEFAULT_SPEED_KN = {"small_craft": 7.0, "mechanized": 9.0, "large_vessel": 12.0}
ALPHAS = [("shortest", "Shortest", 0.0), ("recommended", "Recommended (balanced)", 3.0), ("safest", "Lowest risk", 8.0)]
VARS = ("wave_height", "wind_speed", "wind_gusts", "current_speed", "precipitation")


class RouteOutput(BaseModel):
    route: Optional[RouteResult] = None
    geojson: Optional[dict] = None
    per_model_samples: dict[str, dict[str, list[dict]]] = Field(default_factory=dict)   # sid -> var -> samples
    risk_field_sources: dict[str, list[str]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def _fill_nan(a: np.ndarray) -> np.ndarray:
    m = np.isnan(a)
    if not m.any():
        return a
    if m.all():
        return np.zeros_like(a)
    idx = ndimage.distance_transform_edt(m, return_distances=False, return_indices=True)
    return a[tuple(idx)]


class RouteAgent(Agent):
    name = "route"
    title = "Route Optimisation Agent"
    responsibility = "Time-dependent A* routing over a risk cost surface with land, zone and boundary constraints"
    tools = ["routing.build_grid", "routing.risk_cube", "routing.astar", "routing.smooth", "spatial.zone_intersections",
             "spatial.boundary_distance"]
    consumes = ["geospatial", "ocean:field", "weather:field"]
    output_model = RouteOutput
    timeout_s = 120.0

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        ref = st.ctx.ref
        u = st.bb.understanding
        geo = st.typed["geospatial"]
        of = st.typed.get("ocean:field")
        wf = st.typed.get("weather:field")
        vessel = u.vessel_class.value
        speed = float(st.bb.request.speed_kn or DEFAULT_SPEED_KN[vessel])
        departure = u.time_window.start
        ep = geo.route_endpoints
        o, d = GeoPoint(**ep["origin"]), GeoPoint(**ep["destination"])
        out = RouteOutput()
        if of is None or not of.by_model:
            return AgentOutcome(status=AgentStatus.FAILED, summary="no ocean forecast field — cannot build risk surface",
                                output=out, failures=[])

        st.stage("ALIGNMENT", "Aligning gridded forecasts to the vessel's space-time path")
        # ------------------------------------------------------------ conservative coarse fields
        lats_c, lons_c, times = of.lats, of.lons, of.times
        combined: dict[str, np.ndarray] = {}
        for var in VARS:
            stacks = []
            for src in (of, wf):
                if src is None:
                    continue
                tindex = {t: k for k, t in enumerate(src.times)}
                for sid, arrs in src.by_model.items():
                    if var in arrs:
                        a = arrs[var]
                        aligned = np.full((len(times), len(lats_c), len(lons_c)), np.nan)
                        for k, t in enumerate(times):
                            if t in tindex:
                                aligned[k] = a[tindex[t]]
                        stacks.append(aligned)
                        out.risk_field_sources.setdefault(var, []).append(src.models[sid].spec.name)
            if stacks:
                import warnings as _w
                with np.errstate(all="ignore"), _w.catch_warnings():
                    _w.simplefilter("ignore", RuntimeWarning)
                    combined[var] = np.nanmax(np.stack(stacks), axis=0)   # conservative: worst of models
        gc_km = spatial.distance_km(o, d)
        max_h = gc_km * 1.8 / (speed * 1.852) + 3
        t_sel = [k for k, t in enumerate(times) if departure - timedelta(hours=1) <= t <= departure + timedelta(hours=max_h + 1)]
        if not t_sel:
            out.notes.append("departure time outside forecast coverage")
            return AgentOutcome(status=AgentStatus.FAILED, summary="departure outside forecast coverage (≤ 72 h)",
                                output=out)
        sel_times = [times[k] for k in t_sel]

        # ------------------------------------------------------------ routing grid
        bb = geo.bbox
        span = max(bb.lon_max - bb.lon_min, bb.lat_max - bb.lat_min)
        res = float(np.clip(span / 110, 0.03, 0.1))
        blocked = [z.geom for z in ref.zones if z.kind == "restricted" and not z.geom.is_empty]
        protected = [z.geom for z in ref.zones if z.kind == "mpa" and not z.geom.is_empty]
        if task.params.get("block_protected"):
            blocked += protected
        foreign = None
        if vessel in ("small_craft", "mechanized"):
            fg = [g for p, g in ref.eez if p.get("sovereign") != "India"]
            if fg:
                from shapely.ops import unary_union
                foreign = unary_union(fg)
                blocked.append(foreign)
        grid = routing.build_grid((bb.lon_min, bb.lat_min, bb.lon_max, bb.lat_max), res, ref.sea_mask, blocked, protected)
        st.tool(self.name, "routing.build_grid", f"{grid.passable.shape[0]}×{grid.passable.shape[1]} grid @ {res:.3f}°, "
                                                 f"{int(grid.passable.sum())} navigable cells")
        # ------------------------------------------------------------ risk cube on routing grid
        LA, LO = np.meshgrid(grid.lats, grid.lons, indexing="ij")
        qpts = np.stack([LA.ravel(), LO.ravel()], axis=-1)
        fine: dict[str, np.ndarray] = {}
        for var, arr in combined.items():
            cube = np.empty((len(t_sel), len(grid.lats), len(grid.lons)))
            for n, k in enumerate(t_sel):
                interp = RegularGridInterpolator((lats_c, lons_c), _fill_nan(arr[k]), bounds_error=False, fill_value=None)
                cube[n] = interp(qpts).reshape(LA.shape)
            fine[var] = cube
        rc = risk_cube(vessel, fine)
        st.tool(self.name, "routing.risk_cube", f"risk cube {len(t_sel)} h × grid from {', '.join(sorted(fine))} (worst of models)")
        t0 = sel_times[0]

        def hidx(t: datetime) -> int:
            return int(np.clip(round((t - t0).total_seconds() / 3600), 0, len(sel_times) - 1))

        def cell_of(lat: float, lon: float) -> tuple[int, int]:
            return (int(np.clip(round((lat - grid.lats[0]) / res), 0, len(grid.lats) - 1)),
                    int(np.clip(round((lon - grid.lons[0]) / res), 0, len(grid.lons) - 1)))

        def risk_at(lat, lon, t):
            i, j = cell_of(lat, lon)
            return float(rc[hidx(t), i, j])

        def value_at(var, lat, lon, t) -> Optional[float]:
            c = fine.get(var)
            if c is None:
                return None
            i, j = cell_of(lat, lon)
            return float(c[hidx(t), i, j])

        s_cell = routing.nearest_passable(grid, o)
        g_cell = routing.nearest_passable(grid, d)
        speed_kmh = speed * 1.852
        options: list[RouteOption] = []
        expanded = 0
        st.stage("REASONING", "Searching routes (time-dependent A*)")
        for rid, label, alpha in ALPHAS:
            try:
                sr = routing.astar(grid, s_cell, g_cell, alpha=alpha, speed_kn=speed, departure=departure,
                                   risk_at=risk_at, use_zone_mult=alpha > 0)
            except (ValueError, RuntimeError) as e:
                out.notes.append(f"{label}: {e}")
                continue
            expanded += sr.nodes_expanded
            coords = self._smooth(sr.coords, grid, rc, res, departure, speed_kmh, hidx, cell_of,
                                  protected if alpha > 0 else [])
            coords = [[o.lon, o.lat]] + coords + [[d.lon, d.lat]]
            opt = self._evaluate(rid, label, coords, departure, speed_kmh, vessel, risk_at, value_at, ref, u)
            options.append(opt)
            st.tool(self.name, "routing.astar", f"{label}: {opt.distance_km:.0f} km, {opt.duration_h:.1f} h, max risk "
                                                f"{opt.max_risk:.2f} ({sr.nodes_expanded} nodes)")
        if not options:
            prior = st.typed.get(self.name)
            if task.params.get("block_protected") and prior is not None and prior.route is not None:
                msg = ("No navigable route avoids the protected area(s) as a hard constraint — the previous recommendation is "
                       "retained; transit may be permitted but fishing inside the zone is not.")
                if msg not in prior.route.notes:
                    prior.route.notes.append(msg)
                    rec = next(o for o in prior.route.options if o.id == prior.route.recommended_id)
                    rec.warnings.append(msg)
                return AgentOutcome(status=AgentStatus.PARTIAL, summary=msg, output=prior, typed=prior)
            return AgentOutcome(status=AgentStatus.FAILED, summary="no navigable route found", output=out)
        # choose recommended: balanced unless it violates a hard zone
        rec = next((x for x in options if x.id == "recommended"), options[0])
        out.route = RouteResult(origin=o, destination=d, origin_name=ep["origin_name"], destination_name=ep["destination_name"],
                                speed_kn=speed, options=options, recommended_id=rec.id,
                                algorithm="time-dependent A* (8-connected grid), line-of-sight smoothing",
                                grid_resolution_deg=round(res, 3),
                                cost_model="d·(1+α·r(x,ETA))·zone_mult + danger_penalty; r = max weighted factor score (worst of models)",
                                nodes_expanded=expanded,
                                notes=out.notes + ([f"cells inside foreign EEZs excluded for {vessel.replace('_', ' ')}"] if foreign is not None else []))
        # per-model samples along the recommended route (for evidence / conflicts)
        lons, lats, cum = spatial.densify_route(rec.coordinates, step_km=5.0)
        for src in (of, wf):
            if src is None:
                continue
            for sid, arrs in src.by_model.items():
                for var in VARS + ("cape",):
                    if var not in arrs:
                        continue
                    samples = []
                    for lo, la, ck in zip(lons, lats, cum):
                        t = departure + timedelta(hours=ck / speed_kmh)
                        k = int(np.argmin([abs((tt - t).total_seconds()) for tt in src.times]))
                        i = int(np.argmin(np.abs(src.lats - la)))
                        j = int(np.argmin(np.abs(src.lons - lo)))
                        v = arrs[var][k, i, j]
                        samples.append({"time": t.isoformat(), "lat": float(la), "lon": float(lo),
                                        "value": None if np.isnan(v) else round(float(v), 2)})
                    out.per_model_samples.setdefault(sid, {})[var] = samples
        out.geojson = self._geojson(out.route)
        st.typed[self.name] = out
        summ = (f"{rec.label}: {rec.distance_km:.0f} km ({rec.distance_nm:.0f} nm), {rec.duration_h:.1f} h at {speed:g} kn, "
                f"max segment risk {rec.max_risk:.2f} ({rec.level.value})")
        if rec.zone_violations:
            summ += f"; enters {', '.join(z.name for z in rec.zone_violations)}"
        return AgentOutcome(status=AgentStatus.SUCCEEDED, summary=summ, output=out, typed=out,
                            sources=sorted({s for v in out.risk_field_sources.values() for s in v}),
                            tools=self.tools, confidence=None)

    # ------------------------------------------------------------------ smoothing
    def _smooth(self, coords, grid, rc, res, departure, speed_kmh, hidx, cell_of, protected):
        if len(coords) <= 2:
            return coords
        cum = [0.0]
        for a, b in zip(coords[:-1], coords[1:]):
            cum.append(cum[-1] + spatial.GEOD.inv(a[0], a[1], b[0], b[1])[2] / 1000)
        risks = []
        for (lo, la), c in zip(coords, cum):
            i, j = cell_of(la, lo)
            risks.append(float(rc[hidx(departure + timedelta(hours=c / speed_kmh)), i, j]))
        prot_in = [any(shapely.contains_xy(g, lo, la) for g in protected) for lo, la in coords]

        def ok(i: int, j: int) -> bool:
            a, b = coords[i], coords[j]
            dist = spatial.GEOD.inv(a[0], a[1], b[0], b[1])[2] / 1000
            n = max(2, int(dist / (res * 111 * 0.5)))
            limit = max(risks[i:j + 1]) + 0.02
            allow_prot = any(prot_in[i:j + 1])
            for k in range(1, n):
                f = k / n
                lo, la = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                ci, cj = cell_of(la, lo)
                if not grid.passable[ci, cj]:
                    return False
                t = departure + timedelta(hours=(cum[i] + dist * f) / speed_kmh)
                if rc[hidx(t), ci, cj] > limit:
                    return False
                if not allow_prot and protected and any(shapely.contains_xy(g, lo, la) for g in protected):
                    return False
            return True

        out = [coords[0]]
        i = 0
        while i < len(coords) - 1:
            j = min(len(coords) - 1, i + 60)
            while j > i + 1 and not ok(i, j):
                j -= 1
            out.append(coords[j])
            i = j
        return out

    # ------------------------------------------------------------------ evaluation
    def _evaluate(self, rid, label, coords, departure, speed_kmh, vessel, risk_at, value_at, ref, u) -> RouteOption:
        lons, lats, cum = spatial.densify_route(coords, step_km=1.0)
        total = float(cum[-1])
        etas = [departure + timedelta(hours=c / speed_kmh) for c in cum]
        risks = np.array([risk_at(la, lo, t) for lo, la, t in zip(lons, lats, etas)])
        seg_len = max(8.0, total / 24)
        segments: list[RouteSegment] = []
        start_idx = 0
        ths = THRESHOLDS[vessel]
        while start_idx < len(cum) - 1:
            end_idx = int(np.searchsorted(cum, cum[start_idx] + seg_len))
            end_idx = min(max(end_idx, start_idx + 1), len(cum) - 1)
            sl = slice(start_idx, end_idx + 1)
            k = start_idx + int(np.argmax(risks[sl]))
            vals = {v: value_at(v, lats[k], lons[k], etas[k]) for v in VARS}
            drivers = [f for f in ("wave_height", "wind_speed", "wind_gusts", "current_speed", "precipitation")
                       if vals.get(f) is not None and f in ths and level_for(vals[f], ths[f]) != RiskLevel.NOMINAL]
            r = float(risks[sl].max())
            lvl = RiskLevel.DANGER if r >= 0.999 else RiskLevel.CAUTION if r >= 0.5 else RiskLevel.NOMINAL
            segments.append(RouteSegment(
                index=len(segments), start=GeoPoint(lat=float(lats[start_idx]), lon=float(lons[start_idx])),
                end=GeoPoint(lat=float(lats[end_idx]), lon=float(lons[end_idx])),
                distance_km=round(float(cum[end_idx] - cum[start_idx]), 2), eta_start=etas[start_idx], eta_end=etas[end_idx],
                risk=round(r, 3), level=lvl,
                wave_height_m=None if vals["wave_height"] is None else round(vals["wave_height"], 2),
                wind_kmh=None if vals["wind_speed"] is None else round(vals["wind_speed"], 1),
                current_kmh=None if vals["current_speed"] is None else round(vals["current_speed"], 2), drivers=drivers))
            start_idx = end_idx
        # zones along the route
        violations: list[ZoneHit] = []
        warnings: list[str] = []
        when = departure
        for z in ref.all_zones():
            if z.geom.is_empty or (z.kind == "seasonal_restriction" and not z.active_at(when, vessel)):
                continue
            dist_in, idx = spatial.first_entry_along(lons, lats, cum, z.geom)
            if dist_in is not None and (dist_in < 2.0 or total - dist_in < 2.0):
                # the port / end-point itself lies in or at the edge of the zone: report, don't call it an entry
                warnings.append(f"{'Departure' if dist_in < 2.0 else 'Arrival'} point lies at or inside {z.name}"
                                f"{' (approximate outline)' if z.approximate else ''} — check local access rules.")
                dist_in = None
            if dist_in is not None:
                eta = etas[idx]
                inside = shapely.contains_xy(z.geom, lons, lats)
                km_inside = float(np.sum(np.diff(cum)[inside[1:] | inside[:-1]])) if len(cum) > 1 else 0.0
                hit = ZoneHit(zone_id=z.id, name=z.name, kind=z.kind, inside=True, distance_km=round(dist_in, 1),
                              distance_nm=round(km_to_nm(dist_in), 1), nearest_point=GeoPoint(lat=float(lats[idx]), lon=float(lons[idx])),
                              authority=z.authority, source=z.source, approximate=z.approximate,
                              note=f"entered after {dist_in:.1f} km (~{(eta - departure).total_seconds() / 60:.0f} min, "
                                   f"ETA {eta.astimezone(IST):%H:%M} IST)")
                violations.append(hit)
                warnings.append(f"WARNING: route enters {z.name}{' (approximate outline)' if z.approximate else ''} "
                                f"{dist_in:.1f} km after departure — in about {(eta - departure).total_seconds() / 60:.0f} minutes "
                                f"(ETA {eta.astimezone(IST):%H:%M} IST) and stays inside for {km_inside:.1f} km.")
            elif z.kind in ("mpa", "restricted"):
                md, mi = spatial.min_distance_route_km(lons, lats, z.geom)
                if md < 5.0:
                    eta = etas[mi]
                    where = "skirts the edge of" if md < 0.5 else f"passes {md:.1f} km from"
                    warnings.append(f"Route {where} {z.name} about {(eta - departure).total_seconds() / 3600:.1f} h after departure "
                                    f"(ETA {eta.astimezone(IST):%d %b %H:%M} IST){' — approximate outline' if z.approximate else ''}.")
        bmin = None
        for props, g in ref.boundaries:
            md, mi = spatial.min_distance_route_km(lons, lats, g)
            if bmin is None or md < bmin:
                bmin = md
            if md < 10:
                warnings.append(f"Route comes within {md:.1f} km of the {props.get('name')} maritime boundary.")
        mean_r = float(risks.mean()) if len(risks) else 0.0
        max_r = float(risks.max()) if len(risks) else 0.0
        exposure = float(np.trapezoid(risks, cum)) if len(risks) > 1 else 0.0
        lvl = RiskLevel.DANGER if max_r >= 0.999 else RiskLevel.CAUTION if max_r >= 0.5 else RiskLevel.NOMINAL
        return RouteOption(id=rid, label=label, coordinates=[[round(a, 5), round(b, 5)] for a, b in coords],
                           distance_km=round(total, 1), distance_nm=round(km_to_nm(total), 1),
                           duration_h=round(total / speed_kmh, 2), departure=departure,
                           arrival=departure + timedelta(hours=total / speed_kmh), max_risk=round(max_r, 3),
                           mean_risk=round(mean_r, 3), exposure=round(exposure, 1), level=lvl, segments=segments,
                           zone_violations=violations, boundary_min_distance_km=None if bmin is None else round(bmin, 1),
                           warnings=warnings)

    @staticmethod
    def _geojson(r: RouteResult) -> dict:
        feats = []
        for opt in r.options:
            feats.append({"type": "Feature", "properties": {"kind": "route", "id": opt.id, "label": opt.label,
                                                             "recommended": opt.id == r.recommended_id,
                                                             "distance_km": opt.distance_km, "max_risk": opt.max_risk},
                          "geometry": {"type": "LineString", "coordinates": opt.coordinates}})
            if opt.id == r.recommended_id:
                for s in opt.segments:
                    feats.append({"type": "Feature", "properties": {"kind": "segment", "risk": s.risk, "level": s.level.value,
                                                                     "index": s.index, "wave": s.wave_height_m, "wind": s.wind_kmh,
                                                                     "eta": s.eta_start.isoformat()},
                                  "geometry": {"type": "LineString", "coordinates": [[s.start.lon, s.start.lat], [s.end.lon, s.end.lat]]}})
        return {"type": "FeatureCollection", "features": feats}
