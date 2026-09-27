# Demonstration guide

## Judge mode (≈ 4 minutes)
Open <http://localhost:3000/judge> in **LIVE** mode. It advances only when the real system has produced the data:

1. **System status** — live probe results: which sources respond now, their latest model runs / product dates, and
   which authoritative sources are *not* accessible (IMD whitelisting, MOSDAC account, INCOIS no public API …).
2. **The question** — "Is it safe to sail from Kochi tomorrow at 5 AM?" is typed and submitted.
3. **Planner** — the exact IST window (with the "assumed 6 h trip" assumption) and the task DAG with dependencies.
4. **Agents in parallel** — the network graph animates as agents start/finish; the dock streams every tool call.
5. **Live evidence** — every factor: worst value over sample points × hours × models, number of sources, spread.
6. **Conflicts & confidence** — the conflict table (real disagreements, e.g. CAPE ECMWF vs GFS) and the confidence
   formula with its components and weakest link.
7. **Decision** — the full answer card: decision, reasons, recommendations, excluded sources, caveats, map.
8. **Timestamps** — valid time, model run and retrieval time for each datum.
9. **Stress tests** — one click each, clearly labelled DEMO (below).

## DEMO scenarios (same agents, synthetic data, all labelled SIMULATED)
Select **DEMO** in the top bar, choose a scenario; its questions appear in Ask ORCA.

| Scenario | Question | What to point out |
|---|---|---|
| `kochi_fishing` | Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM? | CAUTION with onset ~08:30 IST → "be back before then"; simulated INCOIS alert agrees with models; Malayalam version gives the same decision |
| `approaching_cyclone` | Is it safe to fish off Visakhapatnam tomorrow morning? | point inside simulated wind radius → DON'T GO; IMD/INCOIS (simulated) warnings; RP3 extends horizon; alerts |
| `mumbai_goa_route` | Find a lower-risk route from Mumbai to Goa for a trawler … | shortest (peak risk 0.90) vs recommended (0.49, +40 km); segment risk profile at ETA |
| `pfz_mangaluru` | Show potential fishing zones near Mangaluru | SST front + chlorophyll co-location; ORCA-derived vs INCOIS PFZ; probabilistic wording |
| `protected_geofence` | Plan a route from Thoothukudi to Rameswaram for a fishing boat … | enters Gulf of Mannar MNP after 7.5 km (~35 min), 28.9 km inside; RP4 hard-constraint re-route proves no alternative exists |
| `conflicting_sources` | Is it safe to fish 25 km off Chennai tomorrow morning? | wave models 1.3–2.4 m straddle thresholds; GFS vs ECMWF winds; IMD (no warning) vs INCOIS (alert); satellite vs model SST; RP2 adds DWD GWAM + UK Met Office |
| `degraded_sources` | Is it safe to fish 20 km off Kochi tomorrow morning? | MFWAM, ICON, CoastWatch down → continues; exclusions listed; lower confidence |
| `total_outage` | Is it safe to fish 20 km off Kochi tomorrow morning? | all wave models down, RP1 alternative also down → NO RELIABLE ASSESSMENT |
| `research_chl` | Why did chlorophyll decline off Kochi over the past 14 days? | OBSERVATION / CORRELATION / HYPOTHESIS / CONCLUSION; no causal claims |

## REPLAY
`data/replay/<snapshot>/` holds real responses recorded by `scripts/record_replay.py` (the current snapshot has
6 questions and the map fields). In REPLAY mode the clock is fixed to the recording time; questions outside the
recording fail with `NOT_IN_RECORDING` rather than being invented. Use REPLAY when the venue has no internet.

## Suggested LIVE questions
* Is it safe to fish 30 km off the coast of Kochi tomorrow morning?
* Calculate a lower-risk route from Mumbai to Goa tomorrow morning
* Show cyclone risk across the Odisha coast for the next 24 hours
* Why did chlorophyll concentration decline off Kochi over the past 14 days? *(live data may contradict the premise — ORCA says so)*
* क्या कल सुबह मुंबई से मछली पकड़ने जाना सुरक्षित है? · நாளை காலை ராமேஸ்வரத்தில் இருந்து மீன்பிடிக்க போகலாமா?
* Follow-ups: "What sources support your conclusion?", "Which data sources disagree?"

Also show: **Live Ocean** (click the sea → every model's series), **Sources** (probe all), **Safety** (run a
monitoring scan, register a vessel watch near the IMBL), **Health** (latencies, cache hit rate), **Eval**.
