"""GEBCO 2020 bathymetry via the public OpenTopoData API (no key, 1 call/s, 100 points/call)."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from ..core.schemas.common import AuthorityTier, DataKind, GeoPoint
from ..core.schemas.provenance import PointValue, SourceFailure
from .base import Connector, DatasetDescriptor, SourceDescriptor
from .transport import TransportError

URL = "https://api.opentopodata.org/v1/gebco2020"
_lock = asyncio.Lock()
_last = [0.0]


class GEBCO(Connector):
    descriptor = SourceDescriptor(
        id="gebco", name="GEBCO 2020 bathymetry", organization="GEBCO (IHO / IOC-UNESCO)",
        distributor="OpenTopoData", authority_tier=AuthorityTier.SCIENTIFIC_COMPILATION,
        integration="live", access="public", homepage="https://www.gebco.net/",
        docs_url="https://www.opentopodata.org/datasets/gebco2020/", license="GEBCO grid: public domain-like, attribution requested",
        rate_limit="1 call/s, 100 locations/call, 1000 calls/day (public OpenTopoData)",
        datasets=[DatasetDescriptor(id="gebco2020", title="GEBCO 2020 global terrain model", variables=["depth"],
                                    kind=DataKind.REFERENCE, spatial_resolution="15 arc-second (~450 m)",
                                    temporal_resolution="static (2020 release)", coverage="global",
                                    units={"depth": "m"})],
        notes=["Static grid; freshness is 'STATIC'. Elevation < 0 is below mean sea level."],
    )

    async def depths(self, pts: list[GeoPoint]) -> tuple[list[Optional[PointValue]], list[SourceFailure]]:
        out: list[Optional[PointValue]] = []
        fails: list[SourceFailure] = []
        ds = self.descriptor.datasets[0]
        for i in range(0, len(pts), 100):
            chunk = pts[i:i + 100]
            locs = "|".join(f"{p.lat:.3f},{p.lon:.3f}" for p in chunk)
            try:
                async with _lock:
                    wait = 1.05 - (time.monotonic() - _last[0])
                    if wait > 0 and self.ctx.mode.value == "LIVE":
                        await asyncio.sleep(wait)
                    res = await self.get(URL, {"locations": locs}, ttl_s=30 * 86400, retries=1)
                    _last[0] = time.monotonic()
                results = res.data.get("results", [])
                for p, r in zip(chunk, results):
                    prov = self.provenance(ds=ds, variable="depth", units="m", res=res,
                                           extent=[p.lon, p.lat, p.lon, p.lat], has_data=r.get("elevation") is not None)
                    out.append(PointValue(variable="depth", value=r.get("elevation"), units="m", location=p,
                                          provenance=prov))
            except TransportError as e:
                fails.append(self.failure(e, impact="depth context unavailable"))
                out.extend(None for _ in chunk)
        return out, fails

    def static_status(self):
        from ..core.schemas.common import SourceStatus
        return SourceStatus.UNKNOWN

    async def probe(self) -> dict:
        v, f = await self.depths([GeoPoint(lat=9.9, lon=75.0)])
        if f or not v or v[0] is None:
            return {"status": "DEGRADED", "detail": f[0].reason if f else "no data"}
        return {"status": "OPERATIONAL", "detail": f"sample depth {v[0].value:.0f} m at 9.9N 75.0E"}
