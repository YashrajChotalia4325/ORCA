"""Agent 5 — Marine biology / Fisheries agent.

Official INCOIS PFZ advisories when accessible; otherwise (and in addition)
ORCA's deterministic productivity indicator from satellite SST fronts and
chlorophyll-a. Outputs are explicitly probabilistic habitat indicators.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import shapely
from pydantic import BaseModel, Field

from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, GeoPoint
from ..core.schemas.geo import CandidateZone
from ..core.schemas.provenance import Provenance
from ..reasoning import fisheries as fx
from .base import Agent, AgentOutcome, RunState

DISCLAIMER = ("ORCA-derived productivity indicator (SST fronts + chlorophyll). It indicates oceanographic conditions "
              "often associated with fish aggregation; it does not indicate that fish are present and is not an "
              "official INCOIS Potential Fishing Zone advisory.")


class FisheriesOutput(BaseModel):
    zones: list[CandidateZone] = Field(default_factory=list)
    official_pfz: list[dict] = Field(default_factory=list)
    official_available: bool = False
    official_status: str = ""
    method: str = ""
    front_threshold_c_per_km: Optional[float] = None
    grad_p90_c_per_km: Optional[float] = None
    sst_product_time: Optional[str] = None
    chl_product_time: Optional[str] = None
    cells_analysed: int = 0
    candidate_cells: int = 0
    sst_provenance: Optional[Provenance] = None
    chl_provenance: Optional[Provenance] = None
    pfz_provenance: Optional[Provenance] = None
    disclaimer: str = DISCLAIMER
    geojson: Optional[dict] = None


class FisheriesAgent(Agent):
    name = "fisheries"
    title = "Marine Biology & Fisheries Agent"
    responsibility = "INCOIS PFZ advisories (when accessible) and a deterministic SST-front / chlorophyll productivity indicator"
    tools = ["incois.pfz", "noaa_coastwatch.grid", "fronts.gradient_analysis", "fronts.cluster", "gebco.depth"]
    consumes = ["geospatial"]
    output_model = FisheriesOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        reg = st.ctx.registry
        ref = st.ctx.ref
        geo = st.typed.get("geospatial")
        origin = geo.origin_place.point if geo.origin_place else geo.samples[0].point
        bbox = geo.bbox
        out = FisheriesOutput()
        st.stage("RETRIEVAL", "Retrieving satellite fields for productivity analysis")
        st.tool(self.name, "noaa_coastwatch.grid", "SST (0.1°) and chlorophyll (9 km) fields over analysis box",
                source_id="noaa_coastwatch")
        (sst, f1), (chl, f2), (pfz, pprov, f3) = await asyncio.gather(
            reg.erddap.grid("sst", bbox, stride=2), reg.erddap.grid("chlorophyll", bbox, stride=1), reg.incois.pfz(bbox))
        failures = f1 + f2 + f3
        out.official_pfz = pfz
        out.official_available = not f3
        out.official_status = "received" if not f3 else f3[0].status
        out.pfz_provenance = pprov
        st.tool(self.name, "incois.pfz", "INCOIS PFZ: " + (f"{len(pfz)} advisory feature(s)" if not f3 else f"excluded — {f3[0].status}"),
                source_id="incois", ok=not f3)
        if sst is None:
            st.typed[self.name] = out
            return AgentOutcome(status=AgentStatus.FAILED, summary="satellite SST unavailable — productivity indicator not computed",
                                output=out, typed=out, failures=failures)
        out.sst_provenance = sst.provenance
        out.sst_product_time = sst.times[0].isoformat()
        if chl is not None:
            out.chl_provenance = chl.provenance
            out.chl_product_time = chl.times[0].isoformat()
        st.stage("CORRELATION", "Correlating SST fronts with chlorophyll-a")
        india = ref.india_eez

        def mask(lons, lats):
            return ref.sea_mask(lons, lats) & shapely.contains_xy(india, lons, lats)

        fa = fx.analyse(sst, chl, origin, mask)
        st.tool(self.name, "fronts.gradient_analysis",
                f"|∇SST| P90 {fa.grad_p90:.3f} °C/km → front threshold {fa.g0:.3f} °C/km; {fa.front_cells} front cells of {fa.n_cells}")
        out.zones, out.method = fa.zones, fa.method
        out.front_threshold_c_per_km, out.grad_p90_c_per_km = fa.g0, fa.grad_p90
        out.cells_analysed, out.candidate_cells = fa.n_cells, fa.n_candidate
        if out.zones:
            depths, f4 = await reg.gebco.depths([z.centroid for z in out.zones])
            failures += f4
            for z, d in zip(out.zones, depths):
                if d is not None and d.value is not None:
                    z.depth_m = d.value
                    z.rationale.append(f"depth {d.value:.0f} m (GEBCO)")
        st.tool(self.name, "fronts.cluster", f"{len(out.zones)} candidate zone(s) from {fa.n_candidate} candidate cells")
        feats = [{"type": "Feature", "properties": {"id": z.id, "score": z.score, "kind": "orca_zone", "official": False,
                                                     "mean_chl": z.mean_chl_mg_m3, "front": z.max_front_gradient_c_per_km},
                  "geometry": {"type": "Polygon", "coordinates": [z.polygon]}} for z in out.zones]
        for f in pfz:
            feats.append({**f, "properties": {**(f.get("properties") or {}), "kind": "incois_pfz", "official": True}})
        out.geojson = {"type": "FeatureCollection", "features": feats}
        st.typed[self.name] = out
        summ = (f"{len(out.zones)} ORCA candidate zone(s)" + (f", best {out.zones[0].id} score {out.zones[0].score:.2f} "
                f"{out.zones[0].distance_from_origin_km:.0f} km from origin" if out.zones else "")
                + (f"; {len(pfz)} INCOIS PFZ feature(s)" if pfz else "; INCOIS PFZ not accessible"))
        status = AgentStatus.SUCCEEDED if chl is not None and not f3 else AgentStatus.PARTIAL
        return AgentOutcome(status=status, summary=summ, output=out, typed=out,
                            sources=["noaa_coastwatch"] + (["incois"] if not f3 else []) + (["gebco"] if out.zones else []),
                            tools=self.tools, failures=failures, confidence=None)
