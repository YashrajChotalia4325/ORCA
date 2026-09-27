"""Risk, evidence, conflict and confidence models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .common import DataKind, Decision, GeoPoint, RiskLevel
from .provenance import Provenance


class ThresholdSpec(BaseModel):
    caution: float
    danger: float
    direction: str = "above"   # "above": higher is worse; "below": lower is worse (visibility)
    units: str = ""
    basis: str = ""            # where the threshold comes from


class ModelValue(BaseModel):
    """Worst-case value a single source reports for a factor inside the window."""
    source: str
    source_id: str
    value: Optional[float]
    units: str
    at: Optional[datetime] = None
    location: Optional[GeoPoint] = None
    level: RiskLevel = RiskLevel.UNKNOWN
    kind: DataKind = DataKind.FORECAST


class RiskFactor(BaseModel):
    id: str                       # wind_speed, wave_height, cyclone_proximity, ...
    label: str
    critical: bool                # missing critical factor => INSUFFICIENT_DATA
    level: RiskLevel
    value: Optional[float] = None  # the value used for the decision (conservative)
    units: str = ""
    at: Optional[datetime] = None
    location: Optional[GeoPoint] = None
    threshold: Optional[ThresholdSpec] = None
    score: float = 0.0            # 0..1 normalised exceedance used for heatmaps
    per_source: list[ModelValue] = Field(default_factory=list)
    spread: Optional[float] = None  # max-min across sources
    onset: Optional[datetime] = None  # first time the level (>= CAUTION) is reached
    explanation: str = ""
    available: bool = True


class RiskAssessment(BaseModel):
    decision: Decision
    risk_index: Optional[float]   # 0..100; None when INSUFFICIENT_DATA
    vessel_class: str
    window_start: datetime
    window_end: datetime
    factors: list[RiskFactor]
    drivers: list[str]            # factor ids that drove the decision
    rules_fired: list[str]        # human-readable decision rules applied
    missing_critical: list[str] = Field(default_factory=list)
    conservative_adjustments: list[str] = Field(default_factory=list)
    model_version: str = "orca-risk-1.0"


class EvidenceItem(BaseModel):
    id: str
    claim_id: str
    source: str
    source_id: str
    kind: DataKind
    variable: str
    value: Optional[float] = None
    value_text: Optional[str] = None
    units: str = ""
    valid_time: Optional[datetime] = None
    location: Optional[GeoPoint] = None
    provenance: Provenance
    supports: Optional[bool] = None     # True supports, False contradicts, None neutral
    # confidence components for this item
    authority: float = 0.0
    freshness: float = 0.0
    spatial: float = 0.0
    temporal: float = 0.0
    weight: float = 0.0
    lineage: str = ""                   # independence grouping key


class ConfidenceBreakdown(BaseModel):
    evidence_quality: float
    agreement: float
    agreement_factor: float
    completeness: float
    independence: float
    value: float
    formula: str
    weakest_link: str = ""
    notes: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    id: str
    text: str
    category: str                 # risk | environment | fisheries | geospatial | research | route
    factor_id: Optional[str] = None
    level: Optional[RiskLevel] = None
    evidence_ids: list[str] = Field(default_factory=list)
    n_supporting: int = 0
    n_contradicting: int = 0
    n_sources: int = 0
    confidence: Optional[ConfidenceBreakdown] = None
    epistemic: str = "OBSERVATION"  # OBSERVATION | FORECAST | CORRELATION | HYPOTHESIS | CONCLUSION
    map_focus: Optional[GeoPoint] = None
    time_focus: Optional[datetime] = None


class ConflictEntry(BaseModel):
    source: str
    source_id: str
    value: Optional[float] = None
    value_text: Optional[str] = None
    units: str = ""
    time: Optional[datetime] = None
    kind: DataKind
    authority: float
    level: Optional[RiskLevel] = None


class Conflict(BaseModel):
    id: str
    variable: str
    description: str
    severity: str                 # minor | material | decision_relevant
    entries: list[ConflictEntry]
    difference: Optional[float] = None
    tolerance: Optional[float] = None
    resolution: str               # how ORCA handled it
    impact: str                   # effect on the decision / confidence
    decision_relevant: bool = False


class Recommendation(BaseModel):
    priority: int
    text: str
    basis: list[str] = Field(default_factory=list)   # claim ids / factor ids


class FinalAssessment(BaseModel):
    decision: Decision
    headline: str
    reasons: list[str]
    confidence: float
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    excluded_sources: list[str] = Field(default_factory=list)
    refusal_reason: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
