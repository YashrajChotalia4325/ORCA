"""Open-Meteo connectors (marine + weather), one connector instance per upstream model.

Open-Meteo redistributes the official output of ECMWF, Météo-France, NOAA
NCEP and DWD models under CC-BY 4.0 with no API key. Each model is exposed as
its own ORCA source so that cross-model agreement can be measured and one
model's outage never hides the others. Model run initialisation and
availability times come from Open-Meteo's `/data/<model>/static/meta.json`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..core.clock import parse_utc
from ..core.schemas.common import AuthorityTier, DataKind, GeoPoint
from ..core.schemas.provenance import SourceFailure, TimeSeries
from .base import Connector, ConnectorContext, DatasetDescriptor, SourceDescriptor
from .transport import TransportError

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
MARINE_META = "https://marine-api.open-meteo.com/data/{model}/static/meta.json"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_META = "https://api.open-meteo.com/data/{model}/static/meta.json"

# upstream variable -> (ORCA canonical variable, canonical unit, converter from upstream unit)
MARINE_VARS = {
    "wave_height": ("wave_height", "m", None),
    "wave_direction": ("wave_direction", "°", None),
    "wave_period": ("wave_period", "s", None),
    "wind_wave_height": ("wind_wave_height", "m", None),
    "swell_wave_height": ("swell_height", "m", None),
    "swell_wave_period": ("swell_period", "s", None),
    "swell_wave_direction": ("swell_direction", "°", None),
    "ocean_current_velocity": ("current_speed", "km/h", None),
    "ocean_current_direction": ("current_direction", "°", None),
    "sea_surface_temperature": ("sst_model", "°C", None),
}
WEATHER_VARS = {
    "wind_speed_10m": ("wind_speed", "km/h", None),
    "wind_direction_10m": ("wind_direction", "°", None),
    "wind_gusts_10m": ("wind_gusts", "km/h", None),
    "precipitation": ("precipitation", "mm/h", None),
    "pressure_msl": ("pressure", "hPa", None),
    "cape": ("cape", "J/kg", None),
    "visibility": ("visibility", "km", lambda v: None if v is None else v / 1000.0),
    "weather_code": ("weather_code", "WMO code", None),
}


@dataclass(frozen=True)
class ModelSpec:
    source_id: str
    api_model: str
    meta_model: str
    name: str
    organization: str
    tier: AuthorityTier
    spatial: str
    temporal: str
    interval_s: int
    latency_s: int
    variables: tuple[str, ...]
    family: str       # marine | weather
    lineage: str      # independence group for the evidence model
    notes: tuple[str, ...] = ()
    role: str = "primary"   # primary | tiebreaker (queried only when the planner requests an extra independent source)


WAVE_VARS = ("wave_height", "wave_direction", "wave_period", "wind_wave_height",
             "swell_wave_height", "swell_wave_period", "swell_wave_direction")

MODELS: dict[str, ModelSpec] = {m.source_id: m for m in [
    ModelSpec("om_mfwam", "meteofrance_wave", "meteofrance_wave", "Météo-France MFWAM", "Météo-France",
              AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.08° (~8 km)", "3-hourly", 43200, 6 * 3600,
              WAVE_VARS, "marine", "mfwam",
              ("MFWAM is the wave model behind the Copernicus Marine global wave forecast; ORCA receives it via Open-Meteo, not the Copernicus Marine Data Store.",)),
    ModelSpec("om_ecmwf_wam", "ecmwf_wam025", "ecmwf_wam025", "ECMWF WAM", "ECMWF",
              AuthorityTier.INTERGOVERNMENTAL, "0.25° (~28 km)", "3-hourly", 21600, 8 * 3600,
              WAVE_VARS, "marine", "ecmwf"),
    ModelSpec("om_gfs_wave", "ncep_gfswave025", "ncep_gfswave025", "NOAA GFS-Wave (WAVEWATCH III)", "NOAA NCEP",
              AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.25° (~28 km)", "hourly", 21600, 6 * 3600,
              WAVE_VARS, "marine", "ncep"),
    ModelSpec("om_smoc", "meteofrance_currents", "meteofrance_currents", "Météo-France / Mercator SMOC currents", "Météo-France / Mercator Ocean",
              AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.08° (~8 km)", "hourly", 86400, 12 * 3600,
              ("ocean_current_velocity", "ocean_current_direction", "sea_surface_temperature"), "marine", "mercator",
              ("SMOC surface currents (incl. tides and Stokes drift) are distributed by Copernicus Marine; ORCA receives them via Open-Meteo.",)),
    ModelSpec("om_ecmwf_ifs", "ecmwf_ifs025", "ecmwf_ifs025", "ECMWF IFS", "ECMWF",
              AuthorityTier.INTERGOVERNMENTAL, "0.25° (~28 km)", "3-hourly", 21600, 8 * 3600,
              ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation", "pressure_msl", "cape", "weather_code"),
              "weather", "ecmwf"),
    ModelSpec("om_gfs", "gfs_global", "ncep_gfs025", "NOAA GFS", "NOAA NCEP",
              AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.25° (~28 km)", "hourly", 21600, 6 * 3600,
              ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation", "pressure_msl", "cape", "visibility", "weather_code"),
              "weather", "ncep"),
    ModelSpec("om_icon", "icon_global", "dwd_icon", "DWD ICON", "Deutscher Wetterdienst",
              AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.125° (~13 km)", "hourly", 21600, 6 * 3600,
              ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation", "pressure_msl", "cape", "weather_code"),
              "weather", "dwd"),
    ModelSpec("om_dwd_gwam", "dwd_gwam", "dwd_gwam", "DWD GWAM", "Deutscher Wetterdienst",
              AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.25° (~28 km)", "3-hourly", 43200, 8 * 3600,
              WAVE_VARS[:5], "marine", "dwd", role="tiebreaker"),
    ModelSpec("om_ukmo", "ukmo_global_deterministic_10km", "ukmo_global_deterministic_10km", "UK Met Office Global",
              "Met Office (UK)", AuthorityTier.NATIONAL_AGENCY_FOREIGN, "0.09° (~10 km)", "hourly", 21600, 6 * 3600,
              ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation", "pressure_msl"),
              "weather", "ukmo", role="tiebreaker"),
]}


def _descriptor(m: ModelSpec) -> SourceDescriptor:
    table = MARINE_VARS if m.family == "marine" else WEATHER_VARS
    return SourceDescriptor(
        id=m.source_id, name=m.name, organization=m.organization, distributor="Open-Meteo",
        authority_tier=m.tier, integration="live", access="public",
        homepage="https://open-meteo.com/",
        docs_url="https://open-meteo.com/en/docs/marine-weather-api" if m.family == "marine" else "https://open-meteo.com/en/docs",
        license="CC-BY 4.0 (Open-Meteo); upstream model terms apply",
        rate_limit="10,000 calls/day non-commercial (multi-location calls count per location)",
        datasets=[DatasetDescriptor(
            id=m.api_model, title=f"{m.name} forecast", variables=[table[v][0] for v in m.variables],
            kind=DataKind.FORECAST, spatial_resolution=m.spatial, temporal_resolution=m.temporal,
            update_interval_s=m.interval_s, expected_latency_s=m.latency_s, coverage="global",
            producer=m.organization, units={table[v][0]: table[v][1] for v in m.variables})],
        notes=list(m.notes),
        critical_for=["safety"] if ("wave_height" in m.variables or "wind_speed_10m" in m.variables) else [],
    )


class RunInfo:
    def __init__(self, issued_at: Optional[datetime], available_at: Optional[datetime], interval_s: Optional[int]):
        self.issued_at, self.available_at, self.interval_s = issued_at, available_at, interval_s


class OpenMeteoModel(Connector):
    def __init__(self, ctx: ConnectorContext, spec: ModelSpec):
        super().__init__(ctx)
        self.spec = spec
        self.descriptor = _descriptor(spec)
        self._table = MARINE_VARS if spec.family == "marine" else WEATHER_VARS

    @property
    def lineage(self) -> str:
        return self.spec.lineage

    def _url(self) -> str:
        return MARINE_URL if self.spec.family == "marine" else WEATHER_URL

    async def run_info(self) -> RunInfo:
        url = (MARINE_META if self.spec.family == "marine" else WEATHER_META).format(model=self.spec.meta_model)
        try:
            r = await self.get(url, None, ttl_s=600, retries=1)
            d = r.data
            ts = lambda k: datetime.fromtimestamp(d[k], tz=timezone.utc) if d.get(k) else None  # noqa: E731
            return RunInfo(ts("last_run_initialisation_time"), ts("last_run_availability_time"),
                           d.get("update_interval_seconds"))
        except (TransportError, KeyError, TypeError, ValueError):
            return RunInfo(None, None, None)

    def _params(self, lats: list[float], lons: list[float], past_days: int, forecast_days: int) -> dict:
        p = {
            "latitude": ",".join(f"{x:.2f}" for x in lats),
            "longitude": ",".join(f"{x:.2f}" for x in lons),
            "hourly": ",".join(self.spec.variables),
            "models": self.spec.api_model,
            "timezone": "GMT",
            "past_days": past_days,
            "forecast_days": forecast_days,
        }
        if self.spec.family == "weather":
            p["wind_speed_unit"] = "kmh"
        return p

    def _parse_one(self, obj: dict, requested: GeoPoint, res, run: RunInfo, variables: list[str] | None) -> dict[str, TimeSeries]:
        hourly = obj.get("hourly") or {}
        units = obj.get("hourly_units") or {}
        times = [parse_utc(t) for t in hourly.get("time", [])]
        grid = GeoPoint(lat=obj.get("latitude", requested.lat), lon=obj.get("longitude", requested.lon))
        ds = self.descriptor.datasets[0]
        out: dict[str, TimeSeries] = {}
        for up in self.spec.variables:
            canon, unit, conv = self._table[up]
            if variables and canon not in variables:
                continue
            key = up if up in hourly else f"{up}_{self.spec.api_model}"
            raw = hourly.get(key)
            if raw is None:
                continue
            vals = [conv(v) if conv else v for v in raw]
            has = any(v is not None for v in vals)
            prov = self.provenance(ds=ds, variable=canon, units=unit, res=res,
                                   issued_at=run.issued_at, last_updated=run.available_at or run.issued_at,
                                   extent=[grid.lon, grid.lat, grid.lon, grid.lat], has_data=has,
                                   notes=[f"upstream unit: {units.get(key, unit)}"] + list(self.spec.notes))
            if run.issued_at is None:
                prov.notes.append("model run time unavailable; freshness based on retrieval time only")
            out[canon] = TimeSeries(variable=canon, units=unit, location=requested, grid_location=grid,
                                    times=times, values=vals, provenance=prov)
        return out

    async def point(self, p: GeoPoint, *, past_days: int = 1, forecast_days: int = 3,
                    variables: list[str] | None = None) -> tuple[dict[str, TimeSeries], list[SourceFailure]]:
        try:
            run = await self.run_info()
            res = await self.get(self._url(), self._params([p.lat], [p.lon], past_days, forecast_days), ttl_s=900)
            obj = res.data[0] if isinstance(res.data, list) else res.data
            if obj.get("error"):
                raise TransportError(self.descriptor.id, "UPSTREAM_ERROR", str(obj.get("reason")))
            series = self._parse_one(obj, p, res, run, variables)
            if not any(any(v is not None for v in s.values) for s in series.values()):
                return {}, [self.failure(TransportError(self.descriptor.id, "NO_DATA",
                                                        "model returned no values at this location (land / outside domain)"))]
            return series, []
        except TransportError as e:
            return {}, [self.failure(e)]

    async def points(self, pts: list[GeoPoint], *, past_days: int = 0, forecast_days: int = 2,
                     variables: list[str] | None = None) -> tuple[list[dict[str, TimeSeries]], list[SourceFailure]]:
        """Multi-location request (chunks of 100). Returns one dict per input point (possibly empty)."""
        out: list[dict[str, TimeSeries]] = []
        failures: list[SourceFailure] = []
        run = await self.run_info()
        for i in range(0, len(pts), 100):
            chunk = pts[i:i + 100]
            try:
                res = await self.get(self._url(), self._params([q.lat for q in chunk], [q.lon for q in chunk],
                                                               past_days, forecast_days), ttl_s=1800, timeout_s=30)
                data = res.data if isinstance(res.data, list) else [res.data]
                if data and isinstance(data[0], dict) and data[0].get("error"):
                    raise TransportError(self.descriptor.id, "UPSTREAM_ERROR", str(data[0].get("reason")))
                for q, obj in zip(chunk, data):
                    out.append(self._parse_one(obj, q, res, run, variables))
            except TransportError as e:
                failures.append(self.failure(e))
                out.extend({} for _ in chunk)
        return out, failures

    async def probe(self) -> dict:
        run = await self.run_info()
        if run.issued_at is None:
            return {"status": "DEGRADED", "detail": "model metadata endpoint unreachable"}
        return {"status": "OPERATIONAL", "detail": f"latest run {run.issued_at:%Y-%m-%d %HZ}",
                "issued_at": run.issued_at, "available_at": run.available_at}


def build_openmeteo(ctx: ConnectorContext) -> dict[str, OpenMeteoModel]:
    return {sid: OpenMeteoModel(ctx, spec) for sid, spec in MODELS.items()}
