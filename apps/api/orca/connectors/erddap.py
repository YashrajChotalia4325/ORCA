"""NOAA CoastWatch ERDDAP connector: satellite SST, SST anomaly and chlorophyll-a.

Public griddap service, no key. Products used:

* noaacwBLENDEDsstDNDaily      NOAA Geo-polar Blended SST (day+night), 0.05°, daily, NRT (GHRSST L4)
* noaacrwsstanomalyDaily       NOAA Coral Reef Watch SST anomaly, 0.05°, daily
* noaacwNPPN20VIIRSDINEOFDaily VIIRS (S-NPP + NOAA-20) chlorophyll-a, DINEOF gap-filled, 9 km, daily, NRT
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from ..core.clock import parse_utc
from ..core.schemas.common import AuthorityTier, BBox, DataKind, GeoPoint
from ..core.schemas.provenance import GridField, PointValue, SourceFailure, TimeSeries
from .base import Connector, DatasetDescriptor, SourceDescriptor
from .transport import TransportError

BASE = "https://coastwatch.noaa.gov/erddap/griddap"

PRODUCTS = {
    "sst": dict(dataset="noaacwBLENDEDsstDNDaily", var="analysed_sst", units="°C", res_deg=0.05, alt=False,
                title="NOAA Geo-polar Blended SST (day+night), GHRSST L4", spatial="0.05° (~5 km)"),
    "sst_anomaly": dict(dataset="noaacrwsstanomalyDaily", var="sea_surface_temperature_anomaly", units="°C", res_deg=0.05,
                        alt=False, title="NOAA Coral Reef Watch daily SST anomaly", spatial="0.05° (~5 km)"),
    "chlorophyll": dict(dataset="noaacwNPPN20VIIRSDINEOFDaily", var="chlor_a", units="mg/m³", res_deg=1 / 12, alt=True,
                        title="VIIRS S-NPP/NOAA-20 chlorophyll-a, DINEOF gap-filled (NRT)", spatial="0.083° (~9 km)"),
}


class NoaaCoastWatch(Connector):
    descriptor = SourceDescriptor(
        id="noaa_coastwatch", name="NOAA CoastWatch ERDDAP", organization="NOAA NESDIS CoastWatch",
        authority_tier=AuthorityTier.NATIONAL_AGENCY_FOREIGN, integration="live", access="public",
        homepage="https://coastwatch.noaa.gov/", docs_url="https://coastwatch.noaa.gov/erddap/griddap/index.html",
        license="Public domain (US Government work)", rate_limit="fair use; large subsets throttled",
        datasets=[
            DatasetDescriptor(id=p["dataset"], title=p["title"], variables=[k], kind=DataKind.ANALYSIS,
                              spatial_resolution=p["spatial"], temporal_resolution="daily",
                              update_interval_s=86400, expected_latency_s=48 * 3600, coverage="global ocean",
                              producer="NOAA NESDIS", units={k: p["units"]})
            for k, p in PRODUCTS.items()],
        notes=["Satellite-derived gridded analyses (observation-based, not forecasts).",
               "Chlorophyll is gap-filled with DINEOF; cloud-covered pixels are statistically reconstructed."],
    )

    def _query(self, key: str, time_sel: str, bbox: BBox, stride: int) -> str:
        p = PRODUCTS[key]
        alt = "[(0.0)]" if p["alt"] else ""
        q = (f"{p['var']}[{time_sel}]{alt}"
             f"[({bbox.lat_min:.3f}):{stride}:({bbox.lat_max:.3f})]"
             f"[({bbox.lon_min:.3f}):{stride}:({bbox.lon_max:.3f})]")
        return f"{BASE}/{p['dataset']}.json?{quote(q, safe='():,')}"

    def _rows(self, data: dict) -> list[list]:
        return data.get("table", {}).get("rows", [])

    async def grid(self, key: str, bbox: BBox, *, stride: int = 1, time: Optional[datetime] = None
                   ) -> tuple[Optional[GridField], list[SourceFailure]]:
        """Latest (or given-day) 2-D field over bbox."""
        p = PRODUCTS[key]
        tsel = "(last)" if time is None else f"({time:%Y-%m-%dT12:00:00Z})"
        url = self._query(key, tsel, bbox, stride)
        try:
            res = await self.get(url, None, ttl_s=3600, timeout_s=45, retries=1)
        except TransportError as e:
            return None, [self.failure(e, impact=f"{key} satellite evidence excluded")]
        rows = self._rows(res.data)
        if not rows:
            return None, [self.failure(TransportError(self.descriptor.id, "NO_DATA", "empty subset"))]
        cols = res.data["table"]["columnNames"]
        ilat, ilon, ival = cols.index("latitude"), cols.index("longitude"), cols.index(p["var"])
        t = parse_utc(rows[0][0])
        lats = sorted({round(r[ilat], 4) for r in rows})
        lons = sorted({round(r[ilon], 4) for r in rows})
        li = {v: i for i, v in enumerate(lats)}
        lj = {v: j for j, v in enumerate(lons)}
        vals: list[list[Optional[float]]] = [[None] * len(lons) for _ in lats]
        for r in rows:
            v = r[ival]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                vals[li[round(r[ilat], 4)]][lj[round(r[ilon], 4)]] = float(v)
        ds = self.dataset(p["dataset"])
        prov = self.provenance(ds=ds, variable=key, units=p["units"], res=res, timestamp=t, last_updated=t,
                               extent=bbox.as_list(),
                               has_data=any(v is not None for row in vals for v in row),
                               notes=[f"subset stride {stride} (~{p['res_deg'] * stride:.2f}°)"])
        return GridField(variable=key, units=p["units"], lats=lats, lons=lons, times=[t], values=[vals],
                         provenance=prov), []

    async def point(self, key: str, pt: GeoPoint, half_deg: float = 0.1) -> tuple[Optional[PointValue], list[SourceFailure]]:
        """Value at the nearest valid pixel to pt (searches a small window to skip coastal gaps)."""
        g, fails = await self.grid(key, BBox.around(pt, half_deg))
        if g is None:
            return None, fails
        best = None
        for i, la in enumerate(g.lats):
            for j, lo in enumerate(g.lons):
                v = g.values[0][i][j]
                if v is None:
                    continue
                d = (la - pt.lat) ** 2 + ((lo - pt.lon) * math.cos(math.radians(pt.lat))) ** 2
                if best is None or d < best[0]:
                    best = (d, la, lo, v)
        if best is None:
            return None, [self.failure(TransportError(self.descriptor.id, "NO_DATA",
                                                      f"no valid {key} pixel within ±{half_deg}° (cloud / coast mask)"))]
        _, la, lo, v = best
        return PointValue(variable=key, value=v, units=g.units, location=pt, grid_location=GeoPoint(lat=la, lon=lo),
                          valid_time=g.times[0], provenance=g.provenance), fails

    async def region_series(self, key: str, bbox: BBox, days: int, stride: int
                            ) -> tuple[Optional[TimeSeries], list[SourceFailure]]:
        """Daily area-mean time series over bbox for the latest `days`+1 product days (research / trends).

        Uses ERDDAP index arithmetic ([last-N:1:last]) so the request is always within the product's
        coverage, whatever its latency, and is identical for the same N (replay-stable).
        """
        p = PRODUCTS[key]
        tsel = f"last-{int(days)}:1:last"
        url = self._query(key, tsel, bbox, stride)
        try:
            res = await self.get(url, None, ttl_s=6 * 3600, timeout_s=60, retries=1)
        except TransportError as e:
            return None, [self.failure(e, impact=f"{key} time series unavailable")]
        rows = self._rows(res.data)
        cols = res.data.get("table", {}).get("columnNames", [])
        if not rows:
            return None, [self.failure(TransportError(self.descriptor.id, "NO_DATA", "empty time series"))]
        ival = cols.index(p["var"])
        acc: dict[datetime, list[float]] = {}
        for r in rows:
            v = r[ival]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            acc.setdefault(parse_utc(r[0]), []).append(float(v))
        times = sorted(acc)
        vals = [sum(acc[t]) / len(acc[t]) for t in times]
        ds = self.dataset(p["dataset"])
        prov = self.provenance(ds=ds, variable=key, units=p["units"], res=res,
                               timestamp=times[-1] if times else None, last_updated=times[-1] if times else None,
                               extent=bbox.as_list(), has_data=bool(times), kind=DataKind.HISTORICAL,
                               notes=[f"daily area mean over {len(rows) // max(1, len(times))} pixels (stride {stride})"])
        return TimeSeries(variable=key, units=p["units"], location=GeoPoint(lat=(bbox.lat_min + bbox.lat_max) / 2,
                                                                             lon=(bbox.lon_min + bbox.lon_max) / 2),
                          times=times, values=vals, provenance=prov), []

    async def probe(self) -> dict:
        pv, fails = await self.point("sst", GeoPoint(lat=10.0, lon=75.0), half_deg=0.05)
        if pv is None:
            return {"status": "DEGRADED", "detail": fails[0].reason if fails else "no data"}
        return {"status": "OPERATIONAL", "detail": f"latest SST product {pv.valid_time:%Y-%m-%d}",
                "product_time": pv.valid_time}


def product_age_ok(t: datetime, now: datetime) -> bool:
    return now - t < timedelta(days=4)
