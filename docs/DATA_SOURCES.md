# Data sources

All access statuses below were verified from this deployment on **26 Sep 2026** (probes are repeated every
10 minutes and shown live on the **Sources** page). Every datum ORCA uses carries a `Provenance` record:
`source, source_id, organization, distributor, authority_tier, dataset, variable, kind, timestamp (valid),
issued_at (model run / bulletin), retrieval_timestamp, spatial_resolution, temporal_resolution, units,
geographic_extent, freshness{status,label,factor}, confidence (authority weight), source_url (secrets stripped),
license, status, mode, notes`.

Data kinds are never mixed: `OBSERVED`, `ANALYSIS` (satellite-derived gridded), `FORECAST`, `ADVISORY`,
`HISTORICAL`, `REFERENCE`, `DERIVED` (ORCA-computed).

## 1. Live integrations

### Open-Meteo model connectors (redistributors of official NWP / wave-model output)
Open-Meteo (CC-BY 4.0, no key, ~10 000 calls/day non-commercial; multi-location requests count per location)
redistributes model output. ORCA exposes **each model as its own source** so cross-model agreement can be
measured and one model's outage never hides the others. Model-run initialisation and availability times come
from `/data/<model>/static/meta.json` and drive the freshness engine.

| ORCA id | Model / producer | Variables | Grid | Step | Updates |
|---|---|---|---|---|---|
| `om_mfwam` | Météo-France MFWAM (the model behind the Copernicus Marine global wave forecast) | Hs, direction, period, wind-sea, swell | 0.08° | 3 h | 12 h |
| `om_ecmwf_wam` | ECMWF WAM | same | 0.25° | 3 h | 6 h |
| `om_gfs_wave` | NOAA NCEP GFS-Wave (WAVEWATCH III) | same | 0.25° | 1 h | 6 h |
| `om_smoc` | Météo-France / Mercator SMOC (Copernicus Marine distributed) | surface current speed/direction, model SST | 0.08° | 1 h | 24 h |
| `om_ecmwf_ifs` | ECMWF IFS | wind, gusts, rain, MSLP, CAPE, weather code | 0.25° | 3 h | 6 h |
| `om_gfs` | NOAA GFS | + visibility | 0.25° | 1 h | 6 h |
| `om_icon` | DWD ICON | wind, gusts, rain, MSLP, CAPE | 0.125° | 1 h | 6 h |
| `om_dwd_gwam` | DWD GWAM — **tie-breaker only** | waves | 0.25° | 3 h | 12 h |
| `om_ukmo` | UK Met Office global — **tie-breaker only** | wind, gusts, rain, MSLP | ~10 km | 1 h | 6 h |

Processing: request per model (3 days, 1 past day), parse hourly series, convert to canonical units (m, s,
km/h, °C, mm/h, J/kg, km), attach provenance with run times. Land cells return null for marine models and are
reported as *no data*, never filled. Limitation: Open-Meteo is a redistributor; ORCA reports the producing
agency and the distributor separately. Direct Copernicus Marine Data Store access needs an account (see §2).

### NOAA CoastWatch ERDDAP (`noaa_coastwatch`) — satellite analyses
Public domain, no key. Griddap subsetting with strides; index arithmetic `[last-N:1:last]` for time series so
requests always fall inside product coverage.

| Product | Dataset id | Resolution | Cadence / latency |
|---|---|---|---|
| Geo-polar Blended SST (day+night, GHRSST L4) | `noaacwBLENDEDsstDNDaily` | 0.05° | daily, ~1.5–2 days |
| Coral Reef Watch SST anomaly | `noaacrwsstanomalyDaily` | 0.05° | daily |
| VIIRS S-NPP/NOAA-20 chlorophyll-a, DINEOF gap-filled (NRT) | `noaacwNPPN20VIIRSDINEOFDaily` | 9 km | daily |

Used for: point context, SST-front detection, chlorophyll co-location, research time series. Limitations:
daily analyses are 1–2 days old — ORCA labels them as such and never as real-time observations; chlorophyll is
statistically reconstructed under cloud (DINEOF), which the research agent lists as a hypothesis (H3).

### NASA GIBS (`nasa_gibs`) — imagery for the map only
WMTS tiles with a TIME dimension; the capabilities document is parsed to find the latest date that actually
exists for each layer: VIIRS NOAA-20 true colour, GHRSST MUR SST and anomaly, PACE OCI chlorophyll-a, GPM
IMERG rain rate, Blue Marble relief. **ORCA never reads numbers from tiles**; the time slider can only select
dates that exist, and shows "latest available" when asked for the future.

### GDACS (`gdacs`) — tropical cyclone advisories
UN OCHA / EC JRC; public. Event list for the North Indian Ocean AOI, then per-event geometry: 6-hourly track
points, wind-radius polygons (63 / 93 / 119 km/h), uncertainty cone. An event is **active** only if its last
advisory is < 24 h old (e.g. "ONE-26", Orange, 22–24 Sep 2026 is correctly treated as inactive on 26 Sep).
Track source is usually JTWC. GDACS is an international advisory, not the Indian national warning (IMD).

### GEBCO 2020 via OpenTopoData (`gebco`)
Point bathymetry (15″ grid). 1 call/s, 100 points/call, ~1 000 calls/day on the public service; ORCA
serialises calls and caches for 30 days. Static reference (`STATIC` freshness).

## 2. Authoritative sources not machine-accessible from this deployment

Each has an adapter with the method signatures the agents call; they activate when configured, and are
otherwise listed under *excluded sources* in every answer.

| Source | What it would add | Status found | How to enable |
|---|---|---|---|
| **IMD** (RSMC New Delhi) | official fishermen / sea-area warnings, cyclone bulletins | API responds *"IP … needs to be whitelisted"* (HTTP 401/403) | request IP whitelisting; set `IMD_API_KEY` |
| **INCOIS** | official PFZ advisories, Ocean State Forecast, high-wave / swell-surge alerts | website reachable; no documented public machine API | provide authorised feeds via `INCOIS_PFZ_GEOJSON_URL`, `INCOIS_OSF_JSON_URL` |
| **MOSDAC** (ISRO SAC) | INSAT-3D/3DR SST, Oceansat-3 OCM chlorophyll, scatterometer winds | download API requires registered account | `MOSDAC_USERNAME`, `MOSDAC_PASSWORD` |
| **Copernicus Marine** (direct) | GLO wave & physics analysis/forecast | free account + toolbox required | `COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD` (MFWAM/SMOC already used via Open-Meteo) |
| **Protected Planet (WDPA)** | legal protected-area polygons | token required; WDPA terms forbid redistribution | `PROTECTED_PLANET_TOKEN` |
| **NASA OceanColor** | PACE L3 chlorophyll numbers | Earthdata login | `EARTHDATA_TOKEN` (GIBS + NOAA VIIRS used instead) |
| **Bhuvan** (NRSC) | coastal thematic layers | per-user token | `BHUVAN_TOKEN` |
| **CMFRI** | landing statistics | publications only, no API | — |

## 3. Reference data (bundled, provenance in `data/reference/manifest.json`)

| Layer | Source | Licence | Processing |
|---|---|---|---|
| Land & islands (land mask, basemap) | Natural Earth 1:10m land + minor islands | public domain | clipped to 60–100°E, 5°S–30°N; simplified 0.004° |
| EEZs (India + neighbours) | Marine Regions EEZ v12 (VLIZ) | CC-BY 4.0 | clipped, simplified 0.01° |
| Maritime boundaries | Marine Regions `eez_boundaries` (treaty, median, court ruling, 200 NM) | CC-BY 4.0 | straight baselines excluded from proximity alerts |
| Protected / restricted / seasonal zones | **ORCA-curated, APPROXIMATE** outlines (Gulf of Mannar MNP, Gulf of Kutch MNP, Malvan MS, Gahirmatha MS, Wandoor MNP, Bombay High, west/east-coast monsoon bans, Odisha olive-ridley restriction) | prototype | land subtracted; flagged approximate everywhere |
| Gazetteer | 64 coastal places + 15 regions with local-language names | prototype | names machine-authored — need native review |

Marine Regions notes that its boundaries are a compilation and not legal delimitations; ORCA repeats this.
