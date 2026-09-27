"""Synthetic marine environment for DEMO mode.

Produces physically plausible, deterministic fields (waves, wind, rain,
convection, currents, SST, chlorophyll, bathymetry, cyclone vortex) and
serves them in the *exact* response formats of the upstream APIs, so the
whole ORCA pipeline (connectors → agents → risk → evidence) runs unmodified.
Everything served here is labelled SIMULATED by the DEMO transport.
"""
from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse

from ..connectors.transport import TransportError
from ..core import spatial
from ..core.schemas.common import GeoPoint
from ..geo.reference import ReferenceStore

UTC = timezone.utc


@dataclass
class Blob:
    """A localized, time-limited anomaly: amp × gaussian(space) × ramp(time)."""
    var: str
    lat: float
    lon: float
    radius_km: float
    amp: float
    t_start_h: float = -1e9          # hours relative to scenario 'now'
    t_peak_h: float = 0.0
    t_end_h: float = 1e9


@dataclass
class Ramp:
    var: str
    t0_h: float
    t1_h: float
    delta: float


@dataclass
class Cyclone:
    name: str
    track: list[tuple[float, float, float, float]]   # (t_h, lat, lon, vmax_kmh)
    rmax_km: float = 40.0
    alert: str = "Red"
    source: str = "SIMULATED"


@dataclass
class Environment:
    base: dict[str, float]
    coastal: dict[str, float] = field(default_factory=dict)     # extra added near coast (decays with 60 km scale)
    blobs: list[Blob] = field(default_factory=list)
    ramps: list[Ramp] = field(default_factory=list)
    cyclone: Optional[Cyclone] = None
    sst_front: Optional[dict] = None                              # {lat0, lat1, lon, width_km, delta, chl_boost}
    daily_trend: dict[str, float] = field(default_factory=dict)  # per-day linear change (research)
    trend_ref_day: float = 0.0
    bias: dict[str, dict[str, float]] = field(default_factory=dict)   # source_id -> var -> multiplier

    # ------------------------------------------------------------------ core field
    def value(self, var: str, lat: float, lon: float, t_h: float, source: str = "") -> Optional[float]:
        dc = coast_km(round(lat, 2), round(lon, 2))
        if var in ("wave_height", "swell_height", "wind_wave_height", "current_speed", "sst", "sst_model", "chlorophyll") and dc < 0:
            return None
        v = self.base.get(var, 0.0)
        v += self.coastal.get(var, 0.0) * math.exp(-max(dc, 0) / 60.0)
        v += self.daily_trend.get(var, 0.0) * (t_h / 24.0 - self.trend_ref_day)
        for r in self.ramps:
            if r.var == var:
                if t_h >= r.t1_h:
                    v += r.delta
                elif t_h > r.t0_h:
                    v += r.delta * (t_h - r.t0_h) / (r.t1_h - r.t0_h)
        for b in self.blobs:
            if b.var != var or not (b.t_start_h <= t_h <= b.t_end_h):
                continue
            d = spatial.distance_km(GeoPoint(lat=lat, lon=lon), GeoPoint(lat=b.lat, lon=b.lon))
            tw = 1.0
            if t_h < b.t_peak_h and b.t_peak_h > b.t_start_h:
                tw = (t_h - b.t_start_h) / (b.t_peak_h - b.t_start_h)
            elif t_h > b.t_peak_h and b.t_end_h > b.t_peak_h:
                tw = max(0.0, 1 - (t_h - b.t_peak_h) / (b.t_end_h - b.t_peak_h))
            v += b.amp * math.exp(-(d / b.radius_km) ** 2) * tw
        if self.sst_front and var in ("sst", "sst_model", "chlorophyll"):
            f = self.sst_front
            if f["lat0"] <= lat <= f["lat1"]:
                x = (lon - f["lon"]) * 111.32 * math.cos(math.radians(lat))   # km east of the front line
                s = math.tanh(x / f["width_km"])
                if var in ("sst", "sst_model"):
                    v += 0.5 * f["delta"] * s          # warm offshore, cool inshore (upwelling)
                else:
                    v += f.get("chl_boost", 0.0) * math.exp(-(x / (2.5 * f["width_km"])) ** 2)
        if self.cyclone and var in ("wind_speed", "wind_gusts", "wave_height", "precipitation", "pressure", "cape",
                                    "swell_height", "wind_direction"):
            v = self._cyclone(var, lat, lon, t_h, v)
        v *= self.bias.get(source, {}).get(var, 1.0)
        v += _noise(var, lat, lon, t_h, source)
        if var in ("wave_height", "swell_height", "wind_wave_height", "wind_speed", "wind_gusts", "precipitation", "cape",
                   "current_speed", "chlorophyll", "visibility"):
            v = max(v, 0.0 if var != "chlorophyll" else 0.03)
        if var == "wind_gusts":
            v = max(v, 1.3 * (self.value("wind_speed", lat, lon, t_h, source) or 0.0))
        return v

    def _cyclone_pos(self, t_h: float) -> Optional[tuple[float, float, float]]:
        tr = self.cyclone.track
        if t_h < tr[0][0] or t_h > tr[-1][0]:
            return None
        for a, b in zip(tr[:-1], tr[1:]):
            if a[0] <= t_h <= b[0]:
                w = (t_h - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0
                return a[1] + (b[1] - a[1]) * w, a[2] + (b[2] - a[2]) * w, a[3] + (b[3] - a[3]) * w
        return tr[-1][1], tr[-1][2], tr[-1][3]

    def _cyclone(self, var, lat, lon, t_h, v):
        pos = self._cyclone_pos(t_h)
        if pos is None:
            return v
        clat, clon, vmax = pos
        r = spatial.distance_km(GeoPoint(lat=lat, lon=lon), GeoPoint(lat=clat, lon=clon))
        rm = self.cyclone.rmax_km
        vr = vmax * (r / rm) if r < rm else vmax * (rm / r) ** 0.6
        if var == "wind_speed":
            return max(v, vr)
        if var == "wind_gusts":
            return max(v, vr * 1.35)
        if var in ("wave_height",):
            return max(v, (vr / 40.0) ** 1.7)
        if var == "swell_height":
            return max(v, 0.6 * (vr / 40.0) ** 1.7)
        if var == "precipitation":
            return v + 25.0 * math.exp(-(r / 180.0) ** 2)
        if var == "pressure":
            return v - 30.0 * math.exp(-(r / 250.0) ** 2)
        if var == "cape":
            return v + 1500.0 * math.exp(-(r / 300.0) ** 2)
        if var == "wind_direction":
            if r < 1500:
                brg = spatial.bearing_deg(GeoPoint(lat=clat, lon=clon), GeoPoint(lat=lat, lon=lon))
                return (brg - 90 - 20) % 360  # counter-clockwise inflow (NH)
        return v


@lru_cache(maxsize=200_000)
def coast_km(lat: float, lon: float) -> float:
    """Signed distance to coast in km (negative on land).

    Simulator-only approximation: planar degree distance scaled by 111 km (cos-lat corrected), computed with
    shapely's vectorised C routines. The real agents use exact local-projection distances (core/spatial.py).
    """
    import shapely
    from shapely.geometry import Point
    ref = ReferenceStore.get()
    k = math.cos(math.radians(lat))
    d_deg = shapely.distance(Point(lon, lat), ref.coast)
    d = d_deg * 111.0 * (0.5 * (1 + k))
    return d if ref.is_sea(GeoPoint(lat=lat, lon=lon)) else -d


def _noise(var: str, lat: float, lon: float, t_h: float, source: str) -> float:
    amp = {"wave_height": 0.06, "wind_speed": 1.2, "wind_gusts": 1.5, "current_speed": 0.1, "sst": 0.05, "sst_model": 0.08,
           "chlorophyll": 0.03, "precipitation": 0.05, "cape": 40.0}.get(var, 0.0)
    if not amp:
        return 0.0
    h = (zlib.crc32(f"{var}|{source}".encode()) % 1000) / 1000.0   # deterministic across processes
    return amp * (math.sin(lat * 3.1 + lon * 2.3 + t_h * 0.21 + h * 6.28) * 0.6 + math.sin(lat * 7.7 - lon * 5.3 + t_h * 0.07) * 0.4)


# ============================================================================ response builders
OM_VARS = {
    # upstream name -> (env var, converter to upstream unit)
    "wave_height": ("wave_height", None), "wave_direction": ("wave_direction", None), "wave_period": ("wave_period", None),
    "wind_wave_height": ("wind_wave_height", None), "swell_wave_height": ("swell_height", None),
    "swell_wave_period": ("swell_period", None), "swell_wave_direction": ("swell_direction", None),
    "ocean_current_velocity": ("current_speed", None), "ocean_current_direction": ("current_direction", None),
    "sea_surface_temperature": ("sst_model", None), "wind_speed_10m": ("wind_speed", None),
    "wind_direction_10m": ("wind_direction", None), "wind_gusts_10m": ("wind_gusts", None),
    "precipitation": ("precipitation", None), "pressure_msl": ("pressure", None), "cape": ("cape", None),
    "visibility": ("visibility", lambda v: v * 1000.0), "weather_code": ("weather_code", None),
}
MARINE_API_MODELS = {"meteofrance_wave": "om_mfwam", "ecmwf_wam025": "om_ecmwf_wam", "ncep_gfswave025": "om_gfs_wave",
                     "meteofrance_currents": "om_smoc", "dwd_gwam": "om_dwd_gwam", "ecmwf_ifs025": "om_ecmwf_ifs",
                     "gfs_global": "om_gfs", "icon_global": "om_icon", "ukmo_global_deterministic_10km": "om_ukmo"}


def openmeteo(env: Environment, now: datetime, source_id: str, params: dict, marine: bool) -> Any:
    lats = [float(x) for x in str(params["latitude"]).split(",")]
    lons = [float(x) for x in str(params["longitude"]).split(",")]
    hourly = str(params.get("hourly", "")).split(",")
    past, fdays = int(params.get("past_days", 0)), int(params.get("forecast_days", 3))
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=past)
    n = 24 * (past + fdays)
    times = [day0 + timedelta(hours=k) for k in range(n)]
    th = [(t - now).total_seconds() / 3600 for t in times]
    out = []
    for la, lo in zip(lats, lons):
        # snap to the model grid (0.25° for coarse models) like the real service
        res = 0.25 if any(k in source_id for k in ("ecmwf", "gfs", "gwam")) else 0.083
        gla, glo = round(la / res) * res, round(lo / res) * res
        obj = {"latitude": gla, "longitude": glo, "generationtime_ms": 0.1, "utc_offset_seconds": 0, "timezone": "GMT",
               "hourly_units": {}, "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}}
        for up in hourly:
            if up not in OM_VARS:
                continue
            var, conv = OM_VARS[up]
            vals = []
            for t in th:
                if var in ("wave_direction", "swell_direction"):
                    v = 250.0 + 10 * math.sin(t / 12)
                elif var in ("wave_period",):
                    v = 7.0 + 2.5 * (env.value("wave_height", gla, glo, t, source_id) or 0) / 2
                elif var == "swell_period":
                    v = 11.0
                elif var == "current_direction":
                    v = 170.0 + 20 * math.sin(t / 10)
                elif var == "weather_code":
                    p = env.value("precipitation", gla, glo, t, source_id) or 0
                    v = 95 if p > 10 else 63 if p > 4 else 61 if p > 1 else 3
                elif var == "wind_direction" and not env.cyclone:
                    v = 290.0 + 15 * math.sin(t / 9)
                elif var == "visibility":
                    p = env.value("precipitation", gla, glo, t, source_id) or 0
                    v = max(0.5, 24.0 - 2.5 * p)
                elif var == "wind_wave_height":
                    v = 0.55 * (env.value("wave_height", gla, glo, t, source_id) or 0)
                elif var == "swell_height" and "swell_height" not in env.base:
                    hs = env.value("wave_height", gla, glo, t, source_id)
                    v = None if hs is None else 0.75 * hs
                else:
                    v = env.value(var, gla, glo, t, source_id)
                if marine and coast_km(round(gla, 2), round(glo, 2)) < 0:
                    v = None
                vals.append(None if v is None else round(conv(v) if conv else v, 2))
            obj["hourly"][up] = vals
            obj["hourly_units"][up] = "°C" if "temperature" in up else "km/h" if ("speed" in up or "gust" in up or "velocity" in up) else ""
        out.append(obj)
    return out if len(out) > 1 else out[0]


def openmeteo_meta(now: datetime, model: str) -> dict:
    step = 12 if model in ("meteofrance_wave", "dwd_gwam") else 24 if model == "meteofrance_currents" else 6
    init = now.replace(minute=0, second=0, microsecond=0)
    init = init - timedelta(hours=init.hour % step) - timedelta(hours=step)
    avail = init + timedelta(hours=5, minutes=20)
    return {"last_run_initialisation_time": int(init.timestamp()), "last_run_availability_time": int(avail.timestamp()),
            "last_run_modification_time": int(avail.timestamp()), "update_interval_seconds": step * 3600,
            "temporal_resolution_seconds": 3600}


ERDDAP_VAR = {"noaacwBLENDEDsstDNDaily": ("analysed_sst", "sst", 0.05),
              "noaacrwsstanomalyDaily": ("sea_surface_temperature_anomaly", "sst_anomaly", 0.05),
              "noaacwNPPN20VIIRSDINEOFDaily": ("chlor_a", "chlorophyll", 1 / 12)}


def erddap(env: Environment, now: datetime, url: str, climatology_sst: Callable[[float, float], float]) -> dict:
    u = unquote(url)
    ds = re.search(r"/griddap/([A-Za-z0-9]+)\.json", u).group(1)
    upvar, var, res = ERDDAP_VAR[ds]
    q = u.split("?", 1)[1]
    brackets = re.findall(r"\[([^\]]*)\]", q)
    tsel = brackets[0]
    rest = [b for b in brackets[1:] if b != "(0.0)"]
    latsel, lonsel = rest[0], rest[1]

    def rng(sel: str) -> tuple[float, int, float]:
        m = re.match(r"\((-?[\d.]+)\):(\d+):\((-?[\d.]+)\)", sel)
        if m:
            return float(m.group(1)), int(m.group(2)), float(m.group(3))
        v = float(sel.strip("()"))
        return v, 1, v

    lat0, ls, lat1 = rng(latsel)
    lon0, os_, lon1 = rng(lonsel)
    product_day = (now - timedelta(hours=36)).replace(hour=12, minute=0, second=0, microsecond=0)
    if tsel == "(last)":
        days = [product_day]
    elif tsel.startswith("last-"):
        n = int(tsel.split(":")[0][5:])
        days = [product_day - timedelta(days=k) for k in range(n, -1, -1)]
    elif ":" in tsel:
        m = re.match(r"\(([^)]+)\):1:\(([^)]+)\)", tsel)
        d0 = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        d1 = min(datetime.fromisoformat(m.group(2).replace("Z", "+00:00")), product_day)
        days = []
        d = d0
        while d <= d1:
            days.append(d)
            d += timedelta(days=1)
    else:
        days = [datetime.fromisoformat(tsel.strip("()").replace("Z", "+00:00"))]
    step = res * max(ls, os_)
    lats, lons = [], []
    la = math.floor(min(lat0, lat1) / res) * res + res / 2
    while la <= max(lat0, lat1) + 1e-9:
        lats.append(round(la, 4)); la += step
    lo = math.floor(min(lon0, lon1) / res) * res + res / 2
    while lo <= max(lon0, lon1) + 1e-9:
        lons.append(round(lo, 4)); lo += step
    rows = []
    for d in days:
        th = (d - now).total_seconds() / 3600
        for la in lats:
            for lo in lons:
                if var == "sst_anomaly":
                    s = env.value("sst", la, lo, th, "noaa_coastwatch")
                    v = None if s is None else s - climatology_sst(la, lo) + env.base.get("sst_anomaly_offset", 0.0)
                else:
                    v = env.value(var, la, lo, th, "noaa_coastwatch")
                row = [d.strftime("%Y-%m-%dT%H:%M:%SZ")]
                if var == "chlorophyll":
                    row.append(0.0)
                row += [la, lo, None if v is None else round(v, 3)]
                rows.append(row)
    cols = ["time", "altitude", "latitude", "longitude", upvar] if var == "chlorophyll" else ["time", "latitude", "longitude", upvar]
    return {"table": {"columnNames": cols, "rows": rows}}


def gdacs_events(env: Environment, now: datetime) -> dict:
    c = env.cyclone
    if not c:
        return {"type": "FeatureCollection", "features": []}
    t_first, t_last = c.track[0][0], min(c.track[-1][0], 0.0)
    pos = env._cyclone_pos(min(0.0, c.track[-1][0])) or c.track[-1][1:]
    lat, lon, vmax = pos[0], pos[1], pos[2]
    fd = now + timedelta(hours=t_first)
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 2), round(lat, 2)]},
        "properties": {"eventtype": "TC", "eventid": 9900001, "episodeid": 1, "name": f"Tropical Cyclone {c.name}",
                       "alertlevel": c.alert, "iscurrent": "true", "country": "India",
                       "fromdate": fd.strftime("%Y-%m-%dT%H:%M:%S"),
                       "todate": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                       "datemodified": (now - timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%S"),
                       "source": c.source, "severitydata": {"severity": vmax, "severitytext": f"Severe Cyclonic Storm (maximum wind speed of {vmax:.0f} km/h) [SIMULATED]"},
                       "url": {"report": "https://www.gdacs.org/ (simulated event — not a real report)"}}}]}


def _circle(lat: float, lon: float, r_km: float, n: int = 36) -> list[list[float]]:
    pts = [spatial.destination(GeoPoint(lat=lat, lon=lon), b, r_km) for b in range(0, 360, 360 // n)]
    ring = [[round(p.lon, 3), round(p.lat, 3)] for p in pts]
    return ring + [ring[0]]


def gdacs_geometry(env: Environment, now: datetime) -> dict:
    c = env.cyclone
    feats = []
    for k, (t_h, lat, lon, vmax) in enumerate(c.track):
        t = now + timedelta(hours=t_h)
        label = t.strftime("%d/%m %H:%M UTC")
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [_circle(lat, lon, 8, 12)]},
                      "properties": {"Class": f"Point_Polygon_Point_{k}", "polygonlabel": label}})
        for cls, thr in (("Poly_Green", 63), ("Poly_Orange", 93), ("Poly_Red", 119)):
            # radius where the vortex wind drops to the threshold
            if vmax <= thr:
                continue
            r = c.rmax_km * (vmax / thr) ** (1 / 0.6)
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [_circle(lat, lon, r)]},
                          "properties": {"Class": cls, "polygondate": t.strftime("%Y-%m-%dT%H:%M:%S")}})
    return {"type": "FeatureCollection", "features": feats}


def gebco(params: dict) -> dict:
    res = []
    for loc in str(params["locations"]).split("|"):
        la, lo = (float(x) for x in loc.split(","))
        d = coast_km(round(la, 2), round(lo, 2))
        elev = -min(4200.0, 4 + 1.6 * d + 0.012 * d * d) if d >= 0 else 10.0
        res.append({"dataset": "gebco2020", "elevation": round(elev), "location": {"lat": la, "lng": lo}})
    return {"results": res, "status": "OK"}


def climatology(lat: float, lon: float) -> float:
    return 28.3 + 0.04 * (15 - lat)
