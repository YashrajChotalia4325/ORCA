# API

Base URL `http://localhost:8000`. Interactive OpenAPI docs at `/docs`. Mode selection: query parameter
`mode=LIVE|REPLAY|DEMO` (+ `scenario=<id>` for DEMO) or `mode` in the request body. Auth: `Authorization: Bearer <token>`
when `ORCA_AUTH_REQUIRED=true`.

## Query pipeline
| Method | Path | Description |
|---|---|---|
| POST | `/api/query` | Start the multi-agent pipeline. Body `QueryRequest {text, conversation_id?, role?, language?, mode?, vessel_class?, location?, speed_kn?}`. Returns `{query_id, trace_id, conversation_id, events_url, result_url}`; `?wait=true` returns the full blackboard. |
| GET | `/api/query/{id}` | Full blackboard (query id or trace id). |
| GET | `/api/query/{id}/events` | **SSE** stream of trace events (`start, stage, plan, agent_start, tool, replan, conflict, evidence, alert, agent_end, done`). |
| GET | `/api/query/{id}/agents` | Plan + agent records. |
| GET | `/api/query/{id}/evidence` | Claims, evidence items, conflicts, failures, final assessment. |
| GET | `/api/traces?limit=` | Recent traces. |

## Data
| Method | Path | Description |
|---|---|---|
| GET | `/api/ocean?lat&lon&hours` | Multi-model waves / swell / currents / model SST series with provenance. |
| GET | `/api/waves?lat&lon&hours` | Multi-model wave height. |
| GET | `/api/weather?lat&lon&hours` | Multi-model wind, gusts, rain, CAPE, visibility, pressure. |
| GET | `/api/satellite?lat&lon` | Satellite SST, SST anomaly, chlorophyll at nearest valid pixel. |
| GET | `/api/fisheries?lat&lon` | Runs the fishing-zone pipeline; returns zones + assessment. |
| POST | `/api/route/analyze` | `{origin, destination (place id/name or {lat,lon}), departure?, vessel_class, speed_kn?, mode?, scenario?}` → query ids (follow via SSE). |
| GET | `/api/boundaries` | Land, EEZ, maritime boundaries, zones, ports (GeoJSON) + provenance. |
| GET | `/api/map/layers` | GIBS layers with latest real dates, ORCA field layers, vector layers, basemaps. |
| GET | `/api/map/field?layer=waves|wind|currents&res=` | Sea-point forecast grid (48 h) with provenance. |
| GET | `/api/map/cyclones` | GDACS cyclone features. |

## Geofencing & alerts
| Method | Path | Description |
|---|---|---|
| GET / POST / DELETE | `/api/geofences[/{id}]` | User geofence polygons (used by geospatial, route and monitor). |
| GET | `/api/alerts?mode&status&limit` | Alert centre. |
| POST | `/api/alerts` | Register a point/vessel watch `{name, lat, lon, radius_km, vessel_class}`. |
| GET | `/api/alerts/watches` | Active watches. |
| POST | `/api/alerts/{id}/ack` | Acknowledge. |
| POST | `/api/alerts/scan?mode&scenario` | Run one monitoring cycle now. |
| GET | `/api/alerts/stream` | **SSE** stream of new alerts. |

## System
| Method | Path | Description |
|---|---|---|
| GET | `/api/agents` | Agent catalogue with tools and output JSON schemas. |
| GET | `/api/agents/graph` | Compiled LangGraph topology: nodes, edges (conditional flag) and Mermaid source. |
| GET | `/api/sources[?probe=true]` | Every source: access, status, datasets, health, latest probe. |
| POST | `/api/sources/probe` | Probe all sources (admin when auth on). |
| GET | `/api/system/health` | Uptime, sources, agent stats, query stats, HTTP/cache metrics, LLM usage, monitor, snapshots. |
| GET | `/api/system/mode` | Modes, snapshots, scenarios. |
| GET | `/api/demo/scenarios` | DEMO scenarios. |
| POST | `/api/demo/scenarios/{id}/activate` | Run a monitor cycle inside a scenario (demo alerts). |
| POST | `/api/eval/run` · GET `/api/eval/latest` | Evaluation suite. |

## Example
```bash
curl -s -X POST "http://localhost:8000/api/query?wait=true&mode=DEMO&scenario=conflicting_sources" -H "content-type: application/json" -d "{\"text\": \"Is it safe to fish 25 km off Chennai tomorrow morning?\"}"
```
