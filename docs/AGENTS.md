# Agents

13 agents with distinct responsibilities, tools and typed outputs. They never exchange free text: each writes
a Pydantic model to the blackboard (`outputs.<agent>`) and keeps rich in-memory objects (series, grids) for
downstream agents. Every run records status, duration, tools, sources, failures and warnings
(`AgentRecord`). The catalogue with JSON output schemas is served at `GET /api/agents`.

Each specialised agent is a node in a LangGraph `StateGraph` (`orca/graph.py`); the planner's phases are the
`understand`, `plan` and `review` nodes. The compiled topology is served at `GET /api/agents/graph`
(see [ARCHITECTURE.md §2](ARCHITECTURE.md)).

| # | Agent | Responsibility | Key tools | Output |
|---|---|---|---|---|
| 1 | **Planner / Orchestrator** | NLU (deterministic; LLM fallback when confidence < 0.5), location & exact IST/UTC window, task DAG, agent selection, re-planning | `nlu.parse`, `temporal.resolve`, `gazetteer.match`, `llm.interpret`, `plan.build_dag`, `plan.review` | `Understanding`, `ExecutionPlan` |
| 2 | **Satellite / EO** | satellite SST, SST anomaly, chlorophyll-a: point values, product times, latency, resolution; research time series; MOSDAC adapter | `noaa_coastwatch.point/grid/region_series`, `mosdac.satellite_value` | `SatelliteOutput` |
| 3 | **Oceanography** | waves, swell, period, currents, model SST from MFWAM, ECMWF WAM, GFS-Wave, SMOC; point or gridded mode; DWD GWAM tie-breaker | `om_*.points`, `openmeteo.run_info` | `RetrievalOutput` (+ series / fields) |
| 4 | **Weather** | wind, gusts, rain, MSLP, CAPE, visibility from ECMWF IFS, GFS, ICON; history mode for research; UK Met Office tie-breaker | `om_*.points` | `RetrievalOutput` |
| 5 | **Fisheries** | INCOIS PFZ (adapter) + ORCA productivity indicator (SST fronts × chlorophyll), zone clustering, depth | `incois.pfz`, `fronts.gradient_analysis`, `fronts.cluster`, `gebco.depth` | `FisheriesOutput` (probabilistic, labelled) |
| 6 | **Geospatial / Boundary** | place → sea point (offshore projection), sampling design (trip transect, rings, coastal stations, route end-points, analysis boxes), EEZ, distance to coast, depth, maritime boundaries, MPAs, restricted & seasonal zones, geofences | `spatial.*`, `marine_regions.eez_lookup`, `gebco.depth` | `GeoOutput` (`GeoContext`, `ZoneHit`s) |
| 7 | **Hazard & Risk** | assembles per-source factor inputs over all sample points × hours (or route at ETA) and applies `orca-risk-1.0`; hourly timeline; per-station regional assessment; extended horizon | `risk.evaluate`, `risk.point_risk` | `HazardOutput` (`RiskAssessment`) |
| 8 | **Route** | worst-of-models hourly risk cube, time-dependent A* (shortest / recommended / safest), smoothing without raising risk, segment evaluation at ETA, zone entry distance & minutes, boundary proximity | `routing.*`, `spatial.zone_intersections` | `RouteOutput` (`RouteResult`) |
| 9 | **Evidence / Verification** | claims, per-source evidence items with A·F·S·T weights, independence, agreement, conflicts (factor, satellite-vs-model, advisory-vs-model), confidence, weakest link, final decision package, recommendations, caveats, excluded sources; follow-up reuse | `evidence.build_claims`, `confidence.*`, `conflicts.detect` | `FinalAssessment`, claims, evidence |
| 10 | **Communication / Localisation** | same result → fisherman / authority / researcher / operator views; 8 Indian languages + English templates; optional LLM narration behind the numeric grounding guard | `i18n.templates`, `llm.narrate` | `LocalizedResponse` |
| 11 | **Advisory** | official & international warnings: GDACS cyclones (track, wind radii, cone, active/inactive), IMD warnings & INCOIS alerts (adapters); distance from every sample point; point-in-wind-radius | `gdacs.cyclones`, `imd.marine_warnings`, `incois.ocean_state_alerts` | `AdvisoryOutput` |
| 12 | **Research** | comparison periods, Welch t-test, linear trend, lagged Pearson correlation, rule-based hypothesis evaluation, premise check, epistemic labels | `stats.*`, `hypothesis.evaluate_rules` | `ResearchOutput` |
| 13 | **Alert** | EVENT → VERIFY → GENERATE → DELIVER; verified only with official advisory or ≥ 2 agreeing independent lineages and confidence ≥ 0.5; de-duplication; SSE delivery; also driven by the background monitor | `alerts.*` | `Alert`s |

## Plans (examples)

* **Safety check** — `geospatial → {ocean, weather, satellite, advisory, [fisheries]} → hazard → evidence → {alert, communication}`
* **Route** — `geospatial → {ocean(field), weather(field), advisory} → route → hazard(route@ETA) → evidence → {alert, communication}`
* **Regional risk** — `geospatial(stations) → {ocean, weather, advisory} → hazard(per station) → evidence → …`
* **Fishing zones** — `geospatial(area) → {fisheries, satellite, ocean, weather, advisory} → hazard → evidence → communication`
* **Research** — `geospatial(area) → {satellite(series), weather(history)} → research → evidence → communication`
* **Follow-ups** ("what sources support…", "which sources disagree", "explain why") — `evidence(reuse previous blackboard) → communication`

## Re-planning rules (the graph's `review` node after each round, max 3 rounds)

| Rule | Trigger | Action |
|---|---|---|
| RP1 | a critical retrieval (waves or wind) returned no data | add an alternative-model task (DWD GWAM / UK Met Office), re-run hazard → evidence → alert → communication |
| RP2 | decision-relevant conflict on wave height or wind | add an independent tie-breaker model, re-verify |
| RP3 | active tropical cyclone within 1 500 km | add an extended-horizon hazard assessment (+24 h) and surface it in recommendations |
| RP4 | recommended route enters a protected area | re-route with protected areas as a hard constraint; if impossible, keep the route and say so |

Failure isolation: an agent that throws or times out is recorded as `FAILED`; dependants still run and handle
the missing input (e.g. hazard returns `INSUFFICIENT_DATA`).
