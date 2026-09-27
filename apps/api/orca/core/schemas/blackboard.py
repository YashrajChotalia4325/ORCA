"""Query, plan, agent-record and blackboard models.

The blackboard is the single shared state every agent reads from and writes
to. Agents never exchange free text: they publish typed outputs under their
own key and consume other agents' typed outputs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .assessment import Claim, Conflict, EvidenceItem, FinalAssessment, RiskAssessment
from .common import (AgentStatus, DataMode, GeoPoint, Intent, Place, TimeWindow,
                     UserRole, VesselClass)
from .geo import Alert, RouteResult
from .provenance import SourceFailure


class QueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    role: Optional[UserRole] = None
    language: Optional[str] = Field(default=None, max_length=8)   # force output language (ISO 639-1)
    mode: Optional[DataMode] = None
    vessel_class: Optional[VesselClass] = None
    location: Optional[GeoPoint] = None                           # map click / GPS, overrides text
    speed_kn: Optional[float] = Field(default=None, gt=0, le=40)


class Understanding(BaseModel):
    intent: Intent
    secondary_intents: list[Intent] = Field(default_factory=list)
    role: UserRole
    language: str                       # detected input language
    output_language: str
    activity: Optional[str] = None      # fishing | sailing | transit | research | monitoring
    places: list[Place] = Field(default_factory=list)
    origin: Optional[Place] = None
    destination: Optional[Place] = None
    region: Optional[Place] = None
    offshore_km: Optional[float] = None
    radius_km: Optional[float] = None
    time_window: Optional[TimeWindow] = None
    comparison_window: Optional[TimeWindow] = None
    vessel_class: VesselClass = VesselClass.SMALL_CRAFT
    variables: list[str] = Field(default_factory=list)
    safety_critical: bool = False
    assumptions: list[str] = Field(default_factory=list)
    parse_method: str = "rules"         # rules | llm | rules+context
    parse_confidence: float = 0.0
    clarification_needed: Optional[str] = None
    inherited_from: Optional[str] = None  # previous query id when context carried over


class PlanTask(BaseModel):
    id: str
    agent: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    reason: str = ""
    round: int = 0
    critical: bool = False


class ExecutionPlan(BaseModel):
    tasks: list[PlanTask] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    replans: list[dict[str, Any]] = Field(default_factory=list)


class AgentRecord(BaseModel):
    task_id: str
    agent: str
    title: str
    status: AgentStatus = AgentStatus.PENDING
    round: int = 0
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    tools_used: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    failures: list[SourceFailure] = Field(default_factory=list)
    confidence: Optional[float] = None
    summary: str = ""
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    seq: int
    at: datetime
    type: str            # stage | plan | agent_start | agent_end | tool | replan | evidence | conflict | decision | error | done
    agent: Optional[str] = None
    task_id: Optional[str] = None
    stage: Optional[str] = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class MapDirective(BaseModel):
    """Instructions for the frontend map derived from the result (not free-form)."""
    center: Optional[GeoPoint] = None
    zoom: Optional[float] = None
    layers: list[str] = Field(default_factory=list)
    time: Optional[datetime] = None
    features: dict[str, Any] = Field(default_factory=dict)   # layer_id -> GeoJSON FeatureCollection


class LocalizedResponse(BaseModel):
    language: str
    role: UserRole
    headline: str
    summary: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    renderer: str = "template"          # template | llm(<model>)
    grounding_check: Optional[dict[str, Any]] = None


class Blackboard(BaseModel):
    query_id: str
    trace_id: str
    conversation_id: str
    created_at: datetime
    virtual_now: datetime               # clock used for reasoning (real now in LIVE)
    mode: DataMode
    request: QueryRequest
    status: str = "running"             # running | complete | failed
    stage: str = "INTENT"
    understanding: Optional[Understanding] = None
    plan: ExecutionPlan = Field(default_factory=ExecutionPlan)
    agents: dict[str, AgentRecord] = Field(default_factory=dict)   # keyed by task id
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)  # agent name -> serialised output
    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    failures: list[SourceFailure] = Field(default_factory=list)
    risk: Optional[RiskAssessment] = None
    route: Optional[RouteResult] = None
    alerts: list[Alert] = Field(default_factory=list)
    final_assessment: Optional[FinalAssessment] = None
    response: Optional[LocalizedResponse] = None
    map: MapDirective = Field(default_factory=MapDirective)
    events: list[TraceEvent] = Field(default_factory=list)
    engine: str = "langgraph"           # orchestration engine
    supersteps: list[dict[str, Any]] = Field(default_factory=list)  # LangGraph waves: which tasks ran in parallel
    timings: dict[str, float] = Field(default_factory=dict)
    llm_usage: dict[str, int] = Field(default_factory=dict)
    completed_at: Optional[datetime] = None
