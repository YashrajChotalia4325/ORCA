# ORCA — Ocean & Marine Reasoning with Collaborative Agents

**Smart India Hackathon 2026 · SIH26176 · Space Technology · Software**

> *Ask the Ocean. ORCA Reasons.* — an agentic marine intelligence system that turns live Earth observation,
> oceanographic and geospatial data into explainable decisions for fishermen, coastal authorities,
> researchers and maritime operators.

ORCA is **not** a chatbot with a map. A planner decomposes each question into a dependency graph of tasks for
13 specialised agents that share a typed blackboard. Agents retrieve **real, currently published** data from
multiple independent sources, align it in space and time over the whole trip or route, detect disagreement
between sources, apply a **deterministic** risk model, compute a **documented** confidence score, and render the
same verified result for different audiences in 8 Indian languages + English. Every number shown carries its
source, dataset, valid time, model-run time, retrieval time and freshness status.

```
RAW LIVE MARINE DATA → MULTI-AGENT COLLABORATION → SPATIAL-TEMPORAL REASONING
                     → EVIDENCE VERIFICATION → RISK ANALYSIS → EXPLAINABLE DECISION → ACTION
```

## What is genuinely live (verified 26 Sep 2026 from this deployment)

| Source | Data | Access |
|---|---|---|
| Météo-France **MFWAM**, **ECMWF WAM**, **NOAA GFS-Wave** (via Open-Meteo) | waves, swell, wave period | public, no key · model-run times from `meta.json` |
| Météo-France / Mercator **SMOC** (via Open-Meteo) | surface currents, model SST | public |
| **ECMWF IFS**, **NOAA GFS**, **DWD ICON** (via Open-Meteo) | wind, gusts, rain, pressure, CAPE, visibility | public |
| DWD GWAM, UK Met Office global | tie-breaker models used only on conflict / failure | public |
| **NOAA CoastWatch ERDDAP** | Geo-polar blended SST (5 km), Coral Reef Watch SST anomaly, VIIRS chlorophyll-a (9 km) | public |
| **NASA GIBS** | MUR SST, PACE chlorophyll, IMERG rain, VIIRS true colour tiles with real dates | public |
| **GDACS** (UN OCHA / EC JRC) | tropical cyclones: tracks, wind radii, cones | public |
| **GEBCO 2020** (via OpenTopoData) | bathymetry | public |
| **Marine Regions** (VLIZ), **Natural Earth** | EEZs, maritime boundaries, land mask | bundled reference |

**Not machine-accessible from here — adapters built, status reported honestly, excluded from answers:**
IMD (API returns *"IP needs to be whitelisted"*), MOSDAC/ISRO (account + token), INCOIS PFZ / ocean-state
(no documented public API), Copernicus Marine direct (account), Protected Planet WDPA (token),
NASA OceanColor downloads (Earthdata login), Bhuvan (token), CMFRI (publications only). Details: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Modes — ORCA never labels simulated or recorded data as live

| Mode | Data | Labelling |
|---|---|---|
| **LIVE** | only real external data | freshness per datum: LIVE / RECENT / STALE / UNAVAILABLE |
| **REPLAY** | real responses recorded by `scripts/record_replay.py`, replayed with original timestamps | REPLAY everywhere; clock fixed to recording time |
| **DEMO** | 9 synthetic scenarios served in the *exact upstream API formats*, so the real agents run unmodified | SIMULATED everywhere + striped banner |

## Quick start

Prerequisites: Python 3.11+, Node 20.9+.

```bash
python -m venv .venv
```
```bash
.venv/Scripts/pip install -r apps/api/requirements-dev.txt      # Linux/macOS: .venv/bin/pip
```
```bash
.venv/Scripts/python -m uvicorn orca.main:app --app-dir apps/api --port 8000
```
```bash
cd apps/web && npm install && npm run dev
```

Open <http://localhost:3000> → **Judge mode** for the guided demonstration, or **Ask ORCA**.
API docs: <http://localhost:8000/docs>. Docker: `docker compose up --build` (add `--profile postgis` for the PostGIS service).

Reference geodata is bundled; to refresh it from its publishers run `scripts/fetch_reference_data.py`.
To record a new REPLAY snapshot from live sources run `scripts/record_replay.py`.

## Tests & evaluation

```bash
cd apps/api && ../../.venv/Scripts/python -m pytest -q
```

85 tests cover geodesy, point-in-polygon/geofencing, offshore projection, freshness rules, temporal
resolution (8 languages), unit conversion, risk rules, confidence behaviour, conflict detection, A* routing,
adapters that must never fabricate data, record/replay, the hallucination guard and every DEMO scenario
end-to-end. The evaluation suite (100 queries + 14 end-to-end runs) is in the console under **Eval** and in
[docs/EVALUATION.md](docs/EVALUATION.md).

## Repository layout

```
apps/api/orca/            FastAPI service (Python)
  core/                   schemas · freshness · confidence · risk model · routing · spatial · temporal · units · clock
  connectors/             transports (live/replay/demo) · Open-Meteo models · ERDDAP · GDACS · GEBCO · GIBS · restricted adapters
  agents/                 13 agents (planner, geospatial, ocean, weather, satellite, advisory, fisheries, hazard,
                          route, research, evidence, communication, alert)
  reasoning/              NLU + multilingual lexicon · conflicts · fisheries fronts · research statistics · i18n · LLM layer
  geo/                    reference store (land, EEZ, boundaries, zones, gazetteer, geofences)
  demo/                   synthetic environment + 9 scenarios
  evaluation/             100-query dataset + runner
  graph.py                LangGraph StateGraph: one node per agent, Send fan-out waves, re-plan loop
  orchestrator.py monitor.py runtime.py main.py api/ store/ services/
apps/api/tests/           pytest suite
apps/web/                 Next.js 16 + TypeScript + Tailwind v4 + MapLibre GL v6 console
data/reference/           Natural Earth land, Marine Regions EEZ/boundaries, curated zones, gazetteer (+ manifest)
data/replay/              recorded real snapshots
infra/postgis/schema.sql  production PostGIS data model
scripts/                  reference-data fetcher, replay recorder
docs/                     architecture, sources, agents, reasoning, safety, API, demo, evaluation, limitations
```

## Documentation

[ARCHITECTURE](docs/ARCHITECTURE.md) · [DATA_SOURCES](docs/DATA_SOURCES.md) · [AGENTS](docs/AGENTS.md) ·
[REASONING](docs/REASONING.md) · [SAFETY](docs/SAFETY.md) · [API](docs/API.md) · [DEMO](docs/DEMO.md) ·
[EVALUATION](docs/EVALUATION.md) · [LIMITATIONS](docs/LIMITATIONS.md)

## Important

ORCA is a **decision-support prototype, not an official authority**. It is not endorsed by ISRO, INCOIS, IMD or
any other organisation. Official warnings always take precedence. Risk thresholds are ORCA defaults that have
not been validated by a marine authority, and protected-area outlines marked *approximate* are not legal boundaries.
