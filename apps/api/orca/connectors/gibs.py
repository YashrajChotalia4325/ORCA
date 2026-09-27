"""NASA GIBS WMTS connector — real satellite imagery tiles for the map.

GIBS layers are *visual* context (colour-mapped PNG tiles); ORCA never reads
numbers off tiles. Quantitative satellite values come from NOAA CoastWatch
ERDDAP. The capabilities document is parsed to find, per layer, the latest
date actually published, so the time slider can only select real dates.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from ..core.clock import utcnow
from ..core.schemas.common import AuthorityTier, DataKind
from .base import Connector, DatasetDescriptor, SourceDescriptor
from .transport import TransportError

CAPS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi"
TILE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{date}/{tms}/{{z}}/{{y}}/{{x}}.{ext}"

LAYERS = {
    "gibs_truecolor": dict(layer="VIIRS_NOAA20_CorrectedReflectance_TrueColor", title="VIIRS NOAA-20 true colour",
                           tms="GoogleMapsCompatible_Level9", ext="jpg", maxzoom=9, variable="imagery"),
    "gibs_sst": dict(layer="GHRSST_L4_MUR_Sea_Surface_Temperature", title="GHRSST MUR L4 SST (JPL)",
                     tms="GoogleMapsCompatible_Level7", ext="png", maxzoom=7, variable="sst"),
    "gibs_sst_anomaly": dict(layer="GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies", title="GHRSST MUR SST anomaly",
                             tms="GoogleMapsCompatible_Level7", ext="png", maxzoom=7, variable="sst_anomaly"),
    "gibs_chlorophyll": dict(layer="OCI_PACE_Chlorophyll_a", title="PACE OCI chlorophyll-a",
                             tms="GoogleMapsCompatible_Level7", ext="png", maxzoom=7, variable="chlorophyll"),
    "gibs_precip": dict(layer="IMERG_Precipitation_Rate", title="GPM IMERG precipitation rate",
                        tms="GoogleMapsCompatible_Level6", ext="png", maxzoom=6, variable="precipitation"),
    "gibs_bathymetry": dict(layer="BlueMarble_ShadedRelief_Bathymetry", title="Blue Marble shaded relief + bathymetry",
                            tms="GoogleMapsCompatible_Level8", ext="jpg", maxzoom=8, variable="bathymetry", static=True),
}


class NasaGIBS(Connector):
    descriptor = SourceDescriptor(
        id="nasa_gibs", name="NASA GIBS", organization="NASA ESDIS (EOSDIS)",
        authority_tier=AuthorityTier.NATIONAL_AGENCY_FOREIGN, integration="live", access="public",
        homepage="https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api",
        docs_url="https://nasa-gibs.github.io/gibs-api-docs/", license="NASA open data (no restrictions, attribution requested)",
        rate_limit="fair use",
        datasets=[DatasetDescriptor(id=v["layer"], title=v["title"], variables=[v["variable"]], kind=DataKind.ANALYSIS,
                                    spatial_resolution=f"WMTS z≤{v['maxzoom']}", temporal_resolution="daily",
                                    update_interval_s=None if v.get("static") else 86400,
                                    expected_latency_s=None if v.get("static") else 36 * 3600,
                                    coverage="global") for v in LAYERS.values()],
        notes=["Map imagery only — ORCA does not derive numeric values from tiles."],
    )

    _cache: dict[str, Any] = {}

    async def latest_dates(self) -> dict[str, dict]:
        now = utcnow()
        c = NasaGIBS._cache
        if c.get("at") and now - c["at"] < timedelta(hours=6):
            return c["dates"]
        dates: dict[str, dict] = {}
        try:
            res = await self.get(CAPS, {"SERVICE": "WMTS", "REQUEST": "GetCapabilities"}, ttl_s=6 * 3600,
                                 timeout_s=60, retries=1, parse="text")
            xml: str = res.data
            for key, v in LAYERS.items():
                i = xml.find(f"<ows:Identifier>{v['layer']}</ows:Identifier>")
                if i < 0:
                    continue
                s, e = xml.rfind("<Layer>", 0, i), xml.find("</Layer>", i)
                block = xml[s:e]
                default = re.findall(r"<Default>([^<]+)</Default>", block)
                values = re.findall(r"<Value>([^<]+)</Value>", block)
                start = None
                if values:
                    start = values[0].split("/")[0]
                dates[key] = {"latest": default[0] if default else None, "earliest": start}
            c.update(at=now, dates=dates, retrieved_at=res.retrieved_at)
        except TransportError as e:
            c.update(at=now, dates={}, error=e.message)
        return dates

    async def layer_catalog(self) -> list[dict]:
        dates = await self.latest_dates()
        out = []
        for key, v in LAYERS.items():
            d = dates.get(key, {})
            latest = d.get("latest")
            if v.get("static"):
                tmpl = f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{v['layer']}/default/default/{v['tms']}/{{z}}/{{y}}/{{x}}.{v['ext']}"
            else:
                tmpl = TILE.format(layer=v["layer"], date="{date}", tms=v["tms"], ext=v["ext"])
            out.append({
                "id": key, "title": v["title"], "source": "NASA GIBS", "gibs_layer": v["layer"],
                "tile_template": tmpl, "maxzoom": v["maxzoom"], "latest_date": latest,
                "earliest_date": d.get("earliest"), "time_dependent": not v.get("static"),
                "available": bool(latest) or bool(v.get("static")),
                "attribution": "Imagery: NASA EOSDIS GIBS",
                "note": "Visual layer; values are not used for reasoning.",
            })
        return out

    async def probe(self) -> dict:
        d = await self.latest_dates()
        if not d:
            return {"status": "DEGRADED", "detail": NasaGIBS._cache.get("error", "capabilities unavailable")}
        return {"status": "OPERATIONAL", "detail": f"MUR SST latest {d.get('gibs_sst', {}).get('latest')}"}


def date_for_offset(latest: str | None, target: datetime) -> str | None:
    """Pick the tile date for a slider time: the target date, capped at the latest published date."""
    if not latest:
        return None
    lt = date.fromisoformat(latest)
    t = target.date()
    return (t if t <= lt else lt).isoformat()
