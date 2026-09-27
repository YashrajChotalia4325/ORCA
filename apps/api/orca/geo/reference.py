"""Reference geodata store: coastline, EEZ, maritime boundaries, protected /
restricted areas, seasonal regulations, ports, gazetteer and user geofences.

Everything here is REFERENCE data with explicit provenance; it is loaded once
and queried with deterministic geometry (shapely / pyproj).
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import shapely
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union

from ..config import get_settings
from ..core import spatial
from ..core.schemas.common import BBox, GeoPoint, Place
from ..core.schemas.geo import ZoneHit
from ..core.units import km_to_nm


@dataclass
class Zone:
    id: str
    name: str
    kind: str                         # mpa | restricted | seasonal_restriction | geofence
    geom: Any
    authority: str = ""
    source: str = ""
    approximate: bool = False
    props: dict[str, Any] = field(default_factory=dict)

    def active_at(self, when: datetime, vessel_class: str | None = None) -> bool:
        if self.kind != "seasonal_restriction":
            return True
        applies = self.props.get("applies_to")
        if vessel_class and applies and vessel_class not in applies:
            return False
        md = when.strftime("%m-%d")
        s, e = self.props["start_mmdd"], self.props["end_mmdd"]
        return (s <= md <= e) if s <= e else (md >= s or md <= e)


class ReferenceStore:
    _instance: Optional["ReferenceStore"] = None
    _lock = threading.Lock()

    def __init__(self, ref_dir: Path):
        self.ref_dir = ref_dir
        self.manifest = json.loads((ref_dir / "manifest.json").read_text(encoding="utf-8"))
        land_fc = json.loads((ref_dir / "land.geojson").read_text(encoding="utf-8"))
        self.land = unary_union([shape(f["geometry"]) for f in land_fc["features"]])
        shapely.prepare(self.land)
        self.coast = self.land.boundary

        eez_fc = json.loads((ref_dir / "eez.geojson").read_text(encoding="utf-8"))
        self.eez: list[tuple[dict, Any]] = []
        for f in eez_fc["features"]:
            g = shape(f["geometry"])
            shapely.prepare(g)
            self.eez.append((f["properties"], g))
        self.india_eez = unary_union([g for p, g in self.eez if p.get("sovereign") == "India"])
        shapely.prepare(self.india_eez)

        b_fc = json.loads((ref_dir / "maritime_boundaries.geojson").read_text(encoding="utf-8"))
        # International boundaries have two parties; "200 NM" lines are the EEZ outer limit;
        # straight baselines are coastal reference lines and are not used for proximity alerts.
        self.boundaries: list[tuple[dict, Any]] = []
        self.eez_limits: list[tuple[dict, Any]] = []
        for f in b_fc["features"]:
            p, g = f["properties"], shape(f["geometry"])
            if p.get("territory2") and p.get("line_type") in ("Treaty", "Median line", "Court ruling", "Connection line"):
                self.boundaries.append((p, g))
            elif p.get("line_type") == "200 NM":
                self.eez_limits.append((p, g))
        self.boundary_union = unary_union([g for _, g in self.boundaries])

        cur = json.loads((ref_dir / "curated" / "zones.json").read_text(encoding="utf-8"))
        self.zones_meta = cur["_meta"]
        self.zones: list[Zone] = []
        for z in cur["protected_areas"]:
            g = Polygon(z["ring"]).difference(self.land)
            self.zones.append(Zone(z["id"], z["name"], "mpa", g, z.get("authority", ""),
                                   "ORCA-curated (approximate)", True, z))
        for z in cur["restricted_areas"]:
            g = Polygon(z["ring"]).difference(self.land)
            self.zones.append(Zone(z["id"], z["name"], "restricted", g, z.get("authority", ""),
                                   "ORCA-curated (approximate)", True, z))
        for z in cur["seasonal_regulations"]:
            a = z["area"]
            if a["type"] == "ring":
                g = Polygon(a["ring"]).difference(self.land)
            else:
                g = self.india_eez.intersection(box(a["lon_min"], -10, a["lon_max"], 30))
            self.zones.append(Zone(z["id"], z["name"], "seasonal_restriction", g, z.get("authority", ""),
                                   "ORCA-curated (approximate)", True, z))
        for zn in self.zones:
            shapely.prepare(zn.geom)
        self.geofences: dict[str, Zone] = {}

        gz = json.loads((ref_dir / "curated" / "gazetteer.json").read_text(encoding="utf-8"))
        self.gazetteer_meta = gz["_meta"]
        self.places: list[dict] = gz["places"]
        self.regions: list[dict] = gz["regions"]
        self.place_by_id = {p["id"]: p for p in self.places}

    # ------------------------------------------------------------------ singleton
    @classmethod
    def get(cls) -> "ReferenceStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = ReferenceStore(get_settings().data_dir / "reference")
        return cls._instance

    # ------------------------------------------------------------------ basic tests
    def is_sea(self, p: GeoPoint) -> bool:
        return not bool(shapely.contains_xy(self.land, p.lon, p.lat))

    def sea_mask(self, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        return ~shapely.contains_xy(self.land, lons, lats)

    def distance_to_coast_km(self, p: GeoPoint) -> float:
        d, _, _ = spatial.distance_to_geometry_km(p, self.coast, window_deg=2.0)
        return d

    def eez_at(self, p: GeoPoint) -> tuple[Optional[str], Optional[bool]]:
        for props, g in self.eez:
            if shapely.contains_xy(g, p.lon, p.lat):
                return props.get("name"), props.get("sovereign") == "India"
        return None, None

    # ------------------------------------------------------------------ places
    def place(self, pid: str) -> Place:
        p = self.place_by_id[pid]
        return Place(id=p["id"], name=p["name"], kind=p["kind"], state=p.get("state"),
                     point=GeoPoint(lat=p["lat"], lon=p["lon"]), names=p.get("names", {}))

    def region_place(self, rid: str) -> Place:
        r = next(r for r in self.regions if r["id"] == rid)
        b = r["bbox"]
        bb = BBox(lon_min=b[0], lat_min=b[1], lon_max=b[2], lat_max=b[3])
        return Place(id=r["id"], name=r["name"], kind="region", bbox=bb, names=r.get("names", {}),
                     point=GeoPoint(lat=(b[1] + b[3]) / 2, lon=(b[0] + b[2]) / 2))

    def ports(self) -> list[dict]:
        return [p for p in self.places if p["kind"] in ("port", "fishing_harbour")]

    def nearest_port(self, p: GeoPoint) -> dict:
        best = min(self.ports(), key=lambda q: spatial.distance_km(p, GeoPoint(lat=q["lat"], lon=q["lon"])))
        q = GeoPoint(lat=best["lat"], lon=best["lon"])
        d = spatial.distance_km(p, q)
        return {"id": best["id"], "name": best["name"], "distance_km": round(d, 1),
                "distance_nm": round(km_to_nm(d), 1), "bearing_deg": round(spatial.bearing_deg(p, q), 0)}

    # ------------------------------------------------------------------ derived points
    def offshore_point(self, p: GeoPoint, km: float) -> tuple[GeoPoint, float]:
        """Point `km` offshore from p, choosing the seaward bearing deterministically.

        Tests 72 bearings; keeps candidates in the sea whose connecting line
        does not cross more than the first 3 km of land, and picks the one
        farthest from the coast.
        """
        best: tuple[float, GeoPoint, float] | None = None
        for b in range(0, 360, 5):
            c = spatial.destination(p, b, km)
            if not self.is_sea(c):
                continue
            mid = spatial.destination(p, b, km * 0.5)
            if not self.is_sea(mid):
                continue
            dc = self.distance_to_coast_km(c)
            if best is None or dc > best[0] + 1e-6:
                best = (dc, c, float(b))
        if best is None:
            raise ValueError("no seaward direction found for offshore projection")
        return best[1], best[2]

    def snap_to_sea(self, p: GeoPoint, max_km: float = 40.0) -> GeoPoint:
        if self.is_sea(p):
            return p
        r = 1.0
        while r <= max_km:
            cands = [spatial.destination(p, b, r) for b in range(0, 360, 15)]
            sea = [c for c in cands if self.is_sea(c)]
            if sea:
                return max(sea, key=self.distance_to_coast_km)
            r *= 1.5
        return p

    # ------------------------------------------------------------------ zones
    def all_zones(self) -> list[Zone]:
        return self.zones + list(self.geofences.values())

    def add_geofence(self, gid: str, name: str, ring: list[list[float]], props: dict | None = None) -> Zone:
        g = Polygon(ring)
        if not g.is_valid:
            g = g.buffer(0)
        shapely.prepare(g)
        z = Zone(gid, name, "geofence", g, "user", "user-defined", False, props or {})
        self.geofences[gid] = z
        return z

    def remove_geofence(self, gid: str) -> None:
        self.geofences.pop(gid, None)

    def zone_hits(self, p: GeoPoint, when: datetime, vessel_class: str | None = None,
                  radius_km: float = 150.0) -> list[ZoneHit]:
        hits: list[ZoneHit] = []
        for z in self.all_zones():
            if z.geom.is_empty:
                continue
            d, near, inside = spatial.distance_to_geometry_km(p, z.geom, window_deg=2.0)
            if d > radius_km:
                continue
            hits.append(ZoneHit(
                zone_id=z.id, name=z.name, kind=z.kind, inside=inside, distance_km=round(d, 2),
                distance_nm=round(km_to_nm(d), 2), nearest_point=near,
                bearing_deg=None if inside or near is None else round(spatial.bearing_deg(p, near), 0),
                active=z.active_at(when, vessel_class), authority=z.authority, source=z.source,
                approximate=z.approximate, note=z.props.get("note") or z.props.get("rule", "")))
        # nearest international maritime boundary
        best = None
        for props, g in self.boundaries:
            d, near, _ = spatial.distance_to_geometry_km(p, g, window_deg=2.0)
            if best is None or d < best[0]:
                best = (d, near, props)
        if best and best[0] <= radius_km * 2:
            d, near, props = best
            hits.append(ZoneHit(
                zone_id=f"boundary_{props.get('line_id')}", name=props.get("name") or "International maritime boundary",
                kind="maritime_boundary", inside=False, distance_km=round(d, 2), distance_nm=round(km_to_nm(d), 2),
                nearest_point=near, bearing_deg=None if near is None else round(spatial.bearing_deg(p, near), 0),
                authority=f"{props.get('line_type', '')} — {props.get('source') or ''}"[:200],
                source="Marine Regions (VLIZ) eez_boundaries, CC-BY 4.0", approximate=False,
                note="Compiled boundary; not an official legal delimitation."))
        for props, g in self.eez_limits:
            d, near, _ = spatial.distance_to_geometry_km(p, g, window_deg=2.0)
            if d <= radius_km:
                hits.append(ZoneHit(
                    zone_id=f"eez_limit_{props.get('line_id')}", name=f"EEZ outer limit (200 NM) — {props.get('territory1')}",
                    kind="eez_limit", inside=False, distance_km=round(d, 2), distance_nm=round(km_to_nm(d), 2),
                    nearest_point=near, bearing_deg=None if near is None else round(spatial.bearing_deg(p, near), 0),
                    source="Marine Regions (VLIZ) eez_boundaries, CC-BY 4.0"))
        hits.sort(key=lambda h: (not h.inside, h.distance_km))
        return hits

    # ------------------------------------------------------------------ GeoJSON export
    def geojson_layers(self) -> dict[str, dict]:
        def fc(features):
            return {"type": "FeatureCollection", "features": features}

        def feat(geom, props):
            return {"type": "Feature", "properties": props, "geometry": mapping(geom)}

        eez = [feat(g.simplify(0.02), {"name": p.get("name"), "sovereign": p.get("sovereign"),
                                         "is_india": p.get("sovereign") == "India"}) for p, g in self.eez]
        bnd = [feat(g, {"name": p.get("name"), "line_type": p.get("line_type"), "source": p.get("source"),
                        "doc_url": p.get("doc_url"), "kind": "international"}) for p, g in self.boundaries]
        bnd += [feat(g, {"name": f"EEZ outer limit — {p.get('territory1')}", "line_type": "200 NM",
                         "kind": "eez_limit"}) for p, g in self.eez_limits]
        zones = [feat(z.geom, {"id": z.id, "name": z.name, "kind": z.kind, "authority": z.authority,
                               "approximate": z.approximate,
                               "season": f"{z.props.get('start_mmdd')}..{z.props.get('end_mmdd')}" if z.kind == "seasonal_restriction" else None,
                               "note": z.props.get("note") or z.props.get("rule")})
                 for z in self.all_zones() if not z.geom.is_empty]
        ports = [{"type": "Feature", "properties": {"id": p["id"], "name": p["name"], "kind": p["kind"], "state": p.get("state")},
                  "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]}} for p in self.ports()]
        land = [feat(self.land.simplify(0.01), {"layer": "land", "source": "Natural Earth 1:10m (public domain)"})]
        return {"land": fc(land), "eez": fc(eez), "maritime_boundaries": fc(bnd), "zones": fc(zones), "ports": fc(ports)}

    def provenance(self) -> dict:
        return {"reference_manifest": self.manifest, "curated_zones": self.zones_meta,
                "gazetteer": self.gazetteer_meta}
