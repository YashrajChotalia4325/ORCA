"""Agent 6 — Geospatial / Boundary agent.

Resolves places to sea points, derives the spatial sampling design for other
agents (trip transect, ring, regional stations, route end-points, analysis
boxes), and computes EEZ membership, distance to coast, depth (GEBCO),
distance to international maritime boundaries, protected / restricted /
seasonal zones and user geofences. Pure GIS — no LLM.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..core import spatial
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, BBox, GeoPoint, Place
from ..core.schemas.geo import GeoContext, ZoneHit
from .base import Agent, AgentOutcome, RunState


class SamplePoint(BaseModel):
    id: str
    label: str
    role: str                  # primary | transit | ring | station | endpoint
    point: GeoPoint
    distance_to_coast_km: Optional[float] = None


class GeoOutput(BaseModel):
    mode: str
    primary: Optional[GeoContext] = None
    origin_place: Optional[Place] = None
    offshore_km: Optional[float] = None
    offshore_bearing_deg: Optional[float] = None
    samples: list[SamplePoint] = Field(default_factory=list)
    route_endpoints: Optional[dict] = None
    bbox: Optional[BBox] = None
    zone_hits: list[ZoneHit] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GeospatialAgent(Agent):
    name = "geospatial"
    title = "Geospatial & Boundary Agent"
    responsibility = ("Place resolution, sea-point projection, sampling design, EEZ / maritime boundary / MPA / "
                      "restricted / seasonal-zone and geofence analysis, bathymetry")
    tools = ["gazetteer.resolve", "spatial.offshore_point", "spatial.snap_to_sea", "spatial.zone_hits",
             "spatial.distance_to_coast", "marine_regions.eez_lookup", "gebco.depth"]
    consumes = ["understanding"]
    output_model = GeoOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        ref = st.ctx.ref
        u = st.bb.understanding
        p = task.params
        mode = p.get("mode", "point")
        vessel = u.vessel_class.value if u else None
        when = u.time_window.start if (u and u.time_window) else st.now
        out = GeoOutput(mode=mode)
        failures = []
        tools = []

        def ctx_for(pt: GeoPoint, resolved_from: str) -> GeoContext:
            name, is_india = ref.eez_at(pt)
            zones = ref.zone_hits(pt, when, vessel)
            regs = [{"id": z.zone_id, "name": z.name, "active": z.active, "inside": z.inside, "note": z.note}
                    for z in zones if z.kind == "seasonal_restriction" and z.inside]
            return GeoContext(point=pt, resolved_from=resolved_from, distance_to_coast_km=round(ref.distance_to_coast_km(pt), 1),
                              in_sea=ref.is_sea(pt), eez=name, in_indian_eez=is_india,
                              zones=[z for z in zones if z.kind != "seasonal_restriction"],
                              nearest_port=ref.nearest_port(pt), regulations=regs)

        if mode in ("point", "ring"):
            place: Place = Place(**p["place"])
            out.origin_place = place
            base = place.point
            if place.kind == "coordinate":
                pt = ref.snap_to_sea(base)
                if pt != base:
                    out.notes.append("coordinate was on land; snapped to the nearest sea point")
                tools.append("spatial.snap_to_sea")
                primary_from = "coordinate"
            elif p.get("offshore_km"):
                pt, brg = ref.offshore_point(base, float(p["offshore_km"]))
                out.offshore_km, out.offshore_bearing_deg = float(p["offshore_km"]), brg
                tools.append("spatial.offshore_point")
                primary_from = f"{p['offshore_km']:g} km offshore of {place.name} (bearing {brg:.0f}° {spatial.compass(brg)})"
                st.tool(self.name, "spatial.offshore_point", f"{p['offshore_km']:g} km seaward of {place.name} → bearing {brg:.0f}°")
            else:
                pt = ref.snap_to_sea(base)
                primary_from = place.name
            out.samples.append(SamplePoint(id="P0", label="Assessment point", role="primary", point=pt))
            if mode == "point" and place.kind != "coordinate" and p.get("offshore_km"):
                harbour = ref.snap_to_sea(base, max_km=20)
                for k, f in enumerate((0.33, 0.66), 1):
                    lat = harbour.lat + (pt.lat - harbour.lat) * f
                    lon = harbour.lon + (pt.lon - harbour.lon) * f
                    tp = GeoPoint(lat=lat, lon=lon)
                    if ref.is_sea(tp):
                        out.samples.append(SamplePoint(id=f"T{k}", label=f"Transit {int(f * 100)}%", role="transit", point=tp))
            ring_km = p.get("ring_km") or (8.0 if mode == "point" else None)
            radius = p.get("radius_km")
            rings = [ring_km] if mode == "point" else [radius / 2, radius] if radius else [25, 50]
            for rk in rings:
                if not rk:
                    continue
                n = 4 if mode == "point" else 8
                for b in range(0, 360, 360 // n):
                    rp = spatial.destination(pt, b, rk)
                    if ref.is_sea(rp):
                        out.samples.append(SamplePoint(id=f"R{int(rk)}_{b}", label=f"{rk:g} km {spatial.compass(b)}",
                                                       role="ring", point=rp))
            out.primary = ctx_for(pt, primary_from)
            out.bbox = BBox.around(pt, 0.6)
        elif mode == "region":
            region: Place = Place(**p["region"])
            r = next(r for r in ref.regions if r["id"] == region.id)
            for aid in r["anchors"]:
                a = ref.place(aid)
                try:
                    sp, brg = ref.offshore_point(a.point, float(p.get("offshore_km") or 25))
                except ValueError:
                    continue
                out.samples.append(SamplePoint(id=f"S_{aid}", label=f"{a.name} ({p.get('offshore_km') or 25:g} km off)",
                                               role="station", point=sp))
            out.bbox = region.bbox
            if out.samples:
                out.primary = ctx_for(out.samples[len(out.samples) // 2].point, region.name)
            tools.append("spatial.offshore_point")
            st.tool(self.name, "spatial.offshore_point", f"{len(out.samples)} coastal stations derived for {region.name}")
        elif mode == "route":
            o, d = Place(**p["origin"]), Place(**p["destination"])
            op, dp = ref.snap_to_sea(o.point, max_km=30), ref.snap_to_sea(d.point, max_km=30)
            out.route_endpoints = {"origin": op.model_dump(), "destination": dp.model_dump(),
                                   "origin_name": o.name, "destination_name": d.name,
                                   "great_circle_km": round(spatial.distance_km(op, dp), 1)}
            out.samples += [SamplePoint(id="O", label=o.name, role="endpoint", point=op),
                            SamplePoint(id="D", label=d.name, role="endpoint", point=dp)]
            margin = max(0.8, 0.25 * max(abs(op.lat - dp.lat), abs(op.lon - dp.lon)))
            out.bbox = BBox(lon_min=min(op.lon, dp.lon) - margin, lat_min=min(op.lat, dp.lat) - margin,
                            lon_max=max(op.lon, dp.lon) + margin, lat_max=max(op.lat, dp.lat) + margin)
            out.primary = ctx_for(op, o.name)
            tools.append("spatial.snap_to_sea")
            st.tool(self.name, "spatial.snap_to_sea", f"route end-points snapped to navigable water; great-circle "
                                                       f"{out.route_endpoints['great_circle_km']} km")
        elif mode == "area":
            place: Place = Place(**p["place"])
            out.origin_place = place
            if place.kind == "region" and place.bbox:
                b = place.bbox
                cx, cy = (b.lon_min + b.lon_max) / 2, (b.lat_min + b.lat_max) / 2
                half = min(1.5, max(b.lon_max - b.lon_min, b.lat_max - b.lat_min) / 2)
                center = ref.snap_to_sea(GeoPoint(lat=cy, lon=cx), max_km=150)
                out.bbox = BBox.around(center, half)
            else:
                off = float(p.get("offshore_km") or 40)
                center, brg = ref.offshore_point(place.point, off)
                out.offshore_km, out.offshore_bearing_deg = off, brg
                out.bbox = BBox.around(center, float(p.get("half_deg") or 1.2))
            out.samples.append(SamplePoint(id="C", label="Analysis centre", role="primary", point=center))
            out.primary = ctx_for(center, f"analysis box around {place.name}")
            tools.append("spatial.offshore_point")

        # depth for primary + samples (GEBCO), one batched call
        pts = [s.point for s in out.samples][:100]
        if pts:
            depths, f = await st.ctx.registry.gebco.depths(pts)
            failures += f
            tools.append("gebco.depth")
            if out.primary and depths and depths[0] is not None:
                out.primary.depth_m = depths[0].value
            st.tool(self.name, "gebco.depth", f"bathymetry for {len(pts)} point(s)" + (" — unavailable" if f else ""))
        for s in out.samples:
            s.distance_to_coast_km = round(ref.distance_to_coast_km(s.point), 1)
        if out.primary:
            out.zone_hits = out.primary.zones
            tools += ["spatial.zone_hits", "marine_regions.eez_lookup", "spatial.distance_to_coast"]
            inside = [z for z in out.zone_hits if z.inside]
            st.tool(self.name, "spatial.zone_hits",
                    f"EEZ: {out.primary.eez or 'outside modelled EEZs'}; {len(out.zone_hits)} zone(s) within 150 km"
                    + (f"; INSIDE {', '.join(z.name for z in inside)}" if inside else ""))
        summary = self._summary(out)
        st.typed[self.name] = out
        return AgentOutcome(status=AgentStatus.SUCCEEDED if not failures else AgentStatus.PARTIAL, summary=summary,
                            output=out, typed=out, confidence=0.9, tools=sorted(set(tools)),
                            sources=["marine_regions", "natural_earth", "orca_curated"] + (["gebco"] if pts else []),
                            failures=failures, warnings=out.notes)

    @staticmethod
    def _summary(o: GeoOutput) -> str:
        parts = [f"{len(o.samples)} sample point(s)"]
        if o.primary:
            pc = o.primary
            parts.append(f"{pc.distance_to_coast_km} km from coast")
            if pc.depth_m is not None:
                parts.append(f"depth {pc.depth_m:.0f} m")
            b = next((z for z in pc.zones if z.kind == "maritime_boundary"), None)
            if b:
                parts.append(f"{b.distance_km:.1f} km to {b.name}")
        if o.route_endpoints:
            parts.append(f"route great-circle {o.route_endpoints['great_circle_km']} km")
        return "; ".join(parts)
