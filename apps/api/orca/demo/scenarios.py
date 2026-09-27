"""DEMO scenarios — controlled, clearly-labelled synthetic environments.

Each scenario fixes the clock, defines the synthetic environment and which
sources fail, and supplies simulated payloads for adapters that are not
accessible live (IMD, INCOIS, MOSDAC) so the complete pipeline can be shown.
Nothing produced here is ever labelled LIVE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from ..connectors.transport import TransportError
from . import simulator as sim
from .simulator import Blob, Cyclone, Environment, Ramp

NOW = datetime(2026, 9, 26, 0, 30, tzinfo=timezone.utc)      # 26 Sep 2026 06:00 IST


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    query: str
    env: Environment
    focus: dict
    demonstrates: list[str]
    queries: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    imd: list[dict] = field(default_factory=list)
    incois_osf: list[dict] = field(default_factory=list)
    incois_pfz: list[dict] = field(default_factory=list)
    now: datetime = NOW

    def respond(self, source_id: str, url: str, params: dict) -> Any:
        if source_id in self.failures:
            st = self.failures[source_id]
            raise TransportError(source_id, st, f"simulated outage ({st}) in scenario '{self.id}'")
        host = urlparse(url).netloc
        if "open-meteo.com" in host:
            if "/static/meta.json" in url:
                model = url.split("/data/")[1].split("/")[0]
                return sim.openmeteo_meta(self.now, model)
            return sim.openmeteo(self.env, self.now, source_id, params, marine="marine-api" in host)
        if "coastwatch" in host:
            return sim.erddap(self.env, self.now, url, sim.climatology)
        if "gdacs" in host:
            return sim.gdacs_geometry(self.env, self.now) if "getgeometry" in url else sim.gdacs_events(self.env, self.now)
        if "opentopodata" in host:
            return sim.gebco(params)
        if host == "demo.orca.invalid":
            path = urlparse(url).path
            issued = (self.now - timedelta(hours=2)).isoformat()
            if path.startswith("/imd/"):
                return {"issued_at": issued, "warnings": self.imd}
            if path.startswith("/incois/ocean_state"):
                return {"issued_at": issued, "alerts": self.incois_osf}
            if path.startswith("/incois/pfz"):
                return {"issued_at": issued, "type": "FeatureCollection", "features": self.incois_pfz}
            if path.startswith("/mosdac/"):
                raise TransportError(source_id, "CREDENTIALS_REQUIRED", "MOSDAC is not simulated — adapter shown as unavailable")
        raise TransportError(source_id, "NOT_SIMULATED", f"{host} is not simulated in DEMO mode")

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "description": self.description, "query": self.query,
                "queries": self.queries or [self.query], "focus": self.focus, "demonstrates": self.demonstrates,
                "now": self.now.isoformat(), "failures": self.failures,
                "has_cyclone": self.env.cyclone is not None}


BASE = {"wave_height": 1.1, "wind_speed": 16.0, "precipitation": 0.2, "cape": 800.0, "pressure": 1008.0,
        "current_speed": 1.2, "sst": 28.7, "sst_model": 28.8, "chlorophyll": 0.35, "visibility": 20.0}
BIAS = {"om_ecmwf_wam": {"wave_height": 0.93}, "om_gfs_wave": {"wave_height": 1.06}, "om_dwd_gwam": {"wave_height": 0.98},
        "om_ecmwf_ifs": {"wind_speed": 0.95}, "om_gfs": {"wind_speed": 1.05}, "om_ukmo": {"wind_speed": 1.02}}


def _b(**kw) -> dict:
    d = dict(BASE)
    d.update(kw)
    return d


def _poly(lon0, lat0, lon1, lat1) -> dict:
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}


SCENARIOS: dict[str, Scenario] = {}


def _add(s: Scenario) -> None:
    SCENARIOS[s.id] = s


_add(Scenario(
    id="kochi_fishing", title="Fishing safety near Kochi",
    description="Monsoon swell building through tomorrow morning off Kerala; winds freshen after 07:30 IST. "
                "INCOIS (simulated) has a high-wave alert that agrees with the models.",
    query="Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?",
    queries=["Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?",
             "Is it safe to fish 30 km off the coast of Kochi tomorrow morning?",
             "നാളെ രാവിലെ കൊച്ചിയിൽ നിന്ന് മീൻ പിടിക്കാൻ പോകാമോ?", "Explain why you classified this as caution",
             "What sources support your conclusion?"],
    env=Environment(base=_b(wave_height=1.15, wind_speed=17, chlorophyll=0.6), coastal={"chlorophyll": 2.0},
                    ramps=[Ramp("wave_height", 24.5, 28.5, 0.8), Ramp("wind_speed", 25, 28.5, 15), Ramp("cape", 22, 27, 700)],
                    bias=BIAS),
    focus={"lat": 9.93, "lon": 76.06, "zoom": 8},
    demonstrates=["multi-model agreement", "temporal reasoning: onset of caution inside the trip window",
                  "official advisory consistent with models", "return-before recommendation"],
    incois_osf=[{"title": "High wave alert — Kerala coast", "level": "CAUTION", "area": "Kollam to Kasaragod",
                 "text": "High waves of 1.5–2.2 m expected from 27 Sep 06:00 IST (SIMULATED bulletin)"}],
    incois_pfz=[{"type": "Feature", "properties": {"name": "PFZ Kochi sector (SIMULATED)", "description": "Depth 40–60 m, 45–60 km WSW of Kochi"},
                 "geometry": _poly(75.55, 9.70, 75.75, 9.95)}]))

_add(Scenario(
    id="approaching_cyclone", title="Approaching cyclone — Andhra / Odisha coast",
    description="A simulated severe cyclonic storm moves north-west across the Bay of Bengal toward Visakhapatnam; "
                "GDACS (simulated) Red alert, IMD (simulated) advises fishermen not to venture.",
    query="Is it safe to fish off Visakhapatnam tomorrow morning?",
    queries=["Is it safe to fish off Visakhapatnam tomorrow morning?",
             "Show cyclone risk across the Andhra Pradesh coast for the next 24 hours",
             "రేపు ఉదయం విశాఖపట్నం నుండి చేపల వేటకు వెళ్ళవచ్చా?", "Is there a cyclone affecting this route?"],
    env=Environment(base=_b(wave_height=1.8, wind_speed=26, precipitation=1.0, cape=1400),
                    cyclone=Cyclone("DEMO-01 (SIMULATED)", [(-36, 14.0, 88.6, 75), (-12, 15.2, 87.3, 95), (0, 16.0, 86.4, 115),
                                                             (12, 16.8, 85.4, 125), (24, 17.5, 84.4, 120), (36, 18.3, 83.7, 90)]),
                    bias=BIAS),
    focus={"lat": 17.0, "lon": 84.8, "zoom": 6},
    demonstrates=["cyclone proximity from track + wind radii (point-in-polygon)", "official warnings", "DON'T GO",
                  "re-planning: extended 24 h horizon when a cyclone is near", "proactive alerts"],
    imd=[{"title": "Severe Cyclonic Storm DEMO-01 — fishermen warning (SIMULATED)", "level": "DANGER",
          "area": "Andhra Pradesh & Odisha coasts", "text": "Fishermen are advised not to venture into the west-central Bay of Bengal "
                                                            "along and off Andhra Pradesh and south Odisha coasts until further notice."}],
    incois_osf=[{"title": "High wave / swell surge alert (SIMULATED)", "level": "DANGER", "area": "Srikakulam to Kakinada",
                 "text": "Waves of 3.5–6.0 m expected"}]))

_add(Scenario(
    id="mumbai_goa_route", title="Mumbai → Goa lower-risk route",
    description="A squall with steep seas sits close to the Ratnagiri coast. The shortest (coast-hugging) track passes "
                "through it; the router finds an offshore alternative and quantifies the trade-off.",
    query="Find a lower-risk route from Mumbai to Goa for a trawler departing tomorrow at 6 AM",
    queries=["Find a lower-risk route from Mumbai to Goa for a trawler departing tomorrow at 6 AM",
             "Is it safe to sail from Mumbai to Goa tomorrow morning?"],
    env=Environment(base=_b(wave_height=1.35, wind_speed=21),
                    blobs=[Blob("wave_height", 17.1, 73.0, 55, 2.4, -6, 20, 60), Blob("wind_speed", 17.1, 73.0, 60, 26, -6, 20, 60),
                           Blob("precipitation", 17.1, 73.0, 60, 9, -6, 20, 60)],
                    bias=BIAS),
    focus={"lat": 17.1, "lon": 72.9, "zoom": 6.5},
    demonstrates=["route risk evaluated per segment at ETA", "shortest vs recommended vs safest",
                  "hazard exposure trade-off", "route risk heat-map"]))

_add(Scenario(
    id="pfz_mangaluru", title="Potential fishing zone — Karnataka coast",
    description="Coastal upwelling creates a sharp SST front ~55 km off Mangaluru with a chlorophyll bloom along it; "
                "a simulated INCOIS PFZ advisory lies on the same front.",
    query="Show potential fishing zones near Mangaluru",
    queries=["Show potential fishing zones near Mangaluru", "Why is this region a potential fishing zone?",
             "Find regions with favorable SST and chlorophyll conditions near Mangaluru",
             "ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಮಂಗಳೂರಿನಿಂದ ಮೀನುಗಾರಿಕೆಗೆ ಹೋಗಬಹುದೇ?"],
    env=Environment(base=_b(sst=28.4, sst_model=28.5, chlorophyll=0.3, wave_height=1.0, wind_speed=14),
                    coastal={"chlorophyll": 1.0, "sst": -0.6},
                    sst_front={"lat0": 12.0, "lat1": 14.2, "lon": 74.3, "width_km": 6, "delta": 1.6, "chl_boost": 2.6},
                    bias=BIAS),
    focus={"lat": 12.9, "lon": 74.3, "zoom": 7.5},
    demonstrates=["SST-front detection (∇SST)", "chlorophyll co-location", "probabilistic language (no fish-presence claims)",
                  "official PFZ vs ORCA-derived indicator"],
    incois_pfz=[{"type": "Feature", "properties": {"name": "PFZ Mangaluru sector (SIMULATED)",
                                                   "description": "Along 74.2–74.4°E between 12.6°N and 13.3°N, depth 50–70 m"},
                 "geometry": _poly(74.2, 12.6, 74.4, 13.3)}]))

_add(Scenario(
    id="protected_geofence", title="Protected-area geofence — Gulf of Mannar",
    description="Calm seas; the question is spatial. The direct Thoothukudi → Rameswaram track crosses the Gulf of Mannar "
                "Marine National Park (approximate outline) and runs close to the India–Sri Lanka maritime boundary.",
    query="Plan a route from Thoothukudi to Rameswaram for a fishing boat tomorrow morning",
    queries=["Plan a route from Thoothukudi to Rameswaram for a fishing boat tomorrow morning",
             "Is my planned route entering a protected area?", "What hazards exist within 50 km of 9.10N 79.30E?"],
    env=Environment(base=_b(wave_height=0.7, wind_speed=12), bias=BIAS),
    focus={"lat": 9.05, "lon": 78.7, "zoom": 8},
    demonstrates=["route ∩ MPA polygon, distance & time to entry", "re-planning with protected areas as hard constraint",
                  "IMBL proximity", "deterministic geometry — no LLM"]))

_add(Scenario(
    id="conflicting_sources", title="Conflicting sources — Chennai",
    description="Wave models disagree across the caution threshold, NWP winds disagree, IMD (simulated) has no warning "
                "while INCOIS (simulated) issues a high-wave alert, and satellite SST differs from model SST.",
    query="Is it safe to fish 25 km off Chennai tomorrow morning?",
    queries=["Is it safe to fish 25 km off Chennai tomorrow morning?", "Which data sources disagree?",
             "Explain why you classified this region as high risk"],
    env=Environment(base=_b(wave_height=1.55, wind_speed=22, sst=29.9, sst_model=28.3),
                    bias={"om_mfwam": {"wave_height": 1.55}, "om_ecmwf_wam": {"wave_height": 0.8}, "om_gfs_wave": {"wave_height": 1.1},
                          "om_dwd_gwam": {"wave_height": 1.22}, "om_ecmwf_ifs": {"wind_speed": 0.78}, "om_gfs": {"wind_speed": 1.35},
                          "om_icon": {"wind_speed": 1.0}, "om_ukmo": {"wind_speed": 1.2}}),
    focus={"lat": 13.1, "lon": 80.5, "zoom": 8},
    demonstrates=["conflict table (source / value / time / authority / impact)", "no averaging — conservative resolution",
                  "re-planning: independent tie-breaker models (DWD GWAM, UK Met Office)",
                  "advisory vs model disagreement", "satellite vs model SST"],
    incois_osf=[{"title": "High wave alert — north Tamil Nadu (SIMULATED)", "level": "CAUTION", "area": "Pulicat to Puducherry",
                 "text": "Waves of 1.8–2.5 m expected"}]))

_add(Scenario(
    id="degraded_sources", title="API failure — degraded mode",
    description="Météo-France MFWAM (HTTP 503), DWD ICON (HTTP 503) and NOAA CoastWatch (timeout) are down. ORCA "
                "continues with the remaining sources, lists every exclusion and lowers confidence.",
    query="Is it safe to fish 20 km off Kochi tomorrow morning?",
    queries=["Is it safe to fish 20 km off Kochi tomorrow morning?"],
    env=Environment(base=_b(wave_height=1.05, wind_speed=15), bias=BIAS),
    failures={"om_mfwam": "HTTP_503", "om_icon": "HTTP_503", "noaa_coastwatch": "TIMEOUT"},
    focus={"lat": 9.93, "lon": 76.06, "zoom": 8},
    demonstrates=["graceful degradation", "excluded-source reporting", "confidence reduction"]))

_add(Scenario(
    id="total_outage", title="Critical data unavailable — ORCA refuses",
    description="Every wave model fails (including the alternative model requested during re-planning). ORCA does not "
                "guess: it returns 'no reliable assessment'.",
    query="Is it safe to fish 20 km off Kochi tomorrow morning?",
    env=Environment(base=_b(wave_height=1.05, wind_speed=15), bias=BIAS),
    failures={"om_mfwam": "HTTP_503", "om_ecmwf_wam": "HTTP_503", "om_gfs_wave": "TIMEOUT", "om_dwd_gwam": "HTTP_503",
              "om_smoc": "HTTP_503"},
    focus={"lat": 9.93, "lon": 76.06, "zoom": 8},
    demonstrates=["re-planning RP1 (alternative model)", "INSUFFICIENT DATA instead of a guess", "safety-first refusal"]))

_add(Scenario(
    id="research_chl", title="Research — declining chlorophyll off Kerala",
    description="Over four weeks chlorophyll declines while SST warms and winds weaken — consistent with relaxation of "
                "the south-west-monsoon upwelling.",
    query="Why did chlorophyll concentration decline off Kochi over the past 14 days?",
    queries=["Why did chlorophyll concentration decline off Kochi over the past 14 days?",
             "Compare this week's marine conditions near Kochi with last week"],
    env=Environment(base=_b(chlorophyll=1.5, sst=28.0, wind_speed=22), coastal={"chlorophyll": 1.0},
                    daily_trend={"chlorophyll": -0.065, "sst": 0.05, "wind_speed": -0.35}, trend_ref_day=-14, bias=BIAS),
    focus={"lat": 9.9, "lon": 75.8, "zoom": 7.5},
    demonstrates=["OBSERVATION / CORRELATION / HYPOTHESIS / CONCLUSION", "Welch t-test, lagged correlation",
                  "no causal claims from correlation"]))


def get_scenario(sid: str) -> Scenario:
    return SCENARIOS[sid]


def list_scenarios() -> list[dict]:
    return [s.summary() for s in SCENARIOS.values()]
