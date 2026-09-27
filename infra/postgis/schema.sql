-- ORCA production data model (PostGIS). The prototype runs on SQLite (apps/api/orca/store/db.py) with the
-- same logical tables; geometry-heavy operations are done in shapely/pyproj. This schema is the migration
-- target for a multi-user deployment. It is loaded by `docker compose --profile postgis up`.
CREATE EXTENSION IF NOT EXISTS postgis;

-- ------------------------------------------------------------------ reference geometry
CREATE TABLE ref_zone (
  id            text PRIMARY KEY,
  name          text NOT NULL,
  kind          text NOT NULL CHECK (kind IN ('eez','maritime_boundary','eez_limit','mpa','restricted','seasonal_restriction','geofence','land')),
  authority     text,
  source        text NOT NULL,                 -- 'Marine Regions', 'WDPA', 'ORCA-curated (approximate)', 'user'
  approximate   boolean NOT NULL DEFAULT false,
  season_start  char(5),                       -- 'MM-DD' for seasonal rules
  season_end    char(5),
  applies_to    text[],                        -- vessel classes
  props         jsonb NOT NULL DEFAULT '{}',
  geom          geometry(Geometry, 4326) NOT NULL,
  valid_from    timestamptz, valid_to timestamptz,
  loaded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ref_zone_gix ON ref_zone USING gist (geom);
CREATE INDEX ref_zone_kind ON ref_zone (kind);

CREATE TABLE ref_place (
  id text PRIMARY KEY, name text NOT NULL, kind text NOT NULL, state text,
  names jsonb NOT NULL DEFAULT '{}',          -- language -> name
  aliases text[] NOT NULL DEFAULT '{}',
  geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX ref_place_gix ON ref_place USING gist (geom);

-- ------------------------------------------------------------------ sources & observations
CREATE TABLE source (
  id text PRIMARY KEY, name text NOT NULL, organization text NOT NULL, distributor text,
  authority_tier text NOT NULL, integration text NOT NULL, access text NOT NULL,
  descriptor jsonb NOT NULL                    -- datasets, resolutions, cadence, licence
);

CREATE TABLE source_health (
  source_id text REFERENCES source(id), at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL, latency_ms real, detail text,
  PRIMARY KEY (source_id, at)
);

-- cached normalised observations / forecasts (one row per source, variable, cell, valid time)
CREATE TABLE observation (
  source_id     text REFERENCES source(id),
  dataset       text NOT NULL,
  variable      text NOT NULL,
  kind          text NOT NULL CHECK (kind IN ('OBSERVED','ANALYSIS','FORECAST','ADVISORY','HISTORICAL','REFERENCE','DERIVED')),
  valid_time    timestamptz NOT NULL,
  issued_at     timestamptz,                   -- model run initialisation / bulletin time
  retrieved_at  timestamptz NOT NULL,
  value         double precision,
  units         text NOT NULL,
  mode          text NOT NULL CHECK (mode IN ('LIVE','REPLAY','DEMO')),
  geom          geometry(Point, 4326) NOT NULL,
  PRIMARY KEY (source_id, variable, valid_time, geom, retrieved_at)
);
CREATE INDEX observation_gix ON observation USING gist (geom);
CREATE INDEX observation_time ON observation (variable, valid_time);

-- ------------------------------------------------------------------ queries, traces, evidence
CREATE TABLE query (
  query_id text PRIMARY KEY, trace_id text UNIQUE NOT NULL, conversation_id text,
  created_at timestamptz NOT NULL, completed_at timestamptz, mode text NOT NULL,
  intent text, role text, language text, decision text, confidence real, status text,
  location_coarse geometry(Point, 4326),       -- rounded to 0.1 deg unless precise storage is enabled
  duration_ms real, llm_input_tokens int, llm_output_tokens int,
  blackboard jsonb NOT NULL                    -- full typed blackboard (plan, agents, claims, evidence, events)
);
CREATE INDEX query_conv ON query (conversation_id, created_at);

CREATE TABLE agent_run (
  query_id text REFERENCES query(query_id) ON DELETE CASCADE, task_id text, agent text NOT NULL,
  status text NOT NULL, round int NOT NULL DEFAULT 0, duration_ms real, n_failures int,
  PRIMARY KEY (query_id, task_id)
);

CREATE TABLE claim (
  query_id text REFERENCES query(query_id) ON DELETE CASCADE, claim_id text, category text, epistemic text,
  text text NOT NULL, confidence real, geom geometry(Point, 4326),
  PRIMARY KEY (query_id, claim_id)
);
CREATE TABLE evidence_item (
  query_id text, claim_id text, evidence_id text, source_id text, kind text, variable text,
  value double precision, units text, valid_time timestamptz, retrieved_at timestamptz,
  authority real, freshness real, spatial real, temporal real, weight real, lineage text, provenance jsonb,
  PRIMARY KEY (query_id, evidence_id),
  FOREIGN KEY (query_id, claim_id) REFERENCES claim(query_id, claim_id) ON DELETE CASCADE
);

-- ------------------------------------------------------------------ alerts & watches
CREATE TABLE alert (
  id text PRIMARY KEY, created_at timestamptz NOT NULL, severity text NOT NULL, category text NOT NULL,
  title text NOT NULL, message text NOT NULL, region text, level text, verified boolean NOT NULL,
  verification text, mode text NOT NULL, status text NOT NULL DEFAULT 'active', dedup_key text,
  valid_from timestamptz, valid_to timestamptz, trace_id text, evidence jsonb, geom geometry(Point, 4326)
);
CREATE INDEX alert_dedup ON alert (dedup_key, created_at);
CREATE INDEX alert_gix ON alert USING gist (geom);

CREATE TABLE watch (
  id text PRIMARY KEY, name text NOT NULL, kind text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  active boolean NOT NULL DEFAULT true, radius_km real, vessel_class text, geom geometry(Geometry, 4326) NOT NULL
);

CREATE TABLE eval_run (id text PRIMARY KEY, created_at timestamptz NOT NULL, summary jsonb NOT NULL, results jsonb NOT NULL);

-- example: zones within 20 km of a vessel (what the monitor does in shapely today)
-- SELECT id, name, kind, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography)/1000 AS km
--   FROM ref_zone WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 20000);
