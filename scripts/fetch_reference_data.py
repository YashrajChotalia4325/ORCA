"""Download and pre-process ORCA's static reference geodata.

Reference layers are *not* live data: they change on the scale of years
(coastlines, treaty boundaries). They are fetched once from their official /
authoritative publishers, clipped to the ORCA area of interest, simplified,
and written to data/reference/ together with a provenance manifest.

Sources
-------
* Natural Earth 1:10m land + minor islands (public domain)
  https://www.naturalearthdata.com/
* Marine Regions (VLIZ) EEZ v12 polygons and maritime boundary lines, CC-BY 4.0
  https://www.marineregions.org/  (WFS: geo.vliz.be/geoserver/MarineRegions)

Run:  .venv/Scripts/python scripts/fetch_reference_data.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference"
AOI = box(60.0, -5.0, 100.0, 30.0)  # lon_min, lat_min, lon_max, lat_max (WGS84)

NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
WFS = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
UA = {"User-Agent": "ORCA-prototype/0.1 (SIH26176 research prototype)"}

EEZ_TERRITORIES = [
    "India", "Sri Lanka", "Maldives", "Pakistan", "Bangladesh", "Myanmar",
    "Andaman and Nicobar", "Indonesia", "Oman", "Thailand",
]


def fetch_json(url: str) -> dict:
    with httpx.Client(timeout=180, headers=UA, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def natural_earth_land() -> dict:
    geoms = []
    for name in ("ne_10m_land.geojson", "ne_10m_minor_islands.geojson"):
        print(f"  fetching {name}")
        fc = fetch_json(NE_BASE + name)
        for f in fc["features"]:
            g = shape(f["geometry"])
            if g.intersects(AOI):
                geoms.append(g.intersection(AOI))
    land = unary_union(geoms).simplify(0.004, preserve_topology=True)
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"layer": "land"}, "geometry": mapping(land)}],
    }


def wfs(type_name: str, cql: str, props: str | None = None) -> dict:
    q = {
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "typeName": type_name, "outputFormat": "application/json", "cql_filter": cql,
    }
    if props:
        q["propertyName"] = props
    return fetch_json(f"{WFS}?{urlencode(q)}")


def marine_regions_eez() -> dict:
    cql = " OR ".join(f"territory1='{t}'" for t in EEZ_TERRITORIES)
    print("  fetching MarineRegions:eez")
    fc = wfs("MarineRegions:eez", cql)
    feats = []
    for f in fc["features"]:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if not g.intersects(AOI):
            continue
        g = g.intersection(AOI).simplify(0.01, preserve_topology=True)
        p = f["properties"]
        feats.append({
            "type": "Feature",
            "properties": {
                "mrgid": p.get("mrgid"), "name": p.get("geoname"), "territory": p.get("territory1"),
                "sovereign": p.get("sovereign1"), "pol_type": p.get("pol_type"),
                "is_india": p.get("sovereign1") == "India",
            },
            "geometry": mapping(g),
        })
    return {"type": "FeatureCollection", "features": feats}


def marine_regions_boundaries() -> dict:
    print("  fetching MarineRegions:eez_boundaries")
    fc = wfs("MarineRegions:eez_boundaries", "sovereign1='India' OR sovereign2='India'")
    feats = []
    for f in fc["features"]:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if not g.intersects(AOI):
            continue
        p = f["properties"]
        feats.append({
            "type": "Feature",
            "properties": {
                "line_id": p.get("line_id"), "name": p.get("line_name"), "line_type": p.get("line_type"),
                "territory1": p.get("territory1"), "territory2": p.get("territory2"),
                "source": p.get("source1"), "doc_url": p.get("url1"), "length_km": p.get("length_km"),
                "international": True,
            },
            "geometry": mapping(g.intersection(AOI).simplify(0.002, preserve_topology=True)),
        })
    return {"type": "FeatureCollection", "features": feats}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    manifest = {"generated_at": now, "aoi_bbox": list(AOI.bounds), "layers": {}}
    jobs = [
        ("land.geojson", natural_earth_land, {
            "source": "Natural Earth", "dataset": "ne_10m_land + ne_10m_minor_islands",
            "license": "Public domain", "url": "https://www.naturalearthdata.com/",
            "processing": "clipped to AOI, unioned, simplified 0.004 deg",
        }),
        ("eez.geojson", marine_regions_eez, {
            "source": "Marine Regions (Flanders Marine Institute, VLIZ)", "dataset": "MarineRegions:eez (EEZ v12)",
            "license": "CC-BY 4.0", "url": "https://www.marineregions.org/",
            "processing": "clipped to AOI, simplified 0.01 deg",
            "note": "Compiled dataset; not an official legal delimitation.",
        }),
        ("maritime_boundaries.geojson", marine_regions_boundaries, {
            "source": "Marine Regions (Flanders Marine Institute, VLIZ)", "dataset": "MarineRegions:eez_boundaries",
            "license": "CC-BY 4.0", "url": "https://www.marineregions.org/",
            "processing": "India-related lines, clipped to AOI, simplified 0.002 deg",
            "note": "Compiled dataset; not an official legal delimitation.",
        }),
    ]
    for fname, fn, meta in jobs:
        print(f"[{fname}]")
        data = fn()
        (OUT / fname).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        meta.update({"retrieved_at": now, "features": len(data["features"]),
                     "bytes": (OUT / fname).stat().st_size})
        manifest["layers"][fname] = meta
        print(f"  -> {len(data['features'])} features, {meta['bytes']/1024:.0f} KiB")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
