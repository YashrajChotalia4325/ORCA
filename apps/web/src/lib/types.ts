// Mirrors of the ORCA backend schemas (apps/api/orca/core/schemas). Only fields the UI reads are typed.

export type DataMode = "LIVE" | "REPLAY" | "DEMO";
export type Decision = "GO" | "CAUTION" | "DONT_GO" | "INSUFFICIENT_DATA" | "NOT_APPLICABLE";
export type RiskLevel = "NOMINAL" | "CAUTION" | "DANGER" | "UNKNOWN";
export type FreshnessStatus = "LIVE" | "RECENT" | "STALE" | "UNAVAILABLE" | "REPLAY" | "SIMULATED" | "STATIC";

export interface GeoPoint { lat: number; lon: number }

export interface Freshness {
  last_updated?: string | null;
  retrieved_at?: string | null;
  age_s?: number | null;
  retrieval_age_s?: number | null;
  status: FreshnessStatus;
  label: string;
  factor: number;
  from_cache?: boolean;
}

export interface Provenance {
  source: string;
  source_id: string;
  organization: string;
  distributor?: string | null;
  authority_tier: string;
  dataset: string;
  variable: string;
  kind: string;
  timestamp?: string | null;
  issued_at?: string | null;
  retrieval_timestamp?: string | null;
  spatial_resolution: string;
  temporal_resolution: string;
  units: string;
  freshness: Freshness;
  confidence: number;
  source_url: string;
  license: string;
  mode: DataMode;
  notes: string[];
}

export interface ThresholdSpec { caution: number; danger: number; direction: string; units: string; basis: string }
export interface ModelValue { source: string; source_id: string; value: number | null; units: string; at?: string | null; level: RiskLevel; kind: string }

export interface RiskFactor {
  id: string; label: string; critical: boolean; level: RiskLevel; value: number | null; units: string;
  at?: string | null; location?: GeoPoint | null; threshold?: ThresholdSpec | null; score: number;
  per_source: ModelValue[]; spread?: number | null; onset?: string | null; explanation: string; available: boolean;
}

export interface RiskAssessment {
  decision: Decision; risk_index: number | null; vessel_class: string; window_start: string; window_end: string;
  factors: RiskFactor[]; drivers: string[]; rules_fired: string[]; missing_critical: string[];
  conservative_adjustments: string[]; model_version: string;
}

export interface ConfidenceBreakdown {
  evidence_quality: number; agreement: number; agreement_factor: number; completeness: number;
  independence: number; value: number; formula: string; weakest_link: string; notes: string[];
}

export interface EvidenceItem {
  id: string; claim_id: string; source: string; source_id: string; kind: string; variable: string;
  value?: number | null; value_text?: string | null; units: string; valid_time?: string | null;
  location?: GeoPoint | null; provenance: Provenance; supports?: boolean | null;
  authority: number; freshness: number; spatial: number; temporal: number; weight: number; lineage: string;
}

export interface Claim {
  id: string; text: string; category: string; factor_id?: string | null; level?: RiskLevel | null;
  evidence_ids: string[]; n_supporting: number; n_contradicting: number; n_sources: number;
  confidence?: ConfidenceBreakdown | null; epistemic: string; map_focus?: GeoPoint | null; time_focus?: string | null;
}

export interface ConflictEntry { source: string; source_id: string; value?: number | null; value_text?: string | null; units: string; time?: string | null; kind: string; authority: number; level?: RiskLevel | null }
export interface Conflict { id: string; variable: string; description: string; severity: string; entries: ConflictEntry[]; difference?: number | null; tolerance?: number | null; resolution: string; impact: string; decision_relevant: boolean }

export interface Recommendation { priority: number; text: string; basis: string[] }
export interface FinalAssessment {
  decision: Decision; headline: string; reasons: string[]; confidence: number;
  confidence_breakdown?: ConfidenceBreakdown | null; recommendations: Recommendation[]; caveats: string[];
  excluded_sources: string[]; refusal_reason?: string | null; metrics: Record<string, unknown>;
}

export interface TimeWindow { start: string; end: string; label: string; rule: string; assumptions: string[] }
export interface Place { id: string; name: string; kind: string; point: GeoPoint; state?: string | null; bbox?: { lon_min: number; lat_min: number; lon_max: number; lat_max: number } | null }

export interface Understanding {
  intent: string; secondary_intents: string[]; role: string; language: string; output_language: string;
  activity?: string | null; places: Place[]; origin?: Place | null; destination?: Place | null; region?: Place | null;
  offshore_km?: number | null; radius_km?: number | null; time_window?: TimeWindow | null;
  comparison_window?: TimeWindow | null; vessel_class: string; variables: string[]; safety_critical: boolean;
  assumptions: string[]; parse_method: string; parse_confidence: number; clarification_needed?: string | null;
}

export interface PlanTask { id: string; agent: string; params: Record<string, unknown>; depends_on: string[]; reason: string; round: number; critical: boolean }
export interface SourceFailure { source_id: string; source: string; reason: string; status: string; at: string; impact: string }

export interface AgentRecord {
  task_id: string; agent: string; title: string; status: "PENDING" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "SKIPPED";
  round: number; started_at?: string | null; ended_at?: string | null; duration_ms?: number | null;
  tools_used: string[]; sources_used: string[]; failures: SourceFailure[]; confidence?: number | null;
  summary: string; output?: Record<string, unknown> | null; error?: string | null; warnings: string[];
}

export interface TraceEvent { seq: number; at: string; type: string; agent?: string | null; task_id?: string | null; stage?: string | null; message: string; data: Record<string, unknown> }

export interface LocalizedResponse { language: string; role: string; headline: string; summary: string; sections: Section[]; renderer: string; grounding_check?: Record<string, unknown> | null }
export interface Section { id: string; title: string; items?: string[]; detail?: string[]; table?: Record<string, unknown>[]; assumptions?: string[]; findings?: ResearchFinding[]; gaps?: string[]; notes?: string[]; disclaimer?: string; official?: string; algorithm?: string }
export interface ResearchFinding { epistemic: string; text: string; variable?: string | null; stats: Record<string, unknown>; supporting: string[]; contradicting: string[]; status?: string | null }

export interface RouteSegment { index: number; start: GeoPoint; end: GeoPoint; distance_km: number; eta_start: string; eta_end: string; risk: number; level: RiskLevel; wave_height_m?: number | null; wind_kmh?: number | null; current_kmh?: number | null; drivers: string[] }
export interface RouteOption { id: string; label: string; coordinates: number[][]; distance_km: number; distance_nm: number; duration_h: number; departure: string; arrival: string; max_risk: number; mean_risk: number; exposure: number; level: RiskLevel; segments: RouteSegment[]; zone_violations: { name: string; note: string }[]; boundary_min_distance_km?: number | null; warnings: string[] }
export interface RouteResult { origin: GeoPoint; destination: GeoPoint; origin_name: string; destination_name: string; speed_kn: number; options: RouteOption[]; recommended_id: string; algorithm: string; grid_resolution_deg: number; cost_model: string; nodes_expanded: number; notes: string[] }

export interface Alert {
  id: string; created_at: string; severity: string; category: string; title: string; message: string; region: string;
  location?: GeoPoint | null; valid_from?: string | null; valid_to?: string | null; level: RiskLevel;
  evidence: Record<string, unknown>[]; verified: boolean; verification: string; mode: DataMode; status: string; trace_id?: string | null;
}

export interface MapDirective { center?: GeoPoint | null; zoom?: number | null; layers: string[]; time?: string | null; features: Record<string, GeoJSON.FeatureCollection> }

export interface Blackboard {
  query_id: string; trace_id: string; conversation_id: string; created_at: string; virtual_now: string; mode: DataMode;
  request: { text: string }; status: string; stage: string; understanding?: Understanding | null;
  plan: { tasks: PlanTask[]; rationale: string[]; replans: { rule: string; round: number; detail: string }[] };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- heterogeneous typed agent outputs (see backend schemas)
  agents: Record<string, AgentRecord>; outputs: Record<string, any>; evidence: EvidenceItem[]; claims: Claim[];
  conflicts: Conflict[]; failures: SourceFailure[]; risk?: RiskAssessment | null; alerts: Alert[];
  engine?: string; supersteps?: { wave: number; round: number; tasks: string[]; agents: string[] }[];
  final_assessment?: FinalAssessment | null; response?: LocalizedResponse | null; map: MapDirective;
  events: TraceEvent[]; timings: Record<string, number>; llm_usage: Record<string, number>; completed_at?: string | null;
}

export interface Scenario { id: string; title: string; description: string; query: string; queries: string[]; focus: { lat: number; lon: number; zoom: number }; demonstrates: string[]; now: string; failures: Record<string, string>; has_cyclone: boolean }

export interface SourceRow {
  id: string; name: string; organization: string; distributor?: string | null; authority_tier: string; authority_weight: number;
  integration: string; access: string; auth_env: string[]; configured: boolean; status: string; homepage: string; docs_url: string;
  license: string; rate_limit: string; notes: string[]; role?: string | null;
  datasets: { id: string; title: string; variables: string[]; kind: string; spatial_resolution: string; temporal_resolution: string; update_interval_s?: number | null; expected_latency_s?: number | null; coverage: string }[];
  health?: { calls: number; successes: number; failures: number; cache_hits: number; latency_p50_ms?: number | null; latency_p95_ms?: number | null; circuit: string; last_success?: string | null; last_error?: string | null; success_rate?: number | null } | null;
  probe?: { status: string; detail: string; at: string; probe_ms?: number; issued_at?: string } | null;
}

export interface AgentInfo { name: string; title: string; responsibility: string; tools: string[]; consumes: string[]; deterministic: boolean; output_schema?: unknown }
