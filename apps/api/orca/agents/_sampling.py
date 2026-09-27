"""Shared multi-model retrieval used by the Oceanography and Weather agents."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
from pydantic import BaseModel, Field

from ..connectors.openmeteo import OpenMeteoModel
from ..core import spatial
from ..core.schemas.common import BBox, GeoPoint
from ..core.schemas.provenance import Provenance, SourceFailure, TimeSeries
from .base import RunState


class SeriesDTO(BaseModel):
    times: list[datetime]
    values: list[Optional[float]]


class ModelSummary(BaseModel):
    source: str
    source_id: str
    lineage: str
    variable: str
    units: str
    worst: Optional[float] = None
    worst_time: Optional[datetime] = None
    worst_sample: Optional[str] = None
    at_primary_start: Optional[float] = None
    freshness_status: str = ""
    freshness_label: str = ""
    issued_at: Optional[datetime] = None
    grid_distance_km: Optional[float] = None
    provenance: Optional[Provenance] = None


class RetrievalOutput(BaseModel):
    mode: str
    models_used: list[str] = Field(default_factory=list)
    models_failed: list[str] = Field(default_factory=list)
    primary_series: dict[str, dict[str, SeriesDTO]] = Field(default_factory=dict)   # var -> source_id -> series
    summaries: list[ModelSummary] = Field(default_factory=list)
    field_grid: Optional[dict] = None
    notes: list[str] = Field(default_factory=list)


@dataclass
class PointData:
    """model source_id -> list over sample points of {var: TimeSeries}."""
    by_model: dict[str, list[dict[str, TimeSeries]]] = field(default_factory=dict)
    sample_ids: list[str] = field(default_factory=list)
    sample_points: list[GeoPoint] = field(default_factory=list)
    models: dict[str, OpenMeteoModel] = field(default_factory=dict)


@dataclass
class FieldData:
    lats: np.ndarray
    lons: np.ndarray
    times: list[datetime]
    by_model: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)   # sid -> var -> [t,i,j]
    provenance: dict[str, dict[str, Provenance]] = field(default_factory=dict)
    models: dict[str, OpenMeteoModel] = field(default_factory=dict)


async def fetch_points(models: list[OpenMeteoModel], sample_ids: list[str], pts: list[GeoPoint], st: RunState,
                       agent: str, variables: list[str] | None, past_days: int = 1, forecast_days: int = 3
                       ) -> tuple[PointData, list[SourceFailure]]:
    data = PointData(sample_ids=sample_ids, sample_points=pts)
    failures: list[SourceFailure] = []

    async def one(m: OpenMeteoModel):
        st.tool(agent, f"{m.descriptor.id}.points", f"requesting {m.spec.name} for {len(pts)} point(s)",
                source_id=m.descriptor.id)
        res, f = await m.points(pts, past_days=past_days, forecast_days=forecast_days, variables=variables)
        return m, res, f

    for m, res, f in await asyncio.gather(*(one(m) for m in models)):
        failures += f
        has = any(any(any(v is not None for v in ts.values) for ts in d.values()) for d in res)
        if has:
            data.by_model[m.descriptor.id] = res
            data.models[m.descriptor.id] = m
            prov = next((ts.provenance for d in res for ts in d.values()), None)
            st.tool(agent, f"{m.descriptor.id}.points",
                    f"{m.spec.name}: received ({prov.freshness.label if prov else ''})", source_id=m.descriptor.id,
                    ok=True, freshness=prov.freshness.status.value if prov else None)
        else:
            reason = f[0].reason if f else "no values at requested points"
            st.tool(agent, f"{m.descriptor.id}.points", f"{m.spec.name}: UNAVAILABLE — {reason}",
                    source_id=m.descriptor.id, ok=False)
            if not f:
                failures.append(m.failure(Exception(reason)))
    return data, failures


def summarize_points(data: PointData, window: tuple[datetime, datetime], variables: list[str],
                     worst_is_max: dict[str, bool] | None = None) -> RetrievalOutput:
    out = RetrievalOutput(mode="point", models_used=list(data.by_model))
    start, end = window
    worst_is_max = worst_is_max or {}
    for sid, per_pt in data.by_model.items():
        m = data.models[sid]
        for var in variables:
            best = None
            prov = None
            gdist = None
            first = None
            for sidx, (sample_id, d) in enumerate(zip(data.sample_ids, per_pt)):
                ts = d.get(var)
                if ts is None:
                    continue
                prov = prov or ts.provenance
                if sidx == 0:
                    if ts.grid_location:
                        gdist = round(spatial.distance_km(ts.location, ts.grid_location), 1)
                    first = ts.at(start)
                    # chart series for the primary point: window ± 12 h
                    lo, hi = start.timestamp() - 12 * 3600, end.timestamp() + 12 * 3600
                    sel = [(t, v) for t, v in zip(ts.times, ts.values) if lo <= t.timestamp() <= hi]
                    out.primary_series.setdefault(var, {})[sid] = SeriesDTO(times=[t for t, _ in sel],
                                                                             values=[v for _, v in sel])
                for t, v in ts.window(start, end):
                    big = worst_is_max.get(var, True)
                    if best is None or (v > best[0] if big else v < best[0]):
                        best = (v, t, sample_id)
            if prov is None:
                continue
            out.summaries.append(ModelSummary(
                source=m.spec.name, source_id=sid, lineage=m.lineage, variable=var, units=prov.units,
                worst=None if best is None else round(best[0], 2), worst_time=None if best is None else best[1],
                worst_sample=None if best is None else best[2], at_primary_start=None if first is None else round(first, 2),
                freshness_status=prov.freshness.status.value, freshness_label=prov.freshness.label,
                issued_at=prov.issued_at, grid_distance_km=gdist, provenance=prov))
    return out


def grid_points(bbox: BBox, res: float) -> tuple[np.ndarray, np.ndarray, list[GeoPoint]]:
    lats = np.round(np.arange(bbox.lat_min, bbox.lat_max + 1e-9, res), 3)
    lons = np.round(np.arange(bbox.lon_min, bbox.lon_max + 1e-9, res), 3)
    pts = [GeoPoint(lat=float(la), lon=float(lo)) for la in lats for lo in lons]
    return lats, lons, pts


async def fetch_field(models: list[OpenMeteoModel], bbox: BBox, res: float, st: RunState, agent: str,
                      variables: list[str], forecast_days: int = 3) -> tuple[Optional[FieldData], list[SourceFailure]]:
    lats, lons, pts = grid_points(bbox, res)
    failures: list[SourceFailure] = []
    fd: Optional[FieldData] = None

    async def one(m: OpenMeteoModel):
        st.tool(agent, f"{m.descriptor.id}.points", f"{m.spec.name}: gridded field {len(lats)}×{len(lons)} @ {res}°",
                source_id=m.descriptor.id)
        r, f = await m.points(pts, past_days=0, forecast_days=forecast_days, variables=variables)
        return m, r, f

    for m, per_pt, f in await asyncio.gather(*(one(m) for m in models)):
        failures += f
        times = next((ts.times for d in per_pt for ts in d.values() if ts.times), None)
        if not times:
            st.tool(agent, f"{m.descriptor.id}.points", f"{m.spec.name}: field UNAVAILABLE", source_id=m.descriptor.id, ok=False)
            continue
        if fd is None:
            fd = FieldData(lats=lats, lons=lons, times=times)
        arrs: dict[str, np.ndarray] = {}
        for var in variables:
            a = np.full((len(fd.times), len(lats), len(lons)), np.nan)
            any_val = False
            for k, d in enumerate(per_pt):
                ts = d.get(var)
                if ts is None:
                    continue
                i, j = divmod(k, len(lons))
                vals = {t: v for t, v in zip(ts.times, ts.values)}
                for ti, t in enumerate(fd.times):
                    v = vals.get(t)
                    if v is not None:
                        a[ti, i, j] = v
                        any_val = True
                if var not in fd.provenance.get(m.descriptor.id, {}):
                    fd.provenance.setdefault(m.descriptor.id, {})[var] = ts.provenance
            if any_val:
                arrs[var] = a
        if arrs:
            fd.by_model[m.descriptor.id] = arrs
            fd.models[m.descriptor.id] = m
            st.tool(agent, f"{m.descriptor.id}.points", f"{m.spec.name}: field received ({', '.join(arrs)})",
                    source_id=m.descriptor.id, ok=True)
    return fd, failures


def field_summary(fd: Optional[FieldData]) -> Optional[dict[str, Any]]:
    if fd is None:
        return None
    return {"lats": [float(x) for x in fd.lats], "lons": [float(x) for x in fd.lons],
            "times": [t.isoformat() for t in fd.times[:1]] + ([fd.times[-1].isoformat()] if fd.times else []),
            "n_times": len(fd.times), "models": {sid: list(v) for sid, v in fd.by_model.items()}}
