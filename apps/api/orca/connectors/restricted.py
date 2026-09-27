"""Adapters for authoritative sources that are NOT openly machine-accessible.

Each adapter:
* declares exactly what access it needs (credentials / IP whitelist / none),
* reports that status honestly on the Data Sources page (with a live probe
  of the public website where useful),
* exposes the method signatures the agents call, so the moment access is
  configured the data flows into the same pipeline,
* in DEMO mode only, is served by the scenario simulator (labelled SIMULATED).

Nothing here fabricates LIVE data.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..core.schemas.common import AuthorityTier, BBox, DataKind, DataMode, SourceStatus
from ..core.schemas.provenance import Provenance, SourceFailure
from .base import Connector, DatasetDescriptor, SourceDescriptor
from .transport import TransportError

DEMO_BASE = "https://demo.orca.invalid"   # never resolvable; only the DEMO transport answers it


def _strip_ip(s: str) -> str:
    return re.sub(r"\b\d{1,3}(\.\d{1,3}){3}\b", "<client-ip>", s)


class _Restricted(Connector):
    probe_url: Optional[str] = None

    def _unavailable(self, what: str) -> SourceFailure:
        st = self.static_status()
        reason = {
            SourceStatus.CREDENTIALS_REQUIRED: f"{self.descriptor.name}: access requires {self.descriptor.access} "
                                               f"({', '.join(self.descriptor.auth_env) or 'agreement'}) — not configured",
            SourceStatus.NO_PUBLIC_API: f"{self.descriptor.name}: no documented public machine-readable API",
        }.get(st, f"{self.descriptor.name}: not configured")
        return self.failure(TransportError(self.descriptor.id, st.value, reason), impact=f"{what} excluded")

    async def probe(self) -> dict[str, Any]:
        st = self.static_status()
        detail = {
            SourceStatus.CREDENTIALS_REQUIRED: "credentials not configured",
            SourceStatus.NO_PUBLIC_API: "no documented public API",
            SourceStatus.NOT_CONFIGURED: "endpoint not configured",
        }.get(st, "configured")
        if self.probe_url:
            try:
                r = await self.get(self.probe_url, None, ttl_s=1800, timeout_s=10, retries=0, parse="text")
                txt = str(r.data)[:300]
                if "whitelist" in txt.lower():
                    detail = "probe: API reachable but access denied — " + _strip_ip(txt.strip())[:120]
                else:
                    detail += " · public website reachable"
            except TransportError as e:
                detail += f" · probe: {e.status} {_strip_ip(e.message)[:100]}"
        return {"status": st.value, "detail": detail}

    async def _demo(self, path: str, params: dict | None = None):
        return await self.get(f"{DEMO_BASE}/{self.descriptor.id}/{path}", params or {}, ttl_s=60)


# ----------------------------------------------------------------------------- ISRO / MOSDAC
class MOSDAC(_Restricted):
    descriptor = SourceDescriptor(
        id="mosdac", name="MOSDAC (ISRO SAC)", organization="Space Applications Centre, ISRO",
        authority_tier=AuthorityTier.NATIONAL_OFFICIAL, integration="adapter", access="credentials",
        auth_env=["MOSDAC_USERNAME", "MOSDAC_PASSWORD"], homepage="https://mosdac.gov.in/",
        docs_url="https://mosdac.gov.in/downloadapi-manual",
        license="MOSDAC data policy (registration required)",
        datasets=[
            DatasetDescriptor(id="oceansat3_ocm_chl", title="EOS-06 (Oceansat-3) OCM-3 chlorophyll", variables=["chlorophyll"],
                              kind=DataKind.ANALYSIS, spatial_resolution="~360 m", temporal_resolution="daily pass",
                              update_interval_s=86400, expected_latency_s=24 * 3600, coverage="Indian Ocean"),
            DatasetDescriptor(id="insat3d_sst", title="INSAT-3D/3DR imager SST", variables=["sst"], kind=DataKind.ANALYSIS,
                              spatial_resolution="4 km", temporal_resolution="30 min", update_interval_s=1800,
                              expected_latency_s=3600, coverage="Indian Ocean"),
            DatasetDescriptor(id="scatsat_winds", title="Scatterometer ocean surface winds", variables=["wind_speed"],
                              kind=DataKind.ANALYSIS, spatial_resolution="25 km", temporal_resolution="per pass",
                              update_interval_s=43200, expected_latency_s=6 * 3600, coverage="global"),
        ],
        notes=["Download API (mdapi.py) requires a registered MOSDAC account and dataset IDs; ORCA's adapter is ready to "
               "receive NetCDF granules but no granules are fetched without credentials."],
    )
    probe_url = "https://mosdac.gov.in/"

    def configured(self) -> bool:
        s = self.ctx.settings
        return bool(s.mosdac_username and s.mosdac_password)

    async def satellite_value(self, variable: str, bbox: BBox) -> tuple[Optional[dict], list[SourceFailure]]:
        if self.ctx.mode == DataMode.DEMO:
            try:
                r = await self._demo(f"{variable}", {"bbox": ",".join(f"{x:.2f}" for x in bbox.as_list())})
                return {"result": r, "data": r.data}, []
            except TransportError as e:
                return None, [self.failure(e, impact=f"MOSDAC {variable} excluded")]
        return None, [self._unavailable(f"MOSDAC {variable}")]


# ----------------------------------------------------------------------------- IMD
class IMD(_Restricted):
    descriptor = SourceDescriptor(
        id="imd", name="IMD (India Meteorological Department)", organization="India Meteorological Department, MoES",
        authority_tier=AuthorityTier.NATIONAL_OFFICIAL, integration="adapter", access="whitelist",
        auth_env=["IMD_API_KEY"], homepage="https://mausam.imd.gov.in/",
        docs_url="",
        license="IMD data policy; API access by IP whitelisting on request",
        datasets=[
            DatasetDescriptor(id="imd_marine_bulletin", title="Sea-area / coastal marine bulletins and fishermen warnings",
                              variables=["marine_warning"], kind=DataKind.ADVISORY, spatial_resolution="sea areas",
                              temporal_resolution="3–4 per day", update_interval_s=6 * 3600, expected_latency_s=3600,
                              coverage="North Indian Ocean"),
            DatasetDescriptor(id="imd_cyclone", title="RSMC New Delhi tropical cyclone advisories", variables=["cyclone"],
                              kind=DataKind.ADVISORY, spatial_resolution="track", temporal_resolution="3–6 hourly during events",
                              update_interval_s=3 * 3600, expected_latency_s=3600, coverage="North Indian Ocean"),
        ],
        notes=["IMD is the official Indian authority for weather and cyclone warnings. Its API is IP-whitelisted; a live "
               "probe from this deployment is rejected, so IMD evidence is excluded in LIVE mode and flagged as a gap."],
    )
    probe_url = "https://mausam.imd.gov.in/api/warnings_district_api.php?id=1"

    def configured(self) -> bool:
        return bool(self.ctx.settings.imd_api_key)

    async def marine_warnings(self, region_id: str) -> tuple[list[dict], Optional[Provenance], list[SourceFailure]]:
        if self.ctx.mode == DataMode.DEMO:
            try:
                r = await self._demo("marine_warnings", {"region": region_id})
                ds = self.dataset("imd_marine_bulletin")
                issued = None
                from ..core.clock import parse_utc
                if r.data.get("issued_at"):
                    issued = parse_utc(r.data["issued_at"])
                prov = self.provenance(ds=ds, variable="marine_warning", units="", res=r, issued_at=issued,
                                       timestamp=issued, has_data=True)
                return r.data.get("warnings", []), prov, []
            except TransportError as e:
                return [], None, [self.failure(e, impact="IMD marine warnings excluded")]
        return [], None, [self._unavailable("IMD marine warnings")]


# ----------------------------------------------------------------------------- INCOIS
class INCOIS(_Restricted):
    descriptor = SourceDescriptor(
        id="incois", name="INCOIS", organization="Indian National Centre for Ocean Information Services, MoES",
        authority_tier=AuthorityTier.NATIONAL_OFFICIAL, integration="adapter", access="none",
        auth_env=["INCOIS_PFZ_GEOJSON_URL", "INCOIS_OSF_JSON_URL"], homepage="https://incois.gov.in/",
        docs_url="",
        license="INCOIS data policy",
        datasets=[
            DatasetDescriptor(id="incois_pfz", title="Potential Fishing Zone advisories", variables=["pfz"],
                              kind=DataKind.ADVISORY, spatial_resolution="sector lines / polygons", temporal_resolution="daily (non-ban days)",
                              update_interval_s=86400, expected_latency_s=6 * 3600, coverage="Indian coastal waters"),
            DatasetDescriptor(id="incois_osf_hwa", title="Ocean State Forecast / High Wave & Swell Surge alerts",
                              variables=["ocean_state_alert"], kind=DataKind.ADVISORY, spatial_resolution="coastal sectors",
                              temporal_resolution="daily + event alerts", update_interval_s=86400, expected_latency_s=6 * 3600,
                              coverage="Indian coast"),
        ],
        notes=["INCOIS publishes PFZ and ocean-state advisories on its website / apps but no documented public machine API. "
               "Set INCOIS_PFZ_GEOJSON_URL / INCOIS_OSF_JSON_URL to an authorised feed to enable. ORCA's own productivity "
               "indicator is labelled 'ORCA-derived' and is never presented as an INCOIS PFZ."],
    )
    probe_url = "https://incois.gov.in/"

    def configured(self) -> bool:
        return bool(self.ctx.settings.incois_pfz_url or self.ctx.settings.incois_osf_url)

    def static_status(self) -> SourceStatus:
        return SourceStatus.UNKNOWN if self.configured() else SourceStatus.NO_PUBLIC_API

    async def pfz(self, bbox: BBox) -> tuple[list[dict], Optional[Provenance], list[SourceFailure]]:
        ds = self.dataset("incois_pfz")
        try:
            if self.ctx.mode == DataMode.DEMO:
                r = await self._demo("pfz", {"bbox": ",".join(f"{x:.2f}" for x in bbox.as_list())})
            elif self.ctx.settings.incois_pfz_url:
                r = await self.get(self.ctx.settings.incois_pfz_url, None, ttl_s=3600)
            else:
                return [], None, [self._unavailable("INCOIS PFZ advisory")]
        except TransportError as e:
            return [], None, [self.failure(e, impact="INCOIS PFZ advisory excluded")]
        feats = (r.data or {}).get("features", [])
        from ..core.clock import parse_utc
        issued = parse_utc(r.data["issued_at"]) if r.data.get("issued_at") else None
        prov = self.provenance(ds=ds, variable="pfz", units="", res=r, issued_at=issued, timestamp=issued, has_data=True)
        return feats, prov, []

    async def ocean_state_alerts(self, region_id: str) -> tuple[list[dict], Optional[Provenance], list[SourceFailure]]:
        ds = self.dataset("incois_osf_hwa")
        try:
            if self.ctx.mode == DataMode.DEMO:
                r = await self._demo("ocean_state", {"region": region_id})
            elif self.ctx.settings.incois_osf_url:
                r = await self.get(self.ctx.settings.incois_osf_url, {"region": region_id}, ttl_s=1800)
            else:
                return [], None, [self._unavailable("INCOIS ocean-state alerts")]
        except TransportError as e:
            return [], None, [self.failure(e, impact="INCOIS ocean-state alerts excluded")]
        from ..core.clock import parse_utc
        issued = parse_utc(r.data["issued_at"]) if r.data.get("issued_at") else None
        prov = self.provenance(ds=ds, variable="ocean_state_alert", units="", res=r, issued_at=issued,
                               timestamp=issued, has_data=True)
        return r.data.get("alerts", []), prov, []


# ----------------------------------------------------------------------------- others
class CopernicusMarine(_Restricted):
    descriptor = SourceDescriptor(
        id="copernicus_marine", name="Copernicus Marine Service (direct)", organization="Mercator Ocean International (EU Copernicus)",
        authority_tier=AuthorityTier.INTERGOVERNMENTAL, integration="adapter", access="credentials",
        auth_env=["COPERNICUSMARINE_SERVICE_USERNAME", "COPERNICUSMARINE_SERVICE_PASSWORD"],
        homepage="https://marine.copernicus.eu/", docs_url="https://help.marine.copernicus.eu/en/collections/9080063-copernicus-marine-toolbox",
        license="Copernicus Marine Service licence (free registration)",
        datasets=[
            DatasetDescriptor(id="GLOBAL_ANALYSISFORECAST_WAV_001_027", title="Global ocean waves analysis & forecast (MFWAM)",
                              variables=["wave_height"], kind=DataKind.FORECAST, spatial_resolution="1/12°",
                              temporal_resolution="3-hourly", update_interval_s=43200, coverage="global"),
            DatasetDescriptor(id="GLOBAL_ANALYSISFORECAST_PHY_001_024", title="Global ocean physics analysis & forecast",
                              variables=["sst", "salinity", "current_speed"], kind=DataKind.FORECAST,
                              spatial_resolution="1/12°", temporal_resolution="hourly/daily", update_interval_s=86400, coverage="global"),
        ],
        notes=["Direct Data Store access needs a (free) account and the copernicusmarine toolbox. ORCA currently receives the "
               "equivalent MFWAM / SMOC model output through Open-Meteo (see om_mfwam, om_smoc)."],
    )
    probe_url = "https://marine.copernicus.eu/"

    def configured(self) -> bool:
        s = self.ctx.settings
        return bool(s.copernicus_username and s.copernicus_password)


class ProtectedPlanet(_Restricted):
    descriptor = SourceDescriptor(
        id="protected_planet", name="Protected Planet (WDPA)", organization="UNEP-WCMC & IUCN",
        authority_tier=AuthorityTier.INTERGOVERNMENTAL, integration="adapter", access="credentials",
        auth_env=["PROTECTED_PLANET_TOKEN"], homepage="https://www.protectedplanet.net/",
        docs_url="https://api.protectedplanet.net/documentation",
        license="WDPA terms of use (no redistribution; non-commercial)",
        datasets=[DatasetDescriptor(id="wdpa_marine", title="World Database on Protected Areas — marine sites",
                                    variables=["protected_area"], kind=DataKind.REFERENCE, spatial_resolution="polygons",
                                    temporal_resolution="monthly release", update_interval_s=30 * 86400, coverage="global")],
        notes=["Without a token ORCA uses hand-digitised APPROXIMATE MPA outlines (clearly flagged) for geofencing."],
    )

    def configured(self) -> bool:
        return bool(self.ctx.settings.protected_planet_token)

    async def marine_protected_areas(self, iso3: str = "IND") -> tuple[list[dict], list[SourceFailure]]:
        if not self.configured():
            return [], [self._unavailable("WDPA marine protected areas")]
        try:
            r = await self.get("https://api.protectedplanet.net/v3/protected_areas/search",
                               {"token": self.ctx.settings.protected_planet_token, "country": iso3, "marine": "true",
                                "with_geometry": "true", "per_page": 50}, ttl_s=7 * 86400, timeout_s=60)
            return r.data.get("protected_areas", []), []
        except TransportError as e:
            return [], [self.failure(e, impact="WDPA polygons unavailable; approximate outlines used")]


class NasaOceanColor(_Restricted):
    descriptor = SourceDescriptor(
        id="nasa_oceancolor", name="NASA OceanColor (OB.DAAC)", organization="NASA GSFC Ocean Biology DAAC",
        authority_tier=AuthorityTier.NATIONAL_AGENCY_FOREIGN, integration="adapter", access="credentials",
        auth_env=["EARTHDATA_TOKEN"], homepage="https://oceancolor.gsfc.nasa.gov/",
        docs_url="https://oceancolor.gsfc.nasa.gov/",
        license="NASA open data (Earthdata login required for downloads)",
        datasets=[DatasetDescriptor(id="pace_oci_l3m_chl", title="PACE OCI L3 mapped chlorophyll", variables=["chlorophyll"],
                                    kind=DataKind.ANALYSIS, spatial_resolution="4 km", temporal_resolution="daily / 8-day",
                                    update_interval_s=86400, expected_latency_s=48 * 3600, coverage="global")],
        notes=["Granule downloads need Earthdata login. ORCA uses NASA GIBS tiles (visual) and NOAA CoastWatch VIIRS "
               "chlorophyll (numeric) instead."],
    )
    probe_url = "https://oceancolor.gsfc.nasa.gov/"

    def configured(self) -> bool:
        return bool(self.ctx.settings.earthdata_token)


class Bhuvan(_Restricted):
    descriptor = SourceDescriptor(
        id="bhuvan", name="Bhuvan (NRSC)", organization="National Remote Sensing Centre, ISRO",
        authority_tier=AuthorityTier.NATIONAL_OFFICIAL, integration="adapter", access="credentials",
        auth_env=["BHUVAN_TOKEN"], homepage="https://bhuvan.nrsc.gov.in/",
        docs_url="https://bhuvan-app1.nrsc.gov.in/api/", license="Bhuvan terms of use",
        datasets=[DatasetDescriptor(id="bhuvan_coastal", title="Coastal zone / shoreline thematic layers (WMS)",
                                    variables=["coastal_layers"], kind=DataKind.REFERENCE, spatial_resolution="1:50k–1:250k",
                                    temporal_resolution="periodic", coverage="India")],
        notes=["Bhuvan APIs issue per-user tokens; thematic WMS layers can be added to the map once a token is configured."],
    )
    probe_url = "https://bhuvan.nrsc.gov.in/"

    def configured(self) -> bool:
        return bool(self.ctx.settings.bhuvan_token)


class CMFRI(_Restricted):
    descriptor = SourceDescriptor(
        id="cmfri", name="CMFRI", organization="ICAR – Central Marine Fisheries Research Institute",
        authority_tier=AuthorityTier.NATIONAL_OFFICIAL, integration="adapter", access="none",
        homepage="https://www.cmfri.org.in/", docs_url="https://eprints.cmfri.org.in/",
        license="Publications (various)",
        datasets=[DatasetDescriptor(id="cmfri_landings", title="Marine fish landings estimates (annual)",
                                    variables=["landings"], kind=DataKind.HISTORICAL, spatial_resolution="state",
                                    temporal_resolution="annual", coverage="India")],
        notes=["Published as reports; no API. Could inform species-season priors for the fisheries agent in future."],
    )
    probe_url = "https://www.cmfri.org.in/"

    def configured(self) -> bool:
        return False


# ----------------------------------------------------------------------------- static reference sources
class StaticReference(Connector):
    def __init__(self, ctx, descriptor: SourceDescriptor):
        super().__init__(ctx)
        self.descriptor = descriptor

    async def probe(self) -> dict:
        return {"status": "STATIC", "detail": "bundled reference data (see data/reference/manifest.json)"}


REFERENCE_DESCRIPTORS = [
    SourceDescriptor(
        id="marine_regions", name="Marine Regions (VLIZ)", organization="Flanders Marine Institute (VLIZ)",
        authority_tier=AuthorityTier.SCIENTIFIC_COMPILATION, integration="reference", access="public",
        homepage="https://www.marineregions.org/", docs_url="https://www.marineregions.org/webservices.php",
        license="CC-BY 4.0",
        datasets=[DatasetDescriptor(id="eez_v12", title="EEZ polygons and maritime boundaries",
                                    variables=["eez", "maritime_boundary"], kind=DataKind.REFERENCE,
                                    spatial_resolution="vector (simplified 0.01°)", temporal_resolution="static release",
                                    coverage="global")],
        notes=["Compiled dataset; not an official legal delimitation."]),
    SourceDescriptor(
        id="natural_earth", name="Natural Earth", organization="Natural Earth (NACIS)",
        authority_tier=AuthorityTier.SCIENTIFIC_COMPILATION, integration="reference", access="public",
        homepage="https://www.naturalearthdata.com/", license="Public domain",
        datasets=[DatasetDescriptor(id="ne_10m_land", title="1:10m land and minor islands", variables=["land"],
                                    kind=DataKind.REFERENCE, spatial_resolution="1:10m (simplified 0.004°)",
                                    temporal_resolution="static", coverage="global")],
        notes=["Used as the land mask for routing and offshore projection."]),
    SourceDescriptor(
        id="orca_curated", name="ORCA curated zones & gazetteer", organization="ORCA prototype",
        authority_tier=AuthorityTier.ORCA_CURATED, integration="reference", access="public",
        license="ORCA prototype data",
        datasets=[DatasetDescriptor(id="curated_zones", title="Approximate MPAs, restricted areas, seasonal fishing restrictions, ports",
                                    variables=["protected_area", "restricted_area", "regulation", "port"],
                                    kind=DataKind.REFERENCE, spatial_resolution="approximate polygons",
                                    temporal_resolution="static", coverage="India")],
        notes=["APPROXIMATE — hand-digitised for prototype geofencing; not legal boundaries."]),
]
