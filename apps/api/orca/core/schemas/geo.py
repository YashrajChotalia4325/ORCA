"""Geospatial, route, fisheries and alert result models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .common import GeoPoint, RiskLevel


class ZoneHit(BaseModel):
    zone_id: str
    name: str
    kind: str                     # eez | maritime_boundary | mpa | restricted | seasonal_restriction | geofence
    inside: bool
    distance_km: float            # 0 when inside
    distance_nm: float
    bearing_deg: Optional[float] = None
    nearest_point: Optional[GeoPoint] = None
    active: bool = True           # temporal validity (seasonal rules)
    authority: str = ""
    source: str = ""
    approximate: bool = False
    note: str = ""


class GeoContext(BaseModel):
    point: GeoPoint
    resolved_from: str
    distance_to_coast_km: Optional[float] = None
    depth_m: Optional[float] = None               # negative below sea level (GEBCO)
    in_sea: bool = True
    eez: Optional[str] = None
    in_indian_eez: Optional[bool] = None
    zones: list[ZoneHit] = Field(default_factory=list)
    nearest_port: Optional[dict[str, Any]] = None
    regulations: list[dict[str, Any]] = Field(default_factory=list)


class RouteSegment(BaseModel):
    index: int
    start: GeoPoint
    end: GeoPoint
    distance_km: float
    eta_start: datetime
    eta_end: datetime
    risk: float                    # 0..1
    level: RiskLevel
    wave_height_m: Optional[float] = None
    wind_kmh: Optional[float] = None
    current_kmh: Optional[float] = None
    drivers: list[str] = Field(default_factory=list)


class RouteOption(BaseModel):
    id: str                        # shortest | safest | recommended
    label: str
    coordinates: list[list[float]]   # [[lon, lat], ...]
    distance_km: float
    distance_nm: float
    duration_h: float
    departure: datetime
    arrival: datetime
    max_risk: float
    mean_risk: float
    exposure: float                # integral of risk over distance (km)
    level: RiskLevel
    segments: list[RouteSegment]
    zone_violations: list[ZoneHit] = Field(default_factory=list)
    boundary_min_distance_km: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)


class RouteResult(BaseModel):
    origin: GeoPoint
    destination: GeoPoint
    origin_name: str
    destination_name: str
    speed_kn: float
    options: list[RouteOption]
    recommended_id: str
    algorithm: str
    grid_resolution_deg: float
    cost_model: str
    nodes_expanded: int = 0
    notes: list[str] = Field(default_factory=list)


class CandidateZone(BaseModel):
    id: str
    centroid: GeoPoint
    polygon: list[list[float]]     # ring [[lon, lat], ...]
    area_km2: float
    score: float                    # 0..1 ORCA productivity indicator
    mean_sst_c: Optional[float] = None
    max_front_gradient_c_per_km: Optional[float] = None
    mean_chl_mg_m3: Optional[float] = None
    depth_m: Optional[float] = None
    distance_from_origin_km: Optional[float] = None
    bearing_from_origin_deg: Optional[float] = None
    rationale: list[str] = Field(default_factory=list)
    official: bool = False          # True only for INCOIS PFZ advisories


class Alert(BaseModel):
    id: str
    created_at: datetime
    severity: str                   # info | warning | severe
    category: str                   # cyclone | waves | wind | lightning | geofence | boundary | change | source
    title: str
    message: str
    region: str
    location: Optional[GeoPoint] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    level: RiskLevel = RiskLevel.CAUTION
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    verified: bool = False
    verification: str = ""
    mode: str = "LIVE"
    status: str = "active"          # active | acknowledged | expired
    trace_id: Optional[str] = None
    dedup_key: str = ""
