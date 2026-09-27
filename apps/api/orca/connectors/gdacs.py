"""GDACS connector — tropical cyclone (and large earthquake) alerts.

GDACS is a cooperation framework of the UN (OCHA) and the European Commission
(JRC). For North Indian Ocean cyclones its track source is usually JTWC.
The *official* Indian authority for cyclone warnings is IMD (RSMC New Delhi);
IMD's API is not publicly accessible (see connectors/restricted.py), so ORCA
labels GDACS as an international advisory source, not the national warning.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

from shapely.geometry import shape

from ..core.clock import UTC, parse_utc
from ..core.schemas.common import AuthorityTier, DataKind, GeoPoint
from ..core.schemas.provenance import Provenance, SourceFailure
from .base import Connector, DatasetDescriptor, SourceDescriptor
from .transport import TransportError

EVENTS = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GEOM = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"

AOI = (45.0, -5.0, 100.0, 30.0)  # lon_min, lat_min, lon_max, lat_max (North Indian Ocean + margin)

WIND_RADII = {"Poly_Green": 63, "Poly_Orange": 93, "Poly_Red": 119}  # km/h wind-buffer thresholds (GDACS)


class GDACS(Connector):
    descriptor = SourceDescriptor(
        id="gdacs", name="GDACS", organization="UN OCHA & European Commission JRC",
        authority_tier=AuthorityTier.INTERGOVERNMENTAL, integration="live", access="public",
        homepage="https://www.gdacs.org/", docs_url="https://www.gdacs.org/Knowledge/models_tc.aspx",
        license="Free use with attribution (GDACS)", rate_limit="fair use",
        datasets=[DatasetDescriptor(
            id="gdacs_tc", title="Tropical cyclone events, tracks, wind radii and uncertainty cones",
            variables=["cyclone"], kind=DataKind.ADVISORY, spatial_resolution="track points (6-hourly)",
            temporal_resolution="per advisory (~6 h)", update_interval_s=6 * 3600, expected_latency_s=3 * 3600,
            coverage="global", producer="JTWC / RSMC via GDACS"),
            DatasetDescriptor(
            id="gdacs_eq", title="Earthquake alerts (tsunami relevance)", variables=["earthquake"],
            kind=DataKind.ADVISORY, spatial_resolution="epicentre", temporal_resolution="event",
            update_interval_s=3600, expected_latency_s=1800, coverage="global")],
        notes=["International alerting system; not the Indian national warning authority (IMD / INCOIS)."],
    )

    @staticmethod
    def _in_aoi(lon: float, lat: float) -> bool:
        return AOI[0] <= lon <= AOI[2] and AOI[1] <= lat <= AOI[3]

    async def cyclones(self) -> tuple[list[dict[str, Any]], Optional[Provenance], list[SourceFailure]]:
        """Current TC events in the Indian Ocean AOI with parsed tracks and wind radii."""
        try:
            res = await self.get(EVENTS, {"eventlist": "TC"}, ttl_s=600)
        except TransportError as e:
            return [], None, [self.failure(e, impact="cyclone advisories excluded")]
        now = self.ctx.now()
        events = []
        for f in (res.data or {}).get("features", []):
            p = f.get("properties", {})
            lon, lat = f["geometry"]["coordinates"][:2]
            if not self._in_aoi(lon, lat):
                continue
            to = parse_utc(p["todate"]) if p.get("todate") else None
            ev = {
                "event_id": p.get("eventid"), "episode_id": p.get("episodeid"), "name": p.get("name"),
                "alert_level": p.get("alertlevel"), "is_current": p.get("iscurrent") == "true",
                "from": parse_utc(p["fromdate"]) if p.get("fromdate") else None, "to": to,
                "modified": parse_utc(p["datemodified"]) if p.get("datemodified") else None,
                "track_source": p.get("source"), "country": p.get("country"),
                "severity_text": (p.get("severitydata") or {}).get("severitytext"),
                "max_wind_kmh": (p.get("severitydata") or {}).get("severity"),
                "centroid": GeoPoint(lat=lat, lon=lon), "report_url": (p.get("url") or {}).get("report"),
                "track": [], "wind_radii": [], "cone": None,
            }
            # Active if the latest advisory is within the last 24 h
            ev["active"] = bool(to and now - to < timedelta(hours=24))
            ev["hours_since_last_advisory"] = round((now - to).total_seconds() / 3600, 1) if to else None
            await self._geometry(ev)
            events.append(ev)
        latest = max((e["modified"] for e in events if e["modified"]), default=None)
        ds = self.dataset("gdacs_tc")
        prov = self.provenance(ds=ds, variable="cyclone", units="", res=res, timestamp=latest, last_updated=latest,
                               extent=list(AOI), has_data=True,
                               notes=[f"{len(events)} TC event(s) in Indian Ocean AOI"])
        # an empty list is valid data ("no active cyclone"), freshness then reflects retrieval only
        return events, prov, []

    async def _geometry(self, ev: dict) -> None:
        try:
            res = await self.get(GEOM, {"eventtype": "TC", "eventid": ev["event_id"], "episodeid": ev["episode_id"]},
                                 ttl_s=1800)
        except TransportError:
            return
        for f in (res.data or {}).get("features", []):
            p, g = f.get("properties", {}), f.get("geometry")
            cls = p.get("Class", "")
            if not g:
                continue
            if cls.startswith("Point_Polygon_Point"):
                m = re.match(r"(\d{2})/(\d{2}) (\d{2}):(\d{2})", p.get("polygonlabel", ""))
                c = shape(g).centroid
                t = None
                if m and ev.get("from"):
                    d, mo, hh, mm = map(int, m.groups())
                    year = ev["from"].year
                    t = datetime(year, mo, d, hh, mm, tzinfo=UTC)
                ev["track"].append({"time": t, "point": GeoPoint(lat=c.y, lon=c.x), "label": p.get("polygonlabel")})
            elif cls in WIND_RADII:
                ev["wind_radii"].append({"threshold_kmh": WIND_RADII[cls], "time": p.get("polygondate"),
                                         "geometry": g})
            elif cls == "Poly_Cones":
                ev["cone"] = g
        ev["track"].sort(key=lambda x: x["time"] or datetime.min.replace(tzinfo=UTC))

    async def probe(self) -> dict:
        ev, prov, fails = await self.cyclones()
        if fails:
            return {"status": "DEGRADED", "detail": fails[0].reason}
        act = [e for e in ev if e["active"]]
        return {"status": "OPERATIONAL", "detail": f"{len(ev)} TC event(s) in AOI, {len(act)} active"}
