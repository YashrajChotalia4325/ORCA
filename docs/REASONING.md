# Reasoning

What the LLM does (optional): interpret a low-confidence question into *gazetteer identifiers* and an English
time phrase; rephrase a computed result. What deterministic code does: everything else below.

## 1. Understanding (reasoning/nlu.py, core/temporal.py)

* **Language** by Unicode script (Malayalam, Tamil, Telugu, Kannada, Bengali, Gujarati, Odia; Devanagari split
  into Hindi vs Marathi by marker words).
* **Intent** by an ordered rule set over a multilingual cue lexicon (`reasoning/lexicon.py`): conflicts → sources
  → explain → route → hazard/geofence → compare → research → fishing zones → geofence → regional → hazard scan →
  safety → conditions.
* **Places** from a 64-place / 15-region gazetteer with local-language names, Indic case-ending stems
  (ராமேஸ்வரத்தில் → ராமேஸ்வரம்), coordinates (one or two), offshore distances ("30 km off", "20 nm offshore",
  "30 കി.മീ"), radii, vessel class cues.
* **Time** to an explicit window in IST with the rule and assumptions recorded: "tomorrow at 5 AM" →
  27 Sep 05:00–11:00 IST (*assumed 6 h trip*); "tomorrow morning" → 05:00–11:00; "next 12 hours";
  "past 14 days" → current + comparison window; weekday / date forms; regional-language words for
  tomorrow/today/morning/…; "कल/কাল" ambiguity recorded as an assumption.
* Follow-ups inherit location/time from the conversation; missing locations produce a clarification request.

## 2. Spatial–temporal alignment

The geospatial agent designs the sampling, so conclusions are about the whole activity, not one point:
* **Safety**: assessment point `d` km seaward (bearing chosen among 72 by maximum distance from coast with a
  sea mid-point), two transit points from the harbour, a 4-point 8 km ring.
* **Hazard scan**: 8-bearing rings at r/2 and r.
* **Regional**: one station 25 km off each anchor harbour of the sector.
* **Route**: every ~1 km at ETA (departure + distance/speed) for risk; per-model samples every 5 km for evidence.
Every factor is evaluated over *all sample points × all hours in the window × all sources*.

## 3. Risk model `orca-risk-1.0` (core/risk.py)

Thresholds per vessel class (ORCA defaults, configurable, **not validated by an authority**; wind informed by
IMD's squally-weather fishermen warnings 45–55 km/h):

| Factor | small craft (caution / danger) | mechanised | large vessel |
|---|---|---|---|
| Sustained wind (km/h) | 28 / 45 | 40 / 55 | 55 / 75 |
| Gusts (km/h) | 40 / 60 | 55 / 75 | 75 / 100 |
| Significant wave height (m) | 1.5 / 2.5 | 2.0 / 3.0 | 3.5 / 5.0 |
| Surface current (km/h) | 3.7 / 5.6 | 4.6 / 7.4 | 5.6 / 9.3 |
| Rain rate (mm/h) | 5 / 15 | 8 / 20 | 15 / 30 |
| Thunderstorm potential (CAPE J/kg, rain-gated) | 1500 / 2500 | 2000 / 3000 | 2500 / 3500 |
| Visibility (km, below) | 4 / 1 | 2 / 0.5 | 1 / 0.3 |
| Cyclone distance (km, below) | 800 / 300 | 600 / 250 | 400 / 200 |
| International boundary (km, below) | 10 / 2 | 10 / 2 | — |

Per factor: each source's worst value in the window, its level, onset (first caution time), spread across
sources; the **conservative (worst-case) value** decides — no averaging. CAPE is counted only where the same
model predicts ≥ 0.5 mm/h rain at the same place and hour (otherwise ×0.4).

Decision rules (all recorded in `rules_fired`):
* **R1** a critical factor (wind, waves) unavailable → `INSUFFICIENT_DATA` ("Unable to provide a reliable safety
  assessment because current … data is unavailable") — never "conditions appear safe".
* **R2** any factor at DANGER → `DONT_GO`. **R2b** convective potential is model-inferred: it may raise to
  CAUTION but never alone to DON'T GO.
* **R4** any factor at CAUTION → `CAUTION`.
* **R5** sources straddle the caution threshold on a critical factor → CAUTION floor.
* **R3** all sources for a critical factor STALE → CAUTION floor.
* **R6** otherwise `GO` — "within configured limits, not a guarantee of safety".
* Official advisories (IMD/INCOIS, when accessible) enter as their own factor; an official DANGER forces DON'T GO.

Risk index = 100·min(1, 0.7·max(weighted factor score) + 0.3·mean(critical scores)), where the score is 0 at half
the caution threshold, 0.5 at caution and 1 at danger.

## 4. Confidence (core/confidence.py) — computed, never generated

Per evidence item *i*: **w = A × F × S × T**
* **A** authority weight by tier: national official 0.95 · intergovernmental 0.90 · foreign national agency 0.88 ·
  scientific compilation 0.85 · ORCA-derived 0.70 · ORCA-curated 0.50.
* **F** freshness: LIVE 1.0 · RECENT 0.95 · STALE 0.6 · UNAVAILABLE 0 · STATIC 0.9 (REPLAY/SIMULATED scored as at
  source time, always labelled).
* **S** spatial match = exp(−max(0, d − 0.71 r)/50 km) × (1 − min(0.3, r/150 km)); d = distance to the product
  cell used, r = native resolution.
* **T** temporal match: forecasts exp(−lead_h/168); analyses/observations exp(−max(0, age_h − validity_h)/48);
  advisories 1 (0.5 outside validity).

Per claim: **Q** = Σι·w/Σι (ι = 1 for the first item of a lineage, 0.3 for repeats), **G** = independence-weighted
share of items agreeing with the claim's level, **K** = 1.0 with ≥ 2 independent lineages else 0.85;
**conf = Q × (0.5 + 0.5·G) × K**.

Assessment: weighted mean of claim confidences (decision drivers ×2) × **C** (completeness: Σ weights of
available factors / expected; critical ×2) × **(0.7 + 0.3·D)** (D = share of queried critical sources that
responded). INSUFFICIENT_DATA reports 0. The UI shows every component and the weakest link.

## 5. Conflicts (reasoning/conflicts.py)

For each factor with ≥ 2 sources: Δ = max − min vs tolerance max(abs, rel·mean) (waves 0.5 m / 25 %, wind 10 km/h /
30 %, gusts 15 km/h / 30 %, currents 2 km/h / 50 %, rain 5 mm/h, CAPE 800 J/kg / 50 %, SST 1 °C).
*Decision-relevant* when sources fall in different risk levels. Also: satellite SST vs model SST, and official
advisory level vs model level. Resolution: conservative value retained, confidence reduced through G, and
re-planning RP2 adds an independent tie-breaker model.

## 6. Freshness (core/freshness.py)

Two clocks per datum — product age (now − model-run availability / product time / bulletin issue) and retrieval
age (now − fetch). Rules in order: no data → UNAVAILABLE; REPLAY → REPLAY; DEMO → SIMULATED; reference → STATIC;
product age > 1.25 × (update interval + expected latency) → STALE; fetched ≤ 15 min → LIVE; ≤ 60 min → RECENT;
else STALE. Stale-if-error cache hits are flagged.

## 7. Routing (core/routing.py, agents/route.py)

Grid 0.03–0.1° over the route box; land impassable; no diagonal corner-cutting; restricted areas and (for
fishing craft) foreign EEZs impassable; protected areas ×6. Hourly risk cube = max over models of the vectorised
factor score of waves/wind/gusts/current/rain, interpolated from the coarse forecast grid.
`edge = d·(1 + α·r(x, ETA))·zone + 20·d·[r ≥ 1]`, α = 0 (shortest), 3 (recommended), 8 (safest); admissible
great-circle heuristic. Line-of-sight smoothing only where the straight segment stays at sea, outside blocked
zones and does not raise the section's max risk. Evaluation every 1 km at ETA → segments (risk, level, drivers,
Hs, wind, current), zone entry distance/minutes/length inside, boundary distance.

## 8. Fisheries indicator (reasoning/fisheries.py)

score = 0.45·f_front + 0.40·f_chl + 0.15·f_sst, f_front = clamp(|∇SST|/(2·G0)), G0 = max(0.02 °C/km, P90),
f_chl = clamp(log10(chl/0.1)/log10(30)), f_sst = 1 in 25–30 °C tapering over 3 °C. Cells ≥ 0.55, at sea, inside the
Indian EEZ; 8-connected clusters → top 5 zones with rationale and depth. Always "probabilistic; presence of fish is
not implied"; official INCOIS PFZ kept separate.

## 9. Research (reasoning/research.py)

Welch t-test between periods, least-squares trend, Pearson correlation with best lag (0–5 d); hypotheses
H1 stratification / weakened upwelling, H2 seasonal upwelling relaxation (west coast, Sep–Nov), H3 cloud / DINEOF
artefact, H4 SST anomaly — each with explicit supporting and contradicting evidence and a status. Findings are
labelled OBSERVATION / CORRELATION / HYPOTHESIS / CONCLUSION; the conclusion states that causation is not
established and flags when the question's premise contradicts the data.

## 10. Hallucination guard (reasoning/llm.py)

Every number in LLM narration must appear (exactly or as a rounding) in the facts passed to it; otherwise the
narration is discarded and templates are used. The decision label, sections, tables and numbers shown in the UI
always come from deterministic code.
