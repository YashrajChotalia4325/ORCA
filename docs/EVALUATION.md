# Evaluation

Framework: `apps/api/orca/evaluation/` (dataset + runner), UI under **Eval**, API `POST /api/eval/run`.

## Dataset (orca-eval-v1)
* **100 understanding cases** — 50 English safety questions (5 templates × 10 harbours), 14 questions in Hindi,
  Marathi, Tamil, Telugu, Malayalam, Kannada and Bengali, and 36 covering fishing zones, routes, regional risk,
  research, period comparison, hazard scans, conditions, geofence checks and follow-ups. Ground truth: intent,
  place (or region / destination), language, IST start day/hour, window length, offshore distance, vessel class.
* **14 end-to-end cases** executed in DEMO scenarios (deterministic, no network) with expected decision,
  required agents, required tools, and consistency groups (paraphrases and translations that must agree).

## Metrics
| # | Metric | Definition |
|---|---|---|
| 1 | Groundedness | share of end-to-end answers whose rendered numbers all appear in computed facts/evidence |
| 2 | Source correctness | share of answers where every evidence item has source, id, retrieval time and freshness |
| 3 | Evidence completeness | share of risk claims backed by ≥ 1 evidence item (also: critical claims with ≥ 2 lineages) |
| 4 | Temporal correctness | resolved window matches expected IST day/hour/duration |
| 5 | Spatial correctness | expected place resolved; assessment point at sea |
| 6 | Agent routing accuracy | required agents ran; no irrelevant agents (e.g. research + route) |
| 7 | Tool selection accuracy | required tools present in the trace |
| 8 | Risk consistency | paraphrase/translation groups share one decision; a re-run is identical |
| 9 | Hallucination rate | answers with unsupported numbers or any LIVE label inside DEMO output |
| 10 | Response latency | p50 / p95 end-to-end |

## Latest results (27 Sep 2026, after the move to LangGraph orchestration)
| Metric | Value |
|---|---|
| Intent accuracy (100) | 1.00 |
| Language detection (100) | 1.00 |
| Place / spatial correctness | 1.00 |
| Temporal correctness | 1.00 |
| Decision accuracy (14) | 1.00 |
| Groundedness | 1.00 |
| Source correctness | 1.00 |
| Evidence completeness | 0.96 (claims derived from unavailable-source notes carry no item) |
| Agent routing / tool selection | 1.00 / 1.00 |
| Risk consistency | 1.00 (Kochi EN/ML/HI group, Vizag EN/TE group; deterministic re-run) |
| Hallucination rate | 0.00 |
| Latency p50 / p95 (DEMO) | 0.79 s / 5.0 s |

LIVE latency is dominated by upstream APIs: typically 4–8 s for a safety check (10 agents, 13 sources), 5–6 s for a
route, 15–20 s for a 28-day research query.

## Honest reading of these numbers
The dataset was written by the same team that wrote the rules, so perfect scores show **regression safety, not
generalisation**. A credible next step is an independent test set collected from fishermen, INCOIS/IMD staff and
researchers in their own words, and a retrospective validation of decisions against observed sea states
(buoys, INCOIS OSF verification) — see [LIMITATIONS.md](LIMITATIONS.md).

## Unit / integration tests
`pytest` (85 tests): geodesy, offshore projection, EEZ/boundary/MPA/seasonal rules, user geofences, route–zone entry,
freshness rules incl. "REPLAY/DEMO never LIVE", 8-language temporal parsing, units, every risk rule, confidence
monotonicity, conflict detection, A* around land and risk, connector parsing, adapters that must not call the network,
circuit breaker, secret stripping, record/replay round trip, NLU intents in 8 languages, follow-up inheritance,
grounding guard (accepts facts, rejects invented numbers), all DEMO scenarios end-to-end, LangGraph topology and superstep ordering, API endpoints.
