"""Agent 7 — Hazard & Risk agent.

Combines waves, wind, gusts, currents, rain, lightning potential, visibility,
cyclone proximity, official warnings and boundary proximity into the
deterministic orca-risk-1.0 model. Every source contributes its own samples
(all sample points × all hours of the window, or the route at ETA) so that
worst cases, onsets and cross-source spreads are computed, not guessed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..core import risk as rm
from ..core import spatial
from ..core.clock import parse_utc
from ..core.schemas.assessment import RiskAssessment, RiskFactor
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, DataKind, FreshnessStatus, GeoPoint, RiskLevel
from .base import Agent, AgentOutcome, RunState

OCEAN_FACTORS = {"wave_height": "wave_height", "current_speed": "current_speed"}
WX_FACTORS = {"wind_speed": "wind_speed", "wind_gusts": "wind_gusts", "precipitation": "precipitation",
              "cape": "cape", "visibility": "visibility"}


CAPE_RAIN_GATE = 0.5   # mm/h


def _gate_cape(cape_srcs, rain_srcs):
    """Keep CAPE only where the same model, location and hour also has rain ≥ gate; otherwise scale it down 60 %."""
    rain = {(r.source_id, s.time, s.location.lat if s.location else None, s.location.lon if s.location else None): s.value
            for r in rain_srcs for s in r.samples}
    out = []
    for src in cape_srcs:
        gated = []
        for s in src.samples:
            key = (src.source_id, s.time, s.location.lat if s.location else None, s.location.lon if s.location else None)
            r = rain.get(key)
            v = s.value if (r is not None and r >= CAPE_RAIN_GATE) else (s.value * 0.4 if s.value is not None else None)
            gated.append(rm.Sample(time=s.time, value=v, location=s.location))
        src.samples = gated
        src.meta["gated_by"] = f"precipitation ≥ {CAPE_RAIN_GATE} mm/h"
        out.append(src)
    return out


class TimelinePoint(BaseModel):
    time: datetime
    score: float
    level: RiskLevel
    drivers: list[str] = Field(default_factory=list)
    wave_height_m: Optional[float] = None
    wind_kmh: Optional[float] = None


class StationRisk(BaseModel):
    id: str
    label: str
    point: GeoPoint
    decision: str
    risk_index: Optional[float]
    drivers: list[str]
    worst_wave_m: Optional[float] = None
    worst_wind_kmh: Optional[float] = None


class HazardOutput(BaseModel):
    mode: str
    assessment: RiskAssessment
    timeline: list[TimelinePoint] = Field(default_factory=list)
    stations: list[StationRisk] = Field(default_factory=list)
    extended: Optional[RiskAssessment] = None
    compliance: list[str] = Field(default_factory=list)


def _samples_from_points(pdata, var: str, start: datetime, end: datetime, only_ids: Optional[set] = None):
    """PointData -> list[SourceSamples] for one variable."""
    out = []
    if pdata is None:
        return out
    for sid, per_pt in pdata.by_model.items():
        m = pdata.models[sid]
        samples, prov, gdist = [], None, None
        for sample_id, pt, d in zip(pdata.sample_ids, pdata.sample_points, per_pt):
            if only_ids and sample_id not in only_ids:
                continue
            ts = d.get(var)
            if ts is None:
                continue
            prov = prov or ts.provenance
            if gdist is None and ts.grid_location:
                gdist = spatial.distance_km(ts.location, ts.grid_location)
            for t, v in ts.window(start, end):
                samples.append(rm.Sample(time=t, value=v, location=pt))
        if samples:
            out.append(rm.SourceSamples(source=m.spec.name, source_id=sid, kind=DataKind.FORECAST, samples=samples,
                                        freshness=prov.freshness.status if prov else FreshnessStatus.LIVE,
                                        units=prov.units if prov else "",
                                        meta={"provenance": prov, "lineage": m.lineage, "grid_distance_km": gdist}))
    return out


class HazardAgent(Agent):
    name = "hazard"
    title = "Hazard & Risk Agent"
    responsibility = "Deterministic multi-factor risk model → GO / CAUTION / DON'T GO / INSUFFICIENT DATA"
    tools = ["risk.evaluate (orca-risk-1.0)", "risk.point_risk", "spatial.distance", "spatial.point_in_polygon"]
    consumes = ["ocean", "weather", "advisory", "geospatial", "route"]
    output_model = HazardOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        u = st.bb.understanding
        vessel = u.vessel_class.value
        start, end = u.time_window.start, u.time_window.end
        if task.params.get("extend_h"):
            end = end + timedelta(hours=float(task.params["extend_h"]))
        geo = st.typed.get("geospatial")
        ocean, wx = st.typed.get("ocean"), st.typed.get("weather")
        adv = st.typed.get("advisory")
        route = st.typed.get("route")
        mode = "route" if route is not None and route.route is not None else ("region" if geo and geo.mode == "region" else "point")
        st.stage("ALIGNMENT", f"Aligning all sources to the {mode} space-time window {u.time_window.label}")

        def build_inputs(only_ids: Optional[set] = None) -> dict[str, rm.FactorInput]:
            inputs: dict[str, rm.FactorInput] = {}
            if mode == "route":
                for sid, per_var in route.per_model_samples.items():
                    m = st.ctx.registry.models.get(sid)
                    for var, samples in per_var.items():
                        if var not in rm.THRESHOLDS[vessel]:
                            continue
                        ss = [rm.Sample(time=parse_utc(s["time"]), value=s["value"], location=GeoPoint(lat=s["lat"], lon=s["lon"]))
                              for s in samples if s["value"] is not None]
                        if not ss:
                            continue
                        fi = inputs.setdefault(var, rm.FactorInput(var))
                        fi.sources.append(rm.SourceSamples(source=m.spec.name if m else sid, source_id=sid, kind=DataKind.FORECAST,
                                                           samples=ss, units=rm.THRESHOLDS[vessel][var].units,
                                                           meta={"lineage": m.lineage if m else sid, "grid_distance_km": 0.0,
                                                                 "route": True}))
                if "cape" in inputs and "precipitation" in inputs:
                    inputs["cape"].sources = _gate_cape(inputs["cape"].sources, inputs["precipitation"].sources)
            else:
                for var in OCEAN_FACTORS:
                    ss = _samples_from_points(ocean, var, start, end, only_ids)
                    if ss:
                        inputs[var] = rm.FactorInput(var, ss)
                for var in WX_FACTORS:
                    ss = _samples_from_points(wx, var, start, end, only_ids)
                    if var == "cape":
                        ss = _gate_cape(ss, _samples_from_points(wx, "precipitation", start, end, only_ids))
                    if ss:
                        inputs[var] = rm.FactorInput(var, ss, note="CAPE counted only where the same model predicts "
                                                                   f"≥ {CAPE_RAIN_GATE} mm/h rain (convection signal)")
            # cyclone proximity
            if adv is not None:
                act = [c for c in adv.cyclones if c.active]
                if act:
                    pts: list[GeoPoint]
                    if mode == "route":
                        rec = next(o for o in route.route.options if o.id == route.route.recommended_id)
                        pts = [GeoPoint(lat=c[1], lon=c[0]) for c in rec.coordinates]
                    else:
                        pts = [s.point for s in geo.samples if not only_ids or s.id in only_ids]
                    ss = []
                    for c in act:
                        positions = [GeoPoint(lat=t["lat"], lon=t["lon"]) for t in c.track] or [c.latest_position]
                        dmin = min(spatial.distance_km(p, q) for p in pts for q in positions)
                        if c.inside_wind_radius_kmh:
                            dmin = 0.0
                        ss.append(rm.Sample(time=c.latest_time, value=round(dmin, 1), location=c.latest_position))
                    inputs["cyclone_distance"] = rm.FactorInput("cyclone_distance", [rm.SourceSamples(
                        source="GDACS (track: " + (act[0].track_source or "n/a") + ")", source_id="gdacs", kind=DataKind.ADVISORY,
                        samples=ss, freshness=adv.gdacs_provenance.freshness.status if adv.gdacs_provenance else FreshnessStatus.LIVE,
                        units="km", meta={"provenance": adv.gdacs_provenance, "lineage": "gdacs"})])
            # boundary proximity (fishing craft)
            if vessel in ("small_craft", "mechanized"):
                bd = None
                if mode == "route":
                    rec = next(o for o in route.route.options if o.id == route.route.recommended_id)
                    bd = rec.boundary_min_distance_km
                elif geo and geo.primary:
                    b = next((z for z in geo.primary.zones if z.kind == "maritime_boundary"), None)
                    bd = b.distance_km if b else None
                if bd is not None:
                    inputs["boundary_distance"] = rm.FactorInput("boundary_distance", [rm.SourceSamples(
                        source="Marine Regions boundary + ORCA geodesy", source_id="marine_regions", kind=DataKind.REFERENCE,
                        samples=[rm.Sample(time=None, value=bd)], freshness=FreshnessStatus.STATIC, units="km",
                        meta={"lineage": "marine_regions"})])
            return inputs

        advisory_in = None
        if adv is not None:
            advisory_in = rm.AdvisoryInput(available=adv.official_available, level=adv.official_level,
                                           items=[o.model_dump() for o in adv.official],
                                           note=("; ".join(f"{o.source}: {o.title}" for o in adv.official) if adv.official_available
                                                 else "IMD marine warnings and INCOIS ocean-state alerts are not machine-accessible "
                                                      "from this deployment — consult official bulletins before departure"))
        compliance = []
        if geo and geo.primary:
            for z in geo.primary.zones:
                if z.inside and z.kind in ("mpa", "restricted"):
                    compliance.append(f"Assessment point lies inside {z.name} ({z.kind}{', approximate outline' if z.approximate else ''}).")
            for r in geo.primary.regulations:
                if r.get("active"):
                    compliance.append(f"Seasonal restriction in force: {r['name']}.")
        if route is not None and route.route is not None:
            rec = next(o for o in route.route.options if o.id == route.route.recommended_id)
            compliance += rec.warnings

        st.stage("REASONING", "Applying deterministic risk model orca-risk-1.0")
        inputs = build_inputs()
        assessment = rm.evaluate(vessel, start, end, inputs, advisory_in, zone_notes=None)
        self._cyclone_none(assessment, adv)
        st.tool(self.name, "risk.evaluate", f"decision {assessment.decision.value}; risk index {assessment.risk_index}; "
                                            f"rules: {'; '.join(r.split(' ')[0] for r in assessment.rules_fired + assessment.conservative_adjustments)}")
        out = HazardOutput(mode=mode, assessment=assessment, compliance=compliance)

        # hourly timeline (point / region mode)
        if mode != "route":
            hours = int((end - start).total_seconds() // 3600) + 1
            for h in range(hours):
                t = (start + timedelta(hours=h)).replace(minute=0, second=0, microsecond=0)
                vals: dict[str, Optional[float]] = {}
                for var in ("wave_height", "wind_speed", "wind_gusts", "current_speed", "precipitation"):
                    fi = inputs.get(var)
                    if not fi:
                        continue
                    vs = [s.value for src in fi.sources for s in src.samples if s.time == t and s.value is not None]
                    if vs:
                        vals[var] = max(vs)
                if vals:
                    sc, lvl, drv = rm.point_risk(vessel, vals)
                    out.timeline.append(TimelinePoint(time=t, score=sc, level=lvl, drivers=drv,
                                                      wave_height_m=vals.get("wave_height"), wind_kmh=vals.get("wind_speed")))
        # per-station assessment for regional questions
        if mode == "region":
            for s in geo.samples:
                a = rm.evaluate(vessel, start, end, build_inputs({s.id}), advisory_in)
                wv = next((f.value for f in a.factors if f.id == "wave_height"), None)
                wn = next((f.value for f in a.factors if f.id == "wind_speed"), None)
                out.stations.append(StationRisk(id=s.id, label=s.label, point=s.point, decision=a.decision.value,
                                                risk_index=a.risk_index, drivers=a.drivers, worst_wave_m=wv, worst_wind_kmh=wn))
            st.tool(self.name, "risk.evaluate", f"{len(out.stations)} coastal stations assessed individually")
        tag = task.params.get("tag")
        if tag:
            st.typed[f"{self.name}:{tag}"] = {"assessment": assessment, "inputs": inputs, "output": out}
            return AgentOutcome(status=AgentStatus.SUCCEEDED, output=out, tools=["risk.evaluate"],
                                summary=f"extended horizon (+{task.params.get('extend_h')} h, to {end:%d %b %H:%MZ}): "
                                        f"{assessment.decision.value}")
        st.stage("DECISION", f"Decision: {assessment.decision.value}")
        st.typed[self.name] = {"assessment": assessment, "inputs": inputs, "output": out}
        st.bb.risk = assessment
        summ = (f"{assessment.decision.value}"
                + (f" (risk index {assessment.risk_index:.0f})" if assessment.risk_index is not None else "")
                + (f"; drivers: {', '.join(assessment.drivers)}" if assessment.drivers else ""))
        return AgentOutcome(status=AgentStatus.SUCCEEDED, summary=summ, output=out, typed=st.typed[self.name],
                            tools=["risk.evaluate", "risk.point_risk"], confidence=None)

    @staticmethod
    def _cyclone_none(a: RiskAssessment, adv) -> None:
        if adv is None or any(f.id == "cyclone_distance" for f in a.factors):
            return
        if adv.gdacs_provenance is None:
            a.factors.append(RiskFactor(id="cyclone_distance", label="Tropical cyclone proximity", critical=False,
                                        level=RiskLevel.UNKNOWN, available=False,
                                        explanation="GDACS unavailable — cyclone check could not be performed"))
            return
        inactive = [c for c in adv.cyclones if not c.active]
        note = "No active tropical cyclone in the North Indian Ocean (GDACS)"
        if inactive:
            c = inactive[0]
            note += f"; {c.name} last advised {c.hours_since_last_advisory:.0f} h ago (treated as inactive)"
        a.factors.append(RiskFactor(id="cyclone_distance", label="Tropical cyclone proximity", critical=False,
                                    level=RiskLevel.NOMINAL, units="km", explanation=note, available=True,
                                    threshold=None, score=0.0))
