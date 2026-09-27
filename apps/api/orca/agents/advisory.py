"""Agent 11 — Advisory & Warnings agent.

Collects *official and international advisories* — never model output:
GDACS tropical-cyclone events (tracks, wind radii, uncertainty cones),
IMD marine / fishermen warnings and INCOIS ocean-state alerts (adapters;
excluded and flagged when not accessible). Computes the geodesic distance
from every sample point to each cyclone's latest and forecast positions and
tests whether any point falls inside a wind-radius polygon.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

import shapely
from pydantic import BaseModel, Field
from shapely.geometry import shape

from ..core import spatial
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, GeoPoint, RiskLevel
from ..core.schemas.provenance import Provenance
from .base import Agent, AgentOutcome, RunState


class CycloneInfo(BaseModel):
    event_id: Any
    name: str
    alert_level: Optional[str] = None
    active: bool
    hours_since_last_advisory: Optional[float] = None
    max_wind_kmh: Optional[float] = None
    severity_text: Optional[str] = None
    track_source: Optional[str] = None
    latest_position: Optional[GeoPoint] = None
    latest_time: Optional[datetime] = None
    min_distance_km: Optional[float] = None
    nearest_sample: Optional[str] = None
    inside_wind_radius_kmh: Optional[int] = None
    report_url: Optional[str] = None
    track: list[dict] = Field(default_factory=list)
    geojson: Optional[dict] = None


class OfficialAdvisory(BaseModel):
    source: str
    title: str
    text: str = ""
    level: RiskLevel = RiskLevel.CAUTION
    area: str = ""
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    provenance: Optional[Provenance] = None


class SourceCheck(BaseModel):
    source: str
    source_id: str
    status: str
    detail: str = ""


class AdvisoryOutput(BaseModel):
    cyclones: list[CycloneInfo] = Field(default_factory=list)
    active_cyclones: int = 0
    nearest_active_km: Optional[float] = None
    official: list[OfficialAdvisory] = Field(default_factory=list)
    official_available: bool = False
    official_level: RiskLevel = RiskLevel.UNKNOWN
    sources_checked: list[SourceCheck] = Field(default_factory=list)
    gdacs_provenance: Optional[Provenance] = None
    region_id: Optional[str] = None


def region_for(ref, p: GeoPoint) -> Optional[str]:
    order = ["gujarat_coast", "maharashtra_coast", "goa_coast", "karnataka_coast", "kerala_coast", "tamil_nadu_coast",
             "andhra_coast", "odisha_coast", "west_bengal_coast", "lakshadweep_sea", "andaman_sea",
             "gulf_of_mannar", "palk_bay", "arabian_sea", "bay_of_bengal"]
    regs = {r["id"]: r for r in ref.regions}
    for rid in order:
        b = regs[rid]["bbox"]
        if b[0] <= p.lon <= b[2] and b[1] <= p.lat <= b[3]:
            return rid
    return None


class AdvisoryAgent(Agent):
    name = "advisory"
    title = "Advisory & Warnings Agent"
    responsibility = "Official / international warnings: cyclones (GDACS), IMD marine warnings, INCOIS ocean-state alerts"
    tools = ["gdacs.cyclones", "imd.marine_warnings", "incois.ocean_state_alerts", "spatial.distance", "spatial.point_in_polygon"]
    consumes = ["geospatial"]
    output_model = AdvisoryOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        reg = st.ctx.registry
        geo = st.typed.get("geospatial")
        u = st.bb.understanding
        samples = geo.samples if geo else []
        out = AdvisoryOutput()
        rid = (u.region.id if (u and u.region) else None) or (region_for(st.ctx.ref, samples[0].point) if samples else None)
        out.region_id = rid
        st.stage("RETRIEVAL", "Checking official and international advisories")
        st.tool(self.name, "gdacs.cyclones", "querying GDACS tropical-cyclone events (Indian Ocean)", source_id="gdacs")
        (events, gprov, gfail), (imd_w, imd_prov, imd_f), (inc_a, inc_prov, inc_f) = await asyncio.gather(
            reg.gdacs.cyclones(), reg.imd.marine_warnings(rid or ""), reg.incois.ocean_state_alerts(rid or ""))
        failures = gfail + imd_f + inc_f
        out.gdacs_provenance = gprov
        out.sources_checked.append(SourceCheck(source="GDACS", source_id="gdacs", status="OK" if not gfail else gfail[0].status,
                                               detail=f"{len(events)} TC event(s) in AOI" if not gfail else gfail[0].reason))
        for ev in events:
            ci = CycloneInfo(event_id=ev["event_id"], name=ev["name"], alert_level=ev["alert_level"], active=ev["active"],
                             hours_since_last_advisory=ev["hours_since_last_advisory"], max_wind_kmh=ev["max_wind_kmh"],
                             severity_text=ev["severity_text"], track_source=ev["track_source"], report_url=ev["report_url"],
                             track=[{"time": t["time"], "lat": t["point"].lat, "lon": t["point"].lon, "label": t["label"]}
                                    for t in ev["track"]])
            positions = [t["point"] for t in ev["track"]] or [ev["centroid"]]
            ci.latest_position = positions[-1]
            ci.latest_time = ev["track"][-1]["time"] if ev["track"] else ev.get("to")
            best = None
            for s in samples:
                for pos in positions:
                    d = spatial.distance_km(s.point, pos)
                    if best is None or d < best[0]:
                        best = (d, s.id)
                for wr in sorted(ev["wind_radii"], key=lambda w: -w["threshold_kmh"]):
                    g = shape(wr["geometry"])
                    if shapely.contains_xy(g, s.point.lon, s.point.lat):
                        if ci.inside_wind_radius_kmh is None or wr["threshold_kmh"] > ci.inside_wind_radius_kmh:
                            ci.inside_wind_radius_kmh = wr["threshold_kmh"]
            if best:
                ci.min_distance_km, ci.nearest_sample = round(best[0], 1), best[1]
            feats = [{"type": "Feature", "properties": {"kind": "wind_radius", "threshold_kmh": w["threshold_kmh"],
                                                         "time": w["time"], "name": ev["name"]}, "geometry": w["geometry"]}
                     for w in ev["wind_radii"]]
            if ev.get("cone"):
                feats.append({"type": "Feature", "properties": {"kind": "cone", "name": ev["name"]}, "geometry": ev["cone"]})
            if ci.track:
                feats.append({"type": "Feature", "properties": {"kind": "track", "name": ev["name"]},
                              "geometry": {"type": "LineString", "coordinates": [[t["lon"], t["lat"]] for t in ci.track]}})
                feats += [{"type": "Feature", "properties": {"kind": "track_point", "label": t["label"], "name": ev["name"]},
                           "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]}} for t in ci.track]
            ci.geojson = {"type": "FeatureCollection", "features": feats}
            out.cyclones.append(ci)
            st.tool(self.name, "spatial.distance",
                    f"{ci.name} ({'ACTIVE' if ci.active else 'inactive, last advisory ' + str(ci.hours_since_last_advisory) + ' h ago'}): "
                    f"{ci.min_distance_km} km from nearest sample point")
        act = [c for c in out.cyclones if c.active]
        out.active_cyclones = len(act)
        out.nearest_active_km = min((c.min_distance_km for c in act if c.min_distance_km is not None), default=None)

        # national warnings
        for w in imd_w:
            out.official.append(OfficialAdvisory(source="IMD", title=w.get("title", "Marine warning"), text=w.get("text", ""),
                                                 level=RiskLevel(w.get("level", "CAUTION")), area=w.get("area", ""),
                                                 issued_at=imd_prov.issued_at if imd_prov else None, provenance=imd_prov))
        for a in inc_a:
            out.official.append(OfficialAdvisory(source="INCOIS", title=a.get("title", "Ocean state alert"), text=a.get("text", ""),
                                                 level=RiskLevel(a.get("level", "CAUTION")), area=a.get("area", ""),
                                                 issued_at=inc_prov.issued_at if inc_prov else None, provenance=inc_prov))
        out.sources_checked.append(SourceCheck(source="IMD", source_id="imd", status="OK" if not imd_f else imd_f[0].status,
                                               detail=f"{len(imd_w)} warning(s)" if not imd_f else imd_f[0].reason))
        out.sources_checked.append(SourceCheck(source="INCOIS", source_id="incois", status="OK" if not inc_f else inc_f[0].status,
                                               detail=f"{len(inc_a)} alert(s)" if not inc_f else inc_f[0].reason))
        for sc in out.sources_checked[1:]:
            st.tool(self.name, f"{sc.source_id}.warnings", f"{sc.source}: {sc.detail}", source_id=sc.source_id, ok=sc.status == "OK")
        out.official_available = not imd_f or not inc_f
        if out.official_available:
            lv = [o.level for o in out.official]
            out.official_level = (RiskLevel.DANGER if RiskLevel.DANGER in lv else RiskLevel.CAUTION if RiskLevel.CAUTION in lv
                                  else RiskLevel.NOMINAL)
        st.typed[self.name] = out
        summ = (f"{out.active_cyclones} active cyclone(s)" + (f", nearest {out.nearest_active_km:.0f} km" if out.nearest_active_km else "")
                + f"; {len(out.official)} official warning(s)" + ("" if out.official_available else " (IMD/INCOIS not accessible)"))
        status = AgentStatus.SUCCEEDED if not gfail and out.official_available else AgentStatus.PARTIAL if not gfail or out.official_available else AgentStatus.FAILED
        srcs = (["gdacs"] if not gfail else []) + (["imd"] if not imd_f else []) + (["incois"] if not inc_f else [])
        return AgentOutcome(status=status, summary=summ, output=out, typed=out, sources=srcs,
                            tools=["gdacs.cyclones", "imd.marine_warnings", "incois.ocean_state_alerts", "spatial.distance"],
                            failures=failures)
