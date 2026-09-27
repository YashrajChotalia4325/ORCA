"""Agent 2 — Satellite / Earth-observation agent.

Satellite-derived SST (NOAA Geo-polar blended L4), SST anomaly (Coral Reef
Watch), chlorophyll-a (VIIRS, gap-filled) from NOAA CoastWatch ERDDAP, and
ISRO MOSDAC products when credentials are configured. Reports each product's
valid time, latency, spatial and temporal resolution explicitly, and never
treats a day-old analysis as a real-time observation.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from ..connectors.erddap import PRODUCTS
from ..core.schemas.blackboard import PlanTask
from ..core.schemas.common import AgentStatus, BBox
from ..core.schemas.provenance import PointValue, Provenance, TimeSeries
from ._sampling import SeriesDTO
from .base import Agent, AgentOutcome, RunState


class ProductInfo(BaseModel):
    variable: str
    source: str
    dataset: str
    product_time: Optional[datetime] = None
    latency_h: Optional[float] = None
    spatial_resolution: str = ""
    temporal_resolution: str = ""
    freshness: str = ""
    freshness_label: str = ""
    available: bool = False
    reason: str = ""


class SatelliteOutput(BaseModel):
    mode: str
    point_values: list[PointValue] = Field(default_factory=list)
    products: list[ProductInfo] = Field(default_factory=list)
    series: dict[str, SeriesDTO] = Field(default_factory=dict)
    series_provenance: dict[str, Provenance] = Field(default_factory=dict)
    unavailable: list[str] = Field(default_factory=list)


class SatelliteAgent(Agent):
    name = "satellite"
    title = "Satellite / Earth Observation Agent"
    responsibility = "Satellite SST, SST anomaly and chlorophyll-a with explicit product time, latency and resolution"
    tools = ["noaa_coastwatch.point", "noaa_coastwatch.grid", "noaa_coastwatch.region_series", "mosdac.satellite_value"]
    consumes = ["geospatial"]
    output_model = SatelliteOutput

    async def run(self, task: PlanTask, st: RunState) -> AgentOutcome:
        reg = st.ctx.registry
        geo = st.typed.get("geospatial")
        mode = task.params.get("mode", "point")
        out = SatelliteOutput(mode=mode)
        failures = []
        st.stage("RETRIEVAL", "Retrieving satellite Earth-observation products")
        now = st.now
        if mode == "series":
            u = st.bb.understanding
            start = (u.comparison_window.start if u.comparison_window else u.time_window.start)
            end = min(u.time_window.end, now)
            bbox: BBox = geo.bbox
            span = max(bbox.lon_max - bbox.lon_min, bbox.lat_max - bbox.lat_min)

            async def ser(key: str):
                stride = max(1, int(round(span / (PRODUCTS[key]["res_deg"] * 8))))
                ndays = int((end - start).total_seconds() // 86400) + 2
                st.tool(self.name, "noaa_coastwatch.region_series",
                        f"{key}: daily area-mean, latest {ndays + 1} product days (stride {stride})", source_id="noaa_coastwatch")
                return key, *(await reg.erddap.region_series(key, bbox, ndays, stride))

            for key, ts, f in await asyncio.gather(*(ser(k) for k in ("sst", "sst_anomaly", "chlorophyll"))):
                failures += f
                if ts is None:
                    out.unavailable.append(key)
                    continue
                out.series[key] = SeriesDTO(times=ts.times, values=ts.values)
                out.series_provenance[key] = ts.provenance
                st.typed.setdefault(self.name + ":series", {})[key] = ts
            summ = f"{len(out.series)} satellite time series ({', '.join(out.series)})"
        else:
            pt = geo.samples[0].point

            async def pv(key: str):
                st.tool(self.name, "noaa_coastwatch.point", f"{key} at assessment point", source_id="noaa_coastwatch")
                return key, *(await reg.erddap.point(key, pt, half_deg=0.15))

            results = await asyncio.gather(*(pv(k) for k in ("sst", "sst_anomaly", "chlorophyll")))
            for key, val, f in results:
                failures += f
                p = PRODUCTS[key]
                info = ProductInfo(variable=key, source="NOAA CoastWatch", dataset=p["dataset"],
                                   spatial_resolution=p["spatial"], temporal_resolution="daily")
                if val is None:
                    info.reason = f[0].reason if f else "no data"
                    out.unavailable.append(key)
                else:
                    out.point_values.append(val)
                    info.available = True
                    info.product_time = val.valid_time
                    info.latency_h = round((now - val.valid_time).total_seconds() / 3600, 1) if val.valid_time else None
                    info.freshness = val.provenance.freshness.status.value
                    info.freshness_label = val.provenance.freshness.label
                out.products.append(info)
            # ISRO MOSDAC (adapter; excluded unless configured / demo)
            _, mf = await reg.mosdac.satellite_value("sst", BBox.around(pt, 0.2))
            if mf:
                failures += mf
                out.products.append(ProductInfo(variable="sst", source="MOSDAC (ISRO)", dataset="insat3d_sst",
                                                available=False, reason=mf[0].reason))
            st.tool(self.name, "mosdac.satellite_value",
                    "MOSDAC INSAT-3D SST: " + ("excluded — " + mf[0].status if mf else "received"), source_id="mosdac")
            st.typed[self.name] = out
            vals = {v.variable: v for v in out.point_values}
            parts = []
            if "sst" in vals:
                parts.append(f"SST {vals['sst'].value:.2f} °C ({vals['sst'].valid_time:%d %b})")
            if "chlorophyll" in vals:
                parts.append(f"chl-a {vals['chlorophyll'].value:.2f} mg/m³")
            if "sst_anomaly" in vals:
                parts.append(f"SST anomaly {vals['sst_anomaly'].value:+.2f} °C")
            summ = "; ".join(parts) or "no satellite values available"
        ok = bool(out.point_values or out.series)
        status = AgentStatus.SUCCEEDED if ok and not out.unavailable else AgentStatus.PARTIAL if ok else AgentStatus.FAILED
        return AgentOutcome(status=status, summary=summ, output=out, typed=out, sources=["noaa_coastwatch"],
                            tools=["noaa_coastwatch." + ("region_series" if mode == "series" else "point"), "mosdac.satellite_value"],
                            failures=failures)
