"use client";
import Link from "next/link";
import { useState } from "react";
import { AGENT_LABEL, fmtVal, ist, LEVEL, utc } from "@/lib/format";
import { useOrca } from "@/lib/store";
import type { Blackboard, Conflict, RiskFactor } from "@/lib/types";
import EvidenceDrawer from "./EvidenceDrawer";
import { ConfidenceRing, DecisionBadge, FreshTag, LevelTag, ModelChart, Section } from "./primitives";

const FACTOR_VAR: Record<string, { agent: "ocean" | "weather"; v: string }> = {
  wave_height: { agent: "ocean", v: "wave_height" }, current_speed: { agent: "ocean", v: "current_speed" },
  wind_speed: { agent: "weather", v: "wind_speed" }, wind_gusts: { agent: "weather", v: "wind_gusts" },
  precipitation: { agent: "weather", v: "precipitation" }, cape: { agent: "weather", v: "cape" }, visibility: { agent: "weather", v: "visibility" },
};
const MODEL_NAME: Record<string, string> = {
  om_mfwam: "MFWAM", om_ecmwf_wam: "ECMWF WAM", om_gfs_wave: "GFS-Wave", om_dwd_gwam: "DWD GWAM", om_smoc: "SMOC",
  om_ecmwf_ifs: "ECMWF IFS", om_gfs: "GFS", om_icon: "ICON", om_ukmo: "UKMO",
};

function FactorRow({ f, bb }: { f: RiskFactor; bb: Blackboard }) {
  const [open, setOpen] = useState(false);
  const fv = FACTOR_VAR[f.id];
  const series = fv ? bb.outputs[fv.agent]?.primary_series?.[fv.v] as Record<string, { times: string[]; values: (number | null)[] }> | undefined : undefined;
  const tw = bb.understanding?.time_window;
  const evidence = bb.evidence.filter((e) => e.claim_id === `C_${f.id}`);
  return (
    <div className="border-t border-line first:border-t-0">
      <button onClick={() => setOpen(!open)} className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-3 py-1.5 text-left hover:bg-panel-2/60" aria-expanded={open}>
        <span className="text-[12.5px] text-ink">{f.label}{f.critical && <span className="ml-1.5 text-[9.5px] text-ink-3">CRITICAL</span>}</span>
        <span className="num text-[12px] text-ink">{f.available ? (f.id === "cyclone_distance" && f.value === null ? "none active" : fmtVal(f.value, f.units)) : "unavailable"}</span>
        <span className="w-[76px] text-right"><LevelTag level={f.level} /></span>
      </button>
      {open && (
        <div className="rise pb-3 pl-1 text-[11.5px] text-ink-2">
          <p className="mb-1.5 leading-snug">{f.explanation}</p>
          {f.onset && <p className="mb-1.5">Caution level first reached <b className="text-ink">{ist(f.onset)}</b>.</p>}
          {series && Object.keys(series).length > 0 && (
            <ModelChart units={f.units}
              series={Object.entries(series).map(([sid, s]) => ({ name: MODEL_NAME[sid] ?? sid, times: s.times, values: s.values }))}
              threshold={f.threshold} window={tw ? [tw.start, tw.end] : null} />
          )}
          {evidence.length > 0 && (
            <table className="mt-2 w-full text-[11px]">
              <thead><tr className="text-ink-3"><th className="text-left font-normal">source</th><th className="text-right font-normal">worst</th><th className="text-right font-normal">at</th><th className="text-right font-normal">freshness</th></tr></thead>
              <tbody>{evidence.map((e) => (
                <tr key={e.id} className="border-t border-line/60">
                  <td className="py-0.5">{e.source}<span className="text-ink-3"> · {e.provenance.spatial_resolution}</span></td>
                  <td className="num py-0.5 text-right text-ink">{fmtVal(e.value ?? null, e.units)}</td>
                  <td className="num py-0.5 text-right">{ist(e.valid_time, false)}</td>
                  <td className="py-0.5 text-right"><FreshTag status={e.provenance.freshness.status} /></td>
                </tr>))}</tbody>
            </table>
          )}
          {f.threshold && <p className="mt-1.5 text-[10.5px] text-ink-3">Thresholds ({bb.risk?.vessel_class.replace("_", " ")}): caution {f.threshold.direction === "above" ? "≥" : "≤"} {f.threshold.caution}, danger {f.threshold.direction === "above" ? "≥" : "≤"} {f.threshold.danger} {f.threshold.units} · {f.threshold.basis}</p>}
        </div>
      )}
    </div>
  );
}

export function ConflictTable({ conflicts }: { conflicts: Conflict[] }) {
  return (
    <div className="flex flex-col gap-3">
      {conflicts.map((c) => (
        <div key={c.id} className="rounded border p-2.5" style={{ borderColor: c.decision_relevant ? "color-mix(in oklab, var(--caution) 45%, transparent)" : "var(--line-2)" }}>
          <div className="mb-1 flex items-center gap-2 text-[12px]">
            <span className="font-cond font-semibold tracking-wider" style={{ color: c.decision_relevant ? "var(--caution)" : "var(--ink-2)" }}>{c.decision_relevant ? "▲ DECISION-RELEVANT" : "● " + c.severity.toUpperCase()}</span>
            <span className="text-ink">{c.variable.replace("_", " ")}</span>
          </div>
          <table className="w-full text-[11px]">
            <thead><tr className="text-ink-3"><th className="text-left font-normal">Source</th><th className="text-right font-normal">Value</th><th className="text-right font-normal">Time</th><th className="text-right font-normal">Authority</th><th className="text-right font-normal">Level</th></tr></thead>
            <tbody>{c.entries.map((e, i) => (
              <tr key={i} className="border-t border-line/60">
                <td className="py-0.5 text-ink-2">{e.source}<span className="text-ink-3"> · {e.kind.toLowerCase()}</span></td>
                <td className="num py-0.5 text-right text-ink">{e.value !== null && e.value !== undefined ? `${e.value} ${e.units}` : e.value_text}</td>
                <td className="num py-0.5 text-right">{e.time ? ist(e.time, false) : "—"}</td>
                <td className="num py-0.5 text-right">{e.authority.toFixed(2)}</td>
                <td className="py-0.5 text-right">{e.level ? <LevelTag level={e.level} /> : "—"}</td>
              </tr>))}</tbody>
          </table>
          <p className="mt-1.5 text-[11px] text-ink-2"><span className="text-ink-3">Resolution: </span>{c.resolution}</p>
          <p className="text-[11px] text-ink-2"><span className="text-ink-3">Impact: </span>{c.impact}</p>
        </div>
      ))}
    </div>
  );
}

export function RouteSummary({ bb }: { bb: Blackboard }) {
  const r = bb.outputs.route?.route;
  if (!r) return null;
  const rec = r.options.find((o: { id: string }) => o.id === r.recommended_id);
  const W = 360, H = 54;
  const segs = rec?.segments ?? [];
  const total = segs.reduce((a: number, s: { distance_km: number }) => a + s.distance_km, 0) || 1;
  const starts: number[] = segs.reduce((arr: number[], _s: { distance_km: number }, i: number) => [...arr, i === 0 ? 0 : arr[i - 1] + segs[i - 1].distance_km], []);
  return (
    <div>
      <table className="w-full text-[11.5px]">
        <thead><tr className="text-ink-3"><th className="text-left font-normal">Option</th><th className="text-right font-normal">Distance</th><th className="text-right font-normal">Time</th><th className="text-right font-normal">Peak risk</th></tr></thead>
        <tbody>{r.options.map((o: { id: string; label: string; distance_km: number; distance_nm: number; duration_h: number; max_risk: number; level: keyof typeof LEVEL }) => (
          <tr key={o.id} className={`border-t border-line ${o.id === r.recommended_id ? "text-ink" : "text-ink-2"}`}>
            <td className="py-1">{o.id === r.recommended_id && <span className="text-accent">★ </span>}{o.label}</td>
            <td className="num py-1 text-right">{o.distance_km.toFixed(0)} km · {o.distance_nm.toFixed(0)} nm</td>
            <td className="num py-1 text-right">{o.duration_h.toFixed(1)} h</td>
            <td className="num py-1 text-right" style={{ color: LEVEL[o.level].color }}>{o.max_risk.toFixed(2)}</td>
          </tr>))}</tbody>
      </table>
      <div className="lbl mb-1 mt-2">Risk along recommended route (at ETA)</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="segment risk profile">
        <line x1="0" x2={W} y1={H - 12 - 0.5 * (H - 16)} y2={H - 12 - 0.5 * (H - 16)} stroke="var(--caution)" strokeDasharray="3 3" strokeWidth="1" opacity="0.6" />
        {segs.map((s: { index: number; distance_km: number; risk: number; level: keyof typeof LEVEL; eta_start: string; wave_height_m?: number; wind_kmh?: number }) => {
          const x = (starts[s.index] / total) * W; const w = Math.max(1, (s.distance_km / total) * W - 2);
          const h = Math.max(2, s.risk * (H - 16));
          return <rect key={s.index} x={x} y={H - 12 - h} width={w} height={h} rx="2" fill={LEVEL[s.level].color} opacity="0.85"><title>{`seg ${s.index}: risk ${s.risk} · Hs ${s.wave_height_m ?? "—"} m · wind ${s.wind_kmh ?? "—"} km/h · ETA ${ist(s.eta_start)}`}</title></rect>;
        })}
        <text x="0" y={H - 1} fontSize="9" fill="var(--ink-3)">{r.origin_name}</text>
        <text x={W} y={H - 1} fontSize="9" textAnchor="end" fill="var(--ink-3)">{r.destination_name}</text>
      </svg>
      {rec?.warnings?.map((w: string, i: number) => <p key={i} className="mt-1 text-[11.5px] text-caution">{w}</p>)}
      <p className="mt-1.5 text-[10.5px] text-ink-3">{r.algorithm} · grid {r.grid_resolution_deg}° · {r.nodes_expanded.toLocaleString()} nodes expanded · {r.speed_kn} kn</p>
    </div>
  );
}

export default function ResultCard({ bb }: { bb: Blackboard }) {
  const [drawer, setDrawer] = useState(false);
  const { flyTo } = useOrca();
  const fa = bb.final_assessment;
  const u = bb.understanding;
  const resp = bb.response;
  const risk = bb.risk;
  const sat = bb.outputs.satellite?.point_values as { variable: string; value: number; units: string; valid_time: string; provenance: { freshness: { status: never; label: string } } }[] | undefined;
  const agents = Object.values(bb.agents);
  const fish = bb.outputs.fisheries;
  const research = bb.outputs.research;
  const stations = bb.outputs.hazard?.stations as { label: string; decision: never; risk_index: number; worst_wave_m: number; worst_wind_kmh: number }[] | undefined;
  if (!fa) return <div className="p-4 text-[12px] text-danger">No assessment produced ({bb.status}).</div>;
  return (
    <div className="rise">
      <div className="flex items-start justify-between gap-3 px-4 pb-3 pt-3">
        <div className="min-w-0">
          <DecisionBadge decision={fa.decision} size="lg" />
          <p className="mt-2 text-[14px] leading-snug text-ink">{resp?.headline ?? fa.headline}</p>
          {resp?.summary && <p className="mt-1 text-[12px] text-ink-2">{resp.summary}</p>}
        </div>
        {fa.decision !== "INSUFFICIENT_DATA" && <ConfidenceRing value={fa.confidence} breakdown={fa.confidence_breakdown} />}
      </div>
      {fa.refusal_reason && <div className="mx-4 mb-3 rounded border border-na/40 bg-panel-2 p-2.5 text-[12px] text-ink">{fa.refusal_reason}</div>}

      {u && (
        <Section title="Understanding">
          <div className="flex flex-wrap gap-1.5 text-[11.5px]">
            <Chip k="intent" v={u.intent.replaceAll("_", " ").toLowerCase()} />
            {u.origin && u.destination ? <Chip k="route" v={`${u.origin.name} → ${u.destination.name}`} /> : u.places[0] && <Chip k="location" v={`${u.places[0].name}${u.offshore_km ? ` · ${u.offshore_km.toFixed(0)} km offshore` : ""}`} />}
            {u.region && <Chip k="region" v={u.region.name} />}
            {u.time_window && <Chip k="time" v={u.time_window.label} title={`${utc(u.time_window.start)} → ${utc(u.time_window.end)}`} />}
            <Chip k="vessel" v={u.vessel_class.replace("_", " ")} />
            <Chip k="role" v={u.role} />
            <Chip k="lang" v={`${u.language}${u.output_language !== u.language ? "→" + u.output_language : ""}`} />
            <Chip k="parse" v={`${u.parse_method} ${Math.round(u.parse_confidence * 100)}%`} />
          </div>
          {u.assumptions.length > 0 && <ul className="mt-2 list-inside list-disc text-[11px] text-ink-3">{u.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>}
        </Section>
      )}

      <Section title={`Agents activated · ${new Set(agents.map((a) => a.agent)).size}`} right={bb.plan.replans.length ? <span className="text-[10.5px] text-replay">{bb.plan.replans.length} re-plan(s)</span> : null}>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
          {agents.map((a) => (
            <div key={a.task_id} className="flex items-center justify-between text-[11.5px]" title={a.summary}>
              <span className="flex items-center gap-1.5 truncate">
                <span style={{ color: a.status === "FAILED" ? "var(--danger)" : a.status === "PARTIAL" ? "var(--caution)" : "var(--go)" }}>{a.status === "FAILED" ? "✕" : a.status === "PARTIAL" ? "◐" : "✓"}</span>
                <span className="text-ink-2">{AGENT_LABEL[a.agent] ?? a.agent}{a.round ? <sup className="text-replay"> #{a.round}</sup> : null}</span>
              </span>
              <span className="num text-[10.5px] text-ink-3">{a.duration_ms !== null && a.duration_ms !== undefined ? `${Math.round(a.duration_ms)} ms` : ""}</span>
            </div>
          ))}
        </div>
        {bb.plan.replans.map((r, i) => <p key={i} className="mt-1 text-[11px] text-replay">↻ {r.rule}: {r.detail}</p>)}
      </Section>

      {risk && (
        <Section title="Live evidence · conditions over the window" right={<span className="text-[10.5px] text-ink-3">worst case across sources & points</span>}>
          {risk.factors.map((f) => <FactorRow key={f.id} f={f} bb={bb} />)}
        </Section>
      )}

      {sat && sat.length > 0 && (
        <Section title="Satellite context">
          {sat.map((p) => (
            <div key={p.variable} className="flex items-center justify-between py-0.5 text-[12px]">
              <span className="text-ink-2">{({ sst: "SST (blended L4)", sst_anomaly: "SST anomaly", chlorophyll: "Chlorophyll-a (VIIRS)" } as Record<string, string>)[p.variable]}</span>
              <span className="num text-ink">{p.value.toFixed(2)} {p.units}</span>
              <span className="text-[10.5px] text-ink-3">product {p.valid_time.slice(0, 10)}</span>
            </div>
          ))}
        </Section>
      )}

      {bb.conflicts.length > 0 && <Section title={`Sources disagree · ${bb.conflicts.length}`}><ConflictTable conflicts={bb.conflicts} /></Section>}

      {bb.outputs.route && <Section title="Route intelligence"><RouteSummary bb={bb} /></Section>}

      {stations && stations.length > 0 && (
        <Section title="Coastal stations">
          {stations.map((s) => (
            <div key={s.label} className="flex items-center justify-between border-t border-line py-1 text-[11.5px] first:border-0">
              <span className="text-ink-2">{s.label}</span>
              <span className="num text-ink-3">Hs {s.worst_wave_m?.toFixed(1) ?? "—"} m · {s.worst_wind_kmh?.toFixed(0) ?? "—"} km/h</span>
              <DecisionBadge decision={s.decision} size="sm" />
            </div>
          ))}
        </Section>
      )}

      {fish && (
        <Section title="Fishing intelligence">
          {fish.zones.length === 0 && <p className="text-[11.5px] text-ink-3">No area met the indicator threshold ({fish.method}).</p>}
          {fish.zones.map((z: { id: string; score: number; distance_from_origin_km: number; rationale: string[]; centroid: { lat: number; lon: number } }) => (
            <button key={z.id} onClick={() => flyTo(z.centroid.lat, z.centroid.lon, 8.5)} className="mb-1.5 block w-full rounded border border-line-2 p-2 text-left hover:border-accent/60">
              <div className="flex justify-between text-[12px]"><span className="text-accent">{z.id}</span><span className="num text-ink">score {z.score.toFixed(2)} · {z.distance_from_origin_km.toFixed(0)} km</span></div>
              <div className="mt-0.5 text-[11px] text-ink-2">{z.rationale.join(" · ")}</div>
            </button>
          ))}
          <p className="text-[10.5px] text-ink-3">{fish.disclaimer} INCOIS PFZ: {fish.official_available ? `${fish.official_pfz.length} feature(s)` : fish.official_status}.</p>
        </Section>
      )}

      {research && (
        <Section title="Research findings">
          {research.findings.map((f: { epistemic: string; text: string; supporting: string[]; contradicting: string[]; status?: string }, i: number) => (
            <div key={i} className="mb-2 text-[12px]">
              <span className="mr-1.5 rounded-sm px-1.5 py-[1px] font-cond text-[9.5px] font-semibold tracking-wider"
                style={{ color: { OBSERVATION: "var(--accent-2)", CORRELATION: "var(--demo)", HYPOTHESIS: "var(--caution)", CONCLUSION: "var(--accent)" }[f.epistemic], border: "1px solid var(--line-2)" }}>{f.epistemic}</span>
              <span className="text-ink">{f.text}</span>{f.status && <span className="text-ink-3"> — {f.status}</span>}
              {(f.supporting.length > 0 || f.contradicting.length > 0) && (
                <ul className="ml-4 mt-0.5 text-[11px]">
                  {f.supporting.map((s, j) => <li key={j} className="text-go">+ {s}</li>)}
                  {f.contradicting.map((s, j) => <li key={j} className="text-serious">− {s}</li>)}
                </ul>)}
            </div>
          ))}
          {research.data_gaps?.length > 0 && <p className="text-[11px] text-ink-3">Gaps: {research.data_gaps.join("; ")}</p>}
        </Section>
      )}

      {fa.recommendations.length > 0 && (
        <Section title="Recommendations">
          <ol className="flex flex-col gap-1 text-[12.5px]">{fa.recommendations.map((r, i) => <li key={i} className="flex gap-2"><span className="num text-accent">{i + 1}</span><span className="text-ink">{r.text}</span></li>)}</ol>
        </Section>
      )}

      {fa.excluded_sources.length > 0 && (
        <Section title="Excluded / unavailable sources">
          <ul className="flex flex-col gap-1 text-[11.5px] text-ink-2">{fa.excluded_sources.map((s, i) => <li key={i}><span className="text-danger">✕</span> {s}</li>)}</ul>
        </Section>
      )}

      <Section title="Caveats">
        <ul className="flex flex-col gap-1 text-[11px] text-ink-3">{fa.caveats.map((c, i) => <li key={i}>· {c}</li>)}</ul>
      </Section>

      <div className="sticky bottom-0 flex items-center gap-2 border-t border-line bg-panel px-4 py-2.5">
        <button onClick={() => setDrawer(true)} className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-abyss hover:brightness-110">View evidence ({bb.evidence.length})</button>
        {bb.map?.center && <button onClick={() => flyTo(bb.map.center!.lat, bb.map.center!.lon, bb.map.zoom ?? 7.5)} className="rounded border border-line-2 px-3 py-1.5 text-[12px] text-ink-2 hover:text-ink">Show on map</button>}
        <Link href={`/agents?trace=${bb.trace_id}`} className="rounded border border-line-2 px-3 py-1.5 text-[12px] text-ink-2 hover:text-ink">Agent graph</Link>
        <span className="num ml-auto text-[10.5px] text-ink-3">{bb.trace_id}</span>
      </div>
      {drawer && <EvidenceDrawer bb={bb} onClose={() => setDrawer(false)} />}
    </div>
  );
}

function Chip({ k, v, title }: { k: string; v: string; title?: string }) {
  return <span title={title} className="rounded-sm border border-line-2 bg-panel-2 px-1.5 py-[2px]"><span className="text-ink-3">{k} </span><span className="text-ink">{v}</span></span>;
}
