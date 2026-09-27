# Limitations (read before any operational use)

## Data access
* **No live IMD, INCOIS, MOSDAC or direct Copernicus Marine data.** IMD's API rejects this deployment's IP
  (whitelisting required); INCOIS has no documented public machine API; MOSDAC and Copernicus need accounts.
  Adapters exist and activate on configuration, but today ORCA's safety answers rely on international model
  output (ECMWF, Météo-France, NOAA, DWD, UK Met Office) and GDACS — not on the Indian national warnings. Every
  answer says this and tells the user to check IMD/INCOIS bulletins.
* Open-Meteo is a redistributor; the underlying producers are named, but ORCA does not verify Open-Meteo's
  processing. Free-tier call limits constrain the monitor interval and field resolution.
* No in-situ observations (buoys, AIS, ship reports) are ingested, so there is no real-time ground truth — "observed"
  in ORCA means satellite analyses that are 1–2 days old.
* Lightning is not observed: "thunderstorm potential" is model CAPE gated by model rain.
* Storm surge, tides and tsunami bulletins are not modelled (INCOIS is the authority for tsunamis).

## Geography
* Protected / restricted / seasonal-ban outlines are hand-digitised **approximations**; seasonal ban dates follow
  typical notifications and must be checked each year. Replace with WDPA and official notifications.
* Maritime boundaries are Marine Regions compilations, not legal delimitations.
* The land mask is Natural Earth 1:10m; harbours, estuaries and small islands can be misrepresented at < 1 km.
  Offshore points are projected along the most seaward bearing, which can be wrong in complex coastlines.
* The gazetteer has 64 places; others require coordinates or a map click (Nominatim is intentionally not used).

## Models and thresholds
* Risk thresholds are ORCA defaults (informed by IMD's fishermen-warning practice and seamanship limits) and are
  **not validated** by any authority; vessel classes are coarse.
* The worst-case policy is deliberately conservative and will over-warn when one model is an outlier.
* Confidence is a transparent heuristic, not a calibrated probability; weights (authority tiers, decay constants)
  are design choices documented in REASONING.md.
* Routing uses a coarse (0.25–0.5°) forecast grid interpolated to 0.03–0.1°, ignores depth/draft, traffic
  separation schemes and vessel dynamics, and approximates ETA from distance at constant speed.
* The productivity indicator is a habitat proxy; it has not been validated against catch data or INCOIS PFZ skill.
* Research statistics use ≤ 30 daily area-means; p-values ignore autocorrelation; hypotheses are rule-based.

## Language
* Indian-language lexicons and response templates were machine-authored and **must be reviewed by native
  speakers**; detailed technical sections remain in English unless the optional LLM narration is enabled (its
  output is number-checked but not translation-checked).
* Hindi/Marathi separation uses marker words and can fail on very short questions; romanised Indian languages are
  not detected.

## Engineering
* Single-process API; in-memory caches and circuit breakers are per process; SQLite store. The PostGIS schema is
  provided but not wired as the live store. No Redis/queue; the monitor runs inside the API process.
* Authentication is static bearer tokens; no user accounts, audit log or per-user data isolation.
* The evaluation dataset was authored with the system (see EVALUATION.md).
* The DEMO environment is synthetic and only as realistic as its parameterisation; it exists to demonstrate the
  pipeline's behaviour, not the ocean's.
