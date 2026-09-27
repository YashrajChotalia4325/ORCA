"""Shared enums and primitive types used across every ORCA layer.

All timestamps are timezone-aware UTC internally. Presentation layers convert
to IST (Asia/Kolkata) and always print the zone.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DataMode(str, Enum):
    LIVE = "LIVE"        # only real external data
    REPLAY = "REPLAY"    # recorded real responses, original timestamps preserved
    DEMO = "DEMO"        # synthetic scenario data, always labelled SIMULATED


class DataKind(str, Enum):
    OBSERVED = "OBSERVED"        # in-situ / direct measurement
    ANALYSIS = "ANALYSIS"        # satellite-derived gridded analysis (observation based)
    FORECAST = "FORECAST"        # numerical model forecast
    ADVISORY = "ADVISORY"        # official warning / bulletin
    HISTORICAL = "HISTORICAL"    # archived record used for comparison
    REFERENCE = "REFERENCE"      # static geodata (coastline, EEZ, MPA)
    DERIVED = "DERIVED"          # computed by ORCA from other data


class FreshnessStatus(str, Enum):
    LIVE = "LIVE"                # fetched <= 15 min ago and product within its refresh cycle
    RECENT = "RECENT"            # fetched <= 60 min ago and product within its refresh cycle
    STALE = "STALE"              # product older than its expected refresh, or cached too long
    UNAVAILABLE = "UNAVAILABLE"  # source failed / no data
    REPLAY = "REPLAY"            # recorded data being replayed (never LIVE)
    SIMULATED = "SIMULATED"      # synthetic demo data (never LIVE)
    STATIC = "STATIC"            # reference data that does not have a refresh cycle


class SourceStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"                    # recent failures / circuit half-open / serving cache
    DOWN = "DOWN"                            # circuit open
    CREDENTIALS_REQUIRED = "CREDENTIALS_REQUIRED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NO_PUBLIC_API = "NO_PUBLIC_API"
    STATIC = "STATIC"
    UNKNOWN = "UNKNOWN"


class AuthorityTier(str, Enum):
    NATIONAL_OFFICIAL = "NATIONAL_OFFICIAL"          # IMD, INCOIS, ISRO/MOSDAC
    INTERGOVERNMENTAL = "INTERGOVERNMENTAL"          # ECMWF, Copernicus, GDACS
    NATIONAL_AGENCY_FOREIGN = "NATIONAL_AGENCY_FOREIGN"  # NOAA, NASA, Météo-France, DWD
    SCIENTIFIC_COMPILATION = "SCIENTIFIC_COMPILATION"    # Marine Regions, GEBCO, Natural Earth
    ORCA_DERIVED = "ORCA_DERIVED"
    ORCA_CURATED = "ORCA_CURATED"                    # hand-digitised approximations


class AgentStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"      # produced output but some inputs missing
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Decision(str, Enum):
    GO = "GO"
    CAUTION = "CAUTION"
    DONT_GO = "DONT_GO"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"   # informational queries


class RiskLevel(str, Enum):
    NOMINAL = "NOMINAL"
    CAUTION = "CAUTION"
    DANGER = "DANGER"
    UNKNOWN = "UNKNOWN"


class UserRole(str, Enum):
    FISHERMAN = "fisherman"
    AUTHORITY = "authority"
    RESEARCHER = "researcher"
    OPERATOR = "operator"
    PUBLIC = "public"


class VesselClass(str, Enum):
    SMALL_CRAFT = "small_craft"     # traditional / outboard FRP boats, < 10 m
    MECHANIZED = "mechanized"       # trawlers, gill-netters, 10-24 m
    LARGE_VESSEL = "large_vessel"   # coastal cargo / passenger, > 24 m


class Intent(str, Enum):
    SAFETY_CHECK = "SAFETY_CHECK"
    CONDITIONS = "CONDITIONS"
    ROUTE_PLAN = "ROUTE_PLAN"
    FISHING_ZONES = "FISHING_ZONES"
    HAZARD_SCAN = "HAZARD_SCAN"
    REGIONAL_RISK = "REGIONAL_RISK"
    RESEARCH_TREND = "RESEARCH_TREND"
    COMPARE_PERIODS = "COMPARE_PERIODS"
    GEOFENCE_CHECK = "GEOFENCE_CHECK"
    EXPLAIN = "EXPLAIN"
    SOURCES = "SOURCES"
    CONFLICTS = "CONFLICTS"
    UNKNOWN = "UNKNOWN"


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    def rounded(self, nd: int = 1) -> "GeoPoint":
        return GeoPoint(lat=round(self.lat, nd), lon=round(self.lon, nd))

    def key(self, nd: int = 3) -> str:
        return f"{self.lat:.{nd}f},{self.lon:.{nd}f}"


class BBox(BaseModel):
    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float

    def as_list(self) -> list[float]:
        return [self.lon_min, self.lat_min, self.lon_max, self.lat_max]

    def contains(self, p: GeoPoint) -> bool:
        return self.lon_min <= p.lon <= self.lon_max and self.lat_min <= p.lat <= self.lat_max

    def expanded(self, deg: float) -> "BBox":
        return BBox(lon_min=self.lon_min - deg, lat_min=self.lat_min - deg,
                    lon_max=self.lon_max + deg, lat_max=self.lat_max + deg)

    @classmethod
    def around(cls, p: GeoPoint, half_deg: float) -> "BBox":
        return cls(lon_min=p.lon - half_deg, lat_min=p.lat - half_deg,
                   lon_max=p.lon + half_deg, lat_max=p.lat + half_deg)


class TimeWindow(BaseModel):
    start: datetime
    end: datetime
    label: str = ""
    display_tz: str = "Asia/Kolkata"
    rule: str = ""                   # which resolution rule fired
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("TimeWindow datetimes must be timezone-aware (UTC)")
        return v

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


class Place(BaseModel):
    id: str
    name: str
    kind: str                  # city | port | fishing_harbour | island | region | coordinate | offshore
    point: GeoPoint
    state: Optional[str] = None
    names: dict[str, str] = Field(default_factory=dict)   # language code -> local name
    bbox: Optional[BBox] = None
    matched_text: Optional[str] = None
