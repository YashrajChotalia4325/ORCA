"""Provenance and data-carrying models.

Every value ORCA reasons over is wrapped with a `Provenance` record. The UI
renders these fields verbatim; nothing is allowed to reach a user without one.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .common import AuthorityTier, DataKind, DataMode, FreshnessStatus, GeoPoint


class Freshness(BaseModel):
    last_updated: Optional[datetime] = None        # product issue / valid time at the source
    retrieved_at: Optional[datetime] = None        # when ORCA obtained it
    expected_update_interval_s: Optional[int] = None
    expected_latency_s: Optional[int] = None       # typical delay between product time and availability
    age_s: Optional[float] = None                  # now - last_updated
    retrieval_age_s: Optional[float] = None        # now - retrieved_at
    from_cache: bool = False
    status: FreshnessStatus = FreshnessStatus.UNAVAILABLE
    label: str = ""                                # human string, e.g. "fetched 3 min ago · run 06Z"
    factor: float = 0.0                            # multiplier used by the confidence model


class Provenance(BaseModel):
    source: str                                    # human-readable producer, e.g. "ECMWF WAM"
    source_id: str                                 # ORCA connector id
    organization: str                              # producing organisation
    distributor: Optional[str] = None              # e.g. "Open-Meteo" when redistributed
    authority_tier: AuthorityTier
    dataset: str
    variable: str
    kind: DataKind
    timestamp: Optional[datetime] = None           # valid time of the value / product
    issued_at: Optional[datetime] = None           # model run initialisation / bulletin issue time
    retrieval_timestamp: Optional[datetime] = None
    spatial_resolution: str = ""
    temporal_resolution: str = ""
    units: str = ""
    geographic_extent: Optional[list[float]] = None  # bbox [lon_min, lat_min, lon_max, lat_max]
    freshness: Freshness = Field(default_factory=Freshness)
    confidence: float = 0.0                        # source quality weight in [0,1] (see REASONING.md)
    source_url: str = ""                           # request URL with credentials stripped
    license: str = ""
    status: str = "OK"
    mode: DataMode = DataMode.LIVE
    notes: list[str] = Field(default_factory=list)


class TimeSeries(BaseModel):
    variable: str
    units: str
    location: GeoPoint                             # requested location
    grid_location: Optional[GeoPoint] = None       # actual model/product cell centre used
    times: list[datetime]
    values: list[Optional[float]]
    provenance: Provenance

    def window(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        return [(t, v) for t, v in zip(self.times, self.values) if start <= t <= end and v is not None]

    def at(self, t: datetime) -> Optional[float]:
        """Linear interpolation in time; None outside coverage or across gaps."""
        if not self.times:
            return None
        if t <= self.times[0]:
            return self.values[0] if t == self.times[0] else None
        for i in range(1, len(self.times)):
            t0, t1 = self.times[i - 1], self.times[i]
            if t0 <= t <= t1:
                v0, v1 = self.values[i - 1], self.values[i]
                if v0 is None or v1 is None:
                    return v0 if t == t0 else (v1 if t == t1 else None)
                span = (t1 - t0).total_seconds()
                w = 0 if span == 0 else (t - t0).total_seconds() / span
                return v0 + (v1 - v0) * w
        return None


class GridField(BaseModel):
    """A 2-D snapshot (or hourly stack) on a regular lat/lon grid."""
    variable: str
    units: str
    lats: list[float]
    lons: list[float]
    times: list[datetime]
    # values[t][i][j] with i over lats and j over lons; None = no data (land / missing)
    values: list[list[list[Optional[float]]]]
    provenance: Provenance


class PointValue(BaseModel):
    variable: str
    value: Optional[float]
    units: str
    location: GeoPoint
    grid_location: Optional[GeoPoint] = None
    valid_time: Optional[datetime] = None
    provenance: Provenance


class SourceFailure(BaseModel):
    source_id: str
    source: str
    reason: str
    status: str                  # DOWN | TIMEOUT | HTTP_5xx | CREDENTIALS_REQUIRED | NOT_IN_RECORDING ...
    at: datetime
    impact: str = ""             # what ORCA excluded because of this
