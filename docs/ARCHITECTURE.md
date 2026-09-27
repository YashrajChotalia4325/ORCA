# ORCA architecture

## 1. System overview

```
                         ┌──────────────────────────── apps/web (Next.js 16, MapLibre v6) ─────────────────────────────┐
                         │ Landing · Judge · Command · Live Ocean · Ask · Fishing · Safety · Route · Research ·         │
                         │ Sources · Agents · Evidence · Health · Eval        (SSE: live agent trace, alert stream)      │
                         └───────────────▲──────────────────────────────▲───────────────────────────────────────────────┘
                                         │ REST + SSE                   │ GIBS WMTS tiles (direct, real dates)
┌────────────────────────────────────────┴──── apps/api (FastAPI) ─────┴─────────────────────────────────────────────────┐
│  api/routes.py  ── security (bearer roles, rate limit) ── request context (no query strings logged)                    │
│                                                                                                                        │
│  orchestrator.py ──► graph.py (LangGraph StateGraph): understand → plan → Send-fan-out waves → join → review → visualize│
│        ▲                 │                                               │                                            │
│        │   re-plan rules │ RP1 missing data · RP2 conflict · RP3 cyclone · RP4 protected-area route                 │
│        │                 ▼                                               ▼                                            │
│   ┌─────────────────────────────────────── BLACKBOARD (typed, per query) ───────────────────────────────────────┐   │
│   │ understanding · plan · agents{task→record} · outputs{agent→typed JSON} · evidence · claims · conflicts ·     │   │
│   │ failures · risk · route · alerts · final_assessment · response · map directive · events (trace) · timings    │   │
│   └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘   │
│   Agents: geospatial · ocean · weather · satellite · advisory · fisheries · hazard · route · research ·               │
│           evidence · communication · alert  (+ planner)                                                              │
│                                                                                                                        │
│  Deterministic core (no LLM):  core/spatial · core/routing · core/risk · core/confidence · core/freshness ·          │
│                                core/temporal · core/units · reasoning/conflicts · reasoning/fisheries · reasoning/research│
│  Optional LLM (Claude):        reasoning/llm.py — interpretation fallback + narration behind a numeric grounding guard │
│                                                                                                                        │
│  connectors/  ─ Transport (LIVE: httpx + TTL cache + request coalescing + retries + circuit breaker + stale-if-error │
│               │             REPLAY: recorded responses · DEMO: synthetic scenario responder)                         │
│               ├ Open-Meteo model connectors (9) · NOAA CoastWatch ERDDAP · GDACS · GEBCO · NASA GIBS                  │
│               └ adapters: MOSDAC · IMD · INCOIS · Copernicus Marine · Protected Planet · NASA OceanColor · Bhuvan · CMFRI│
│  geo/reference.py — land mask, EEZ, maritime boundaries, zones (MPA/restricted/seasonal), gazetteer, user geofences  │
│  monitor.py — proactive scan → verify (full pipeline) → alerts → SSE                                                  │
│  store/db.py — SQLite (queries+traces, agent runs, alerts, geofences, watches, eval runs); PostGIS schema in infra/  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. The agent graph (LangGraph)

`apps/api/orca/graph.py` compiles one graph at import time and every query invokes it:

```
START → understand ─┬→ clarify ─────────────────────────────────────┐
                    └→ plan ─dispatch→ Send(agent, task) ×N ─→ join ─┤ (loop while tasks are ready)
                                          ▲                     │    │
                                          └──── dispatch ◄──────┘    │
                         join ─(plan exhausted)→ review ─(RP1–RP4 added tasks)→ Send(...) ×N
                                                        └─(nothing to add / round cap 3)→ visualize → END
```

* **Nodes** — `understand`, `clarify`, `plan`, `review` (planner phases), `join` (barrier), `visualize`,
  and one node per specialised agent (12).
* **Dynamic fan-out** — the planner's `ExecutionPlan` is a dependency DAG that differs per intent. The `dispatch`
  router returns a `Send(<agent>, {task_id, wave})` for every task whose dependencies are complete; LangGraph runs
  them concurrently in one superstep and `join` runs once they have all finished. One superstep = one DAG wave.
* **State** — graph channels hold only scheduling state (`completed` task ids merged by an `operator.add` reducer,
  `round`, `superstep`, `clarify`). The heavy per-query `RunState` (typed Blackboard, LIVE/REPLAY/DEMO execution
  context, SSE event bus) is passed as LangGraph *runtime context* (`context_schema=OrcaContext`).
* **Re-planning** — `review` applies RP1–RP4; new tasks re-enter through the same `Send` mechanism, max 3 rounds.
* **Failure isolation** — each agent node wraps its agent in a timeout and catches every exception, so a failed
  agent becomes a `FAILED` record, never a crashed graph.
* **Observability** — waves are stored as `blackboard.supersteps` and streamed as `dispatch` events.

## 3. Reasoning pipeline (visible in the UI dock as 16 stages)

`INTENT → LOCATION_TIME → PLANNING → AGENT_SELECTION → RETRIEVAL → NORMALIZATION → ALIGNMENT → CORRELATION →
CONFLICTS → REASONING → VERIFICATION → CONFIDENCE → DECISION → EXPLANATION → VISUALIZATION → RESPONSE`

Each stage is emitted as a trace event by the agent that performs it; every tool call, source response,
re-plan, conflict and alert is also an event. The whole trace is stored with the blackboard and addressable by
a trace ID of the form `ORCA-YYYY-MM-DD-XXXXX`.

## 4. Why these technology choices

| Need | Choice | Reason / alternative rejected |
|---|---|---|
| Agent orchestration | LangGraph `StateGraph` (one node per agent, `Send` fan-out per DAG wave, conditional edges for re-planning) over a typed blackboard | Parallel supersteps with a join barrier, conditional routing and a compiled, inspectable topology (`GET /api/agents/graph`) without hand-written scheduling. The plan itself stays deterministic Python, so LangGraph schedules but never decides. |
| Schemas | Pydantic v2 | Typed agent outputs, JSON-schema published at `/api/agents`. |
| Geometry | shapely 2 (vectorised) + pyproj local AEQD projections | Exact metric distances, point-in-polygon, route∩zone — PostGIS-equivalent operations without a DB dependency for the prototype. PostGIS schema is provided for production. |
| Routing | own time-dependent A* on a land-masked grid | Needs a risk cost that depends on ETA; off-the-shelf road routers don't apply at sea. |
| Store | SQLite | Zero-ops for a demo; same logical model as `infra/postgis/schema.sql`. |
| Cache / queue | in-process TTL cache, request coalescing, asyncio monitor | Redis/Celery would add ops without benefit at this scale. |
| Realtime | Server-Sent Events | One-directional agent traces and alert streams; simpler than WebSockets. |
| Map | MapLibre GL v6, basemap from bundled Natural Earth land | No API keys, no licence ambiguity; real NASA GIBS imagery as overlays. |
| LLM | Anthropic Claude (optional, `claude-opus-5`, server-side refusal fallbacks) | Only for interpretation fallback and phrasing; numbers are guarded. The system is fully functional without it. |

## 5. Modes and the transport seam

Connectors build requests and parse responses; the transport underneath decides where bytes come from.
This is how LIVE, REPLAY and DEMO run the *same* agents:

* **LiveTransport** — httpx client, TTL cache (per-source TTLs), concurrent-request coalescing, 2 retries
  with back-off for timeouts/5xx/429, per-source circuit breaker (opens after 3 failures, half-opens after 60 s),
  stale-if-error fallback (≤ 24 h, labelled), optional recorder.
* **ReplayTransport** — looks up the canonical request key in a recorded snapshot; unknown requests fail with
  `NOT_IN_RECORDING` (never fabricated). The clock is fixed to the recording time.
* **DemoTransport** — a scenario responder generates responses in the upstream formats (Open-Meteo JSON,
  ERDDAP griddap tables, GDACS GeoJSON, OpenTopoData) from a physically-motivated synthetic environment, and
  injects outages. Freshness status is always `SIMULATED`.

## 6. Data model (SQLite today, PostGIS target)

| Table | Content |
|---|---|
| `queries` | query/trace ids, conversation, mode, intent, role, language, decision, confidence, coarse location (0.1°), timings, LLM tokens, full blackboard JSON |
| `agent_runs` | per task: agent, status, duration, round, failures |
| `alerts` | alert body, severity, category, verified flag, dedup key, mode, status |
| `geofences`, `watches` | user geofence rings; vessel/point watches for the monitor |
| `eval_runs` | evaluation summaries and per-case results |

The PostGIS schema adds `ref_zone`, `ref_place`, `source`, `source_health`, `observation`, `claim`,
`evidence_item` with GiST indexes (see `infra/postgis/schema.sql`).

## 7. Security

Bearer-token roles (`ORCA_API_TOKENS`), optional mandatory auth (`ORCA_AUTH_REQUIRED`), admin-only evaluation and
probe endpoints when auth is on, token-bucket rate limiting on expensive endpoints, Pydantic input validation
(query length, coordinate ranges, geofence rings), secrets only from environment variables and stripped from
recorded URLs, CORS allow-list, `X-Content-Type-Options: nosniff`, request logging without query strings, stored
locations rounded to 0.1° unless `ORCA_STORE_PRECISE_LOCATION=true`. See [SAFETY.md](SAFETY.md).
