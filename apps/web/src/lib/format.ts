import type { Decision, FreshnessStatus, RiskLevel } from "./types";

const IST = "Asia/Kolkata";

export function ist(iso?: string | null, withDate = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-GB", { timeZone: IST, day: "2-digit", month: "short" });
  const time = d.toLocaleTimeString("en-GB", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
  return withDate ? `${date} ${time} IST` : `${time} IST`;
}

export function utc(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toISOString().slice(0, 16).replace("T", " ")}Z`;
}

export function ago(iso?: string | null, now = Date.now()): string {
  if (!iso) return "—";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h ago`;
  return `${(s / 86400).toFixed(1)} d ago`;
}

export function fmtVal(v: number | null | undefined, units = "", nd = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (units === "km/h") return `${v.toFixed(0)} km/h · ${(v / 1.852).toFixed(0)} kn`;
  if (units === "km") return `${v.toFixed(1)} km · ${(v / 1.852).toFixed(1)} nm`;
  const d = Math.abs(v) >= 100 ? 0 : nd;
  return `${v.toFixed(d)}${units ? ` ${units}` : ""}`;
}

export const pct = (v?: number | null) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

export const DECISION: Record<Decision, { label: string; color: string; glyph: string; short: string }> = {
  GO: { label: "GO", short: "GO", color: "var(--go)", glyph: "●" },
  CAUTION: { label: "CAUTION", short: "CAUTION", color: "var(--caution)", glyph: "▲" },
  DONT_GO: { label: "DON'T GO", short: "DON'T GO", color: "var(--danger)", glyph: "■" },
  INSUFFICIENT_DATA: { label: "NO RELIABLE ASSESSMENT", short: "NO ASSESSMENT", color: "var(--na)", glyph: "◇" },
  NOT_APPLICABLE: { label: "ANALYSIS", short: "ANALYSIS", color: "var(--accent)", glyph: "◆" },
};

export const LEVEL: Record<RiskLevel, { label: string; color: string; glyph: string }> = {
  NOMINAL: { label: "normal", color: "var(--go)", glyph: "●" },
  CAUTION: { label: "caution", color: "var(--caution)", glyph: "▲" },
  DANGER: { label: "danger", color: "var(--danger)", glyph: "■" },
  UNKNOWN: { label: "no data", color: "var(--na)", glyph: "◇" },
};

export const FRESH: Record<FreshnessStatus, { label: string; color: string }> = {
  LIVE: { label: "LIVE", color: "var(--live)" },
  RECENT: { label: "RECENT", color: "#7fd4a8" },
  STALE: { label: "STALE", color: "var(--serious)" },
  UNAVAILABLE: { label: "UNAVAILABLE", color: "var(--danger)" },
  REPLAY: { label: "REPLAY", color: "var(--replay)" },
  SIMULATED: { label: "SIMULATED", color: "var(--demo)" },
  STATIC: { label: "STATIC", color: "var(--ink-3)" },
};

export const SOURCE_STATUS: Record<string, { label: string; color: string }> = {
  OPERATIONAL: { label: "OPERATIONAL", color: "var(--live)" },
  DEGRADED: { label: "DEGRADED", color: "var(--caution)" },
  DOWN: { label: "DOWN", color: "var(--danger)" },
  CREDENTIALS_REQUIRED: { label: "CREDENTIALS REQUIRED", color: "var(--ink-3)" },
  NO_PUBLIC_API: { label: "NO PUBLIC API", color: "var(--ink-3)" },
  NOT_CONFIGURED: { label: "NOT CONFIGURED", color: "var(--ink-3)" },
  STATIC: { label: "STATIC REFERENCE", color: "var(--accent-2)" },
  UNKNOWN: { label: "UNKNOWN", color: "var(--na)" },
};

export const AGENT_LABEL: Record<string, string> = {
  planner: "Planner", geospatial: "Geospatial", ocean: "Oceanography", weather: "Weather", satellite: "Satellite EO",
  advisory: "Advisories", fisheries: "Fisheries", hazard: "Hazard & Risk", route: "Route", research: "Research",
  evidence: "Evidence", communication: "Communication", alert: "Alerts",
};

export const STAGES = ["INTENT", "LOCATION_TIME", "PLANNING", "AGENT_SELECTION", "RETRIEVAL", "NORMALIZATION", "ALIGNMENT",
  "CORRELATION", "CONFLICTS", "REASONING", "VERIFICATION", "CONFIDENCE", "DECISION", "EXPLANATION", "VISUALIZATION", "RESPONSE"];
export const STAGE_LABEL: Record<string, string> = {
  INTENT: "Intent", LOCATION_TIME: "Where / when", PLANNING: "Plan", AGENT_SELECTION: "Agents", RETRIEVAL: "Retrieve",
  NORMALIZATION: "Normalise", ALIGNMENT: "Align", CORRELATION: "Correlate", CONFLICTS: "Conflicts", REASONING: "Reason",
  VERIFICATION: "Verify", CONFIDENCE: "Confidence", DECISION: "Decide", EXPLANATION: "Explain", VISUALIZATION: "Visualise", RESPONSE: "Respond",
};
