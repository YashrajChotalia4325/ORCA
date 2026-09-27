# Safety, honesty and data ethics

## Safety-critical output policy
* Decisions are **GO / CAUTION / DON'T GO / NO RELIABLE ASSESSMENT**, always with colour + shape + text.
  GO means "within ORCA's configured limits", never "definitely safe".
* Worst case across sources, sample points and hours; disagreement makes ORCA more conservative, never averaged.
* Missing critical data (wind or waves) ⇒ refusal: *"Unable to provide a reliable safety assessment because current
  wave data is unavailable. ORCA will not infer safety from partial information."*
* Official warnings (IMD / INCOIS), when accessible, dominate model output. When they are *not* accessible ORCA
  says so in every answer and recommends checking them.
* Model-inferred convective potential can raise to CAUTION but cannot alone force DON'T GO (R2b).
* Temporal honesty: onsets are reported ("caution from 08:30 IST — be back before then"); windows are explicit.

## No fake data
* LIVE mode contains only real external data. Adapters for credentialed / non-public sources return typed
  failures (`CREDENTIALS_REQUIRED`, `NO_PUBLIC_API`) and are listed as *excluded sources*.
* REPLAY data is labelled REPLAY with its recording time; DEMO data is labelled SIMULATED, with a striped banner.
  Tests assert that no DEMO evidence item is ever LIVE.
* Satellite analyses are labelled with their product date and age; GIBS tiles are imagery only.
* ORCA-derived indicators (productivity zones) are never presented as INCOIS PFZ advisories.
* Approximate protected-area outlines are flagged approximate everywhere.

## Security
* Secrets only from environment variables; stripped from recorded/displayed URLs; presence (not value) reported.
* Bearer-token roles; `ORCA_AUTH_REQUIRED=true` for shared deployments; admin role for evaluation runs and
  source probes; token-bucket rate limit (default 60/min/client) on query-starting endpoints.
* Input validation by Pydantic (text ≤ 2 000 chars, coordinate ranges, geofence rings ≤ 500 vertices, radii).
* CORS allow-list; `X-Content-Type-Options: nosniff`; container runs as non-root.

## Location privacy
* Request logs record method, path, status and latency only — never query strings or coordinates.
* Stored query locations are rounded to 0.1° (~11 km) unless `ORCA_STORE_PRECISE_LOCATION=true`.
* Watches (vessel points) are stored only when a user registers them and can be deleted.

## Attribution & endorsement
ORCA is not endorsed by ISRO, INCOIS, IMD, NOAA, NASA, ECMWF, Météo-France, DWD, UK Met Office, VLIZ, GDACS or any
other organisation. It distinguishes **official source data** from **ORCA's computational interpretation** in
every answer, and is a decision-support system, not an authority.
