"""Gridded forecast fields for map layers (waves, wind, currents).

Only sea points of a regular grid over the Indian seas are requested (land
points are skipped to respect upstream rate limits). Results are cached per
mode/scenario for 3 hours. Values come verbatim from the named model; the
map legend shows the model, run time and retrieval time.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import numpy as np

from ..core.schemas.common import BBox, DataMode, GeoPoint
from ..runtime import ExecContext

FIELD_BBOX = BBox(lon_min=64.0, lat_min=4.0, lon_max=95.0, lat_max=24.0)
LAYERS = {
    "waves": {"model": "om_mfwam", "vars": ["wave_height", "wave_direction"], "units": "m", "label": "Significant wave height"},
    "wind": {"model": "om_gfs", "vars": ["wind_speed", "wind_direction"], "units": "km/h", "label": "10 m wind"},
    "currents": {"model": "om_smoc", "vars": ["current_speed", "current_direction"], "units": "km/h", "label": "Surface current"},
}
_cache: dict[str, tuple[float, dict]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def field(ctx: ExecContext, layer: str, res: float = 1.5, bbox: Optional[BBox] = None) -> dict[str, Any]:
    spec = LAYERS[layer]
    bbox = bbox or FIELD_BBOX
    key = f"{ctx.mode.value}:{ctx.scenario_id}:{ctx.replay_snapshot}:{layer}:{res}:{bbox.as_list()}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < 3 * 3600:
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < 3 * 3600:
            return hit[1]
        lats = np.round(np.arange(bbox.lat_min, bbox.lat_max + 1e-9, res), 3)
        lons = np.round(np.arange(bbox.lon_min, bbox.lon_max + 1e-9, res), 3)
        LO, LA = np.meshgrid(lons, lats)
        sea = ctx.ref.sea_mask(LO.ravel(), LA.ravel())
        pts = [GeoPoint(lat=float(la), lon=float(lo)) for la, lo, s in zip(LA.ravel(), LO.ravel(), sea) if s]
        model = ctx.registry.models[spec["model"]]
        per_pt, failures = await model.points(pts, past_days=0, forecast_days=2, variables=spec["vars"])
        times = next((ts.times for d in per_pt for ts in d.values() if ts.times), [])
        prov = next((ts.provenance for d in per_pt for ts in d.values()), None)
        features = []
        for p, d in zip(pts, per_pt):
            sp, dr = d.get(spec["vars"][0]), d.get(spec["vars"][1])
            if sp is None:
                continue
            features.append({"lat": p.lat, "lon": p.lon, "v": [None if v is None else round(v, 2) for v in sp.values],
                             "d": [None if v is None else round(v) for v in (dr.values if dr else [])]})
        out = {"layer": layer, "label": spec["label"], "units": spec["units"], "source": model.spec.name,
               "source_id": spec["model"], "resolution_deg": res, "times": [t.isoformat() for t in times],
               "points": features, "mode": ctx.mode.value,
               "provenance": prov.model_dump(mode="json") if prov else None,
               "failures": [f.model_dump(mode="json") for f in failures]}
        if features:
            _cache[key] = (time.monotonic(), out)
        return out
