"use client";
import { useState } from "react";
import { DECISION, FRESH, LEVEL, pct } from "@/lib/format";
import type { ConfidenceBreakdown, Decision, FreshnessStatus, RiskLevel } from "@/lib/types";

export function DecisionBadge({ decision, size = "md" }: { decision: Decision; size?: "sm" | "md" | "lg" }) {
  const d = DECISION[decision];
  const cls = size === "lg" ? "px-3.5 py-1.5 text-[17px]" : size === "sm" ? "px-2 py-[1px] text-[11px]" : "px-2.5 py-1 text-[13px]";
  return (
    <span className={`inline-flex items-center gap-2 rounded font-cond font-semibold tracking-[0.12em] ${cls}`}
      style={{ color: d.color, background: `color-mix(in oklab, ${d.color} 14%, transparent)`, border: `1px solid color-mix(in oklab, ${d.color} 45%, transparent)` }}>
      <span aria-hidden>{d.glyph}</span>{d.label}
    </span>
  );
}

export function LevelTag({ level }: { level: RiskLevel }) {
  const l = LEVEL[level];
  return <span className="inline-flex items-center gap-1 font-cond text-[10.5px] font-semibold uppercase tracking-[0.1em]" style={{ color: l.color }}><span aria-hidden>{l.glyph}</span>{l.label}</span>;
}

export function FreshTag({ status, label }: { status: FreshnessStatus; label?: string }) {
  const f = FRESH[status] ?? FRESH.STATIC;
  return (
    <span className="inline-flex items-center gap-1.5 text-[10.5px]" title={label}>
      <span className={`h-1.5 w-1.5 rounded-full ${status === "LIVE" ? "pulse" : ""}`} style={{ background: f.color }} />
      <span className="font-cond font-semibold tracking-[0.1em]" style={{ color: f.color }}>{f.label}</span>
      {label && <span className="text-ink-3">{label}</span>}
    </span>
  );
}

export function ConfidenceRing({ value, breakdown }: { value: number; breakdown?: ConfidenceBreakdown | null }) {
  const [open, setOpen] = useState(false);
  const r = 17, c = 2 * Math.PI * r;
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2" aria-expanded={open} title="How confidence is computed">
        <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden>
          <circle cx="22" cy="22" r={r} stroke="var(--line-2)" strokeWidth="4" fill="none" />
          <circle cx="22" cy="22" r={r} stroke="var(--accent)" strokeWidth="4" fill="none" strokeLinecap="round"
            strokeDasharray={`${c * value} ${c}`} transform="rotate(-90 22 22)" />
        </svg>
        <div className="text-left">
          <div className="num text-[18px] leading-none text-ink">{pct(value)}</div>
          <div className="lbl mt-0.5">confidence ⓘ</div>
        </div>
      </button>
      {open && breakdown && (
        <div className="rise absolute right-0 top-12 z-30 w-[330px] rounded-md border border-line-2 bg-panel p-3 text-[12px] shadow-2xl">
          <div className="lbl mb-1">Transparent confidence</div>
          <div className="num mb-2 text-[11px] text-accent">{breakdown.formula}</div>
          <table className="w-full text-[11.5px]">
            <tbody>
              {[["Evidence quality Q", breakdown.evidence_quality], ["Agreement G", breakdown.agreement], ["Agreement factor 0.5+0.5G", breakdown.agreement_factor],
                ["Completeness C", breakdown.completeness], ["Independence", breakdown.independence]].map(([k, v]) => (
                <tr key={k as string} className="border-t border-line"><td className="py-1 text-ink-2">{k}</td>
                  <td className="py-1"><div className="h-1.5 w-24 rounded bg-line"><div className="h-1.5 rounded bg-accent-2" style={{ width: `${Math.min(1, v as number) * 100}%` }} /></div></td>
                  <td className="num py-1 text-right">{(v as number).toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 text-[11px] text-ink-2"><span className="text-ink-3">Weakest link: </span>{breakdown.weakest_link}</div>
          {breakdown.notes.map((n, i) => <div key={i} className="text-[11px] text-ink-3">· {n}</div>)}
          <div className="mt-1.5 text-[10.5px] text-ink-3">Per item: w = authority × freshness × spatial match × temporal match. See docs/REASONING.md.</div>
        </div>
      )}
    </div>
  );
}

const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];

export interface Series { name: string; times: string[]; values: (number | null)[] }

/** Multi-model line chart: one axis, 2px lines, crosshair tooltip, legend + direct end labels (≤4 series). */
export function ModelChart({ series, units, threshold, window, height = 92 }: {
  series: Series[]; units: string; threshold?: { caution: number; danger: number; direction: string } | null;
  window?: [string, string] | null; height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 360, H = height, pl = 30, pr = 8, pt = 6, pb = 16;
  const all = series.flatMap((s) => s.times.map((t, i) => [new Date(t).getTime(), s.values[i]] as const)).filter(([, v]) => v !== null) as [number, number][];
  if (!all.length) return <div className="text-[11px] text-ink-3">no series</div>;
  const t0 = Math.min(...all.map((a) => a[0])), t1 = Math.max(...all.map((a) => a[0]));
  const v0 = Math.min(0, ...all.map((a) => a[1]));
  let v1 = Math.max(...all.map((a) => a[1]));
  if (threshold && threshold.direction === "above") v1 = Math.max(v1, threshold.caution * 1.05);
  if (v1 === v0) v1 = v0 + 1;
  const x = (t: number) => pl + ((t - t0) / Math.max(1, t1 - t0)) * (W - pl - pr);
  const y = (v: number) => pt + (1 - (v - v0) / (v1 - v0)) * (H - pt - pb);
  const ticks = [v0, (v0 + v1) / 2, v1];
  const times = [...new Set(all.map((a) => a[0]))].sort((a, b) => a - b);
  const hoverT = hover !== null ? times[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`chart ${units}`}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const tx = t0 + ((e.clientX - r.left) / r.width * W - pl) / (W - pl - pr) * (t1 - t0);
          let bi = 0; times.forEach((t, i) => { if (Math.abs(t - tx) < Math.abs(times[bi] - tx)) bi = i; });
          setHover(bi);
        }} onMouseLeave={() => setHover(null)}>
        {window && <rect x={x(new Date(window[0]).getTime())} y={pt} width={Math.max(0, x(new Date(window[1]).getTime()) - x(new Date(window[0]).getTime()))} height={H - pt - pb} fill="var(--accent)" opacity="0.07" />}
        {ticks.map((t, i) => <g key={i}><line x1={pl} x2={W - pr} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth="1" /><text x={pl - 4} y={y(t) + 3} fontSize="9" textAnchor="end" fill="var(--ink-3)" className="num">{t.toFixed(t >= 10 ? 0 : 1)}</text></g>)}
        {threshold && threshold.direction === "above" && [["caution", threshold.caution, "var(--caution)"], ["danger", threshold.danger, "var(--danger)"]].map(([k, v, c]) =>
          (v as number) <= v1 ? <g key={k as string}><line x1={pl} x2={W - pr} y1={y(v as number)} y2={y(v as number)} stroke={c as string} strokeDasharray="3 3" strokeWidth="1" opacity="0.8" /><text x={W - pr} y={y(v as number) - 2} fontSize="8.5" textAnchor="end" fill={c as string}>{k as string}</text></g> : null)}
        {series.map((s, si) => {
          const pts = s.times.map((t, i) => [new Date(t).getTime(), s.values[i]] as const).filter(([, v]) => v !== null) as [number, number][];
          const d = pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("");
          return <path key={s.name} d={d} stroke={SERIES[si % 4]} strokeWidth="2" fill="none" strokeDasharray={si === 3 ? "5 3" : undefined} />;
        })}
        {hoverT !== null && <line x1={x(hoverT)} x2={x(hoverT)} y1={pt} y2={H - pb} stroke="var(--ink-3)" strokeWidth="1" />}
        <text x={pl} y={H - 3} fontSize="9" fill="var(--ink-3)">{new Date(t0).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</text>
        <text x={W - pr} y={H - 3} fontSize="9" textAnchor="end" fill="var(--ink-3)">{new Date(t1).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", hour: "2-digit", minute: "2-digit" })} IST</text>
      </svg>
      <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-ink-2">
        {series.map((s, si) => <span key={s.name} className="flex items-center gap-1"><span className="inline-block h-0.5 w-3" style={{ background: SERIES[si % 4] }} />{s.name}</span>)}
      </div>
      {hoverT !== null && (
        <div className="pointer-events-none absolute right-1 top-0 rounded border border-line-2 bg-panel px-2 py-1 text-[10.5px] shadow-lg">
          <div className="text-ink-3">{new Date(hoverT).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })} IST</div>
          {series.map((s) => { const i = s.times.findIndex((t) => new Date(t).getTime() === hoverT); const v = i >= 0 ? s.values[i] : null;
            return <div key={s.name} className="num text-ink">{s.name.split(" ")[0]} {v === null || v === undefined ? "—" : v.toFixed(2)} {units}</div>; })}
        </div>
      )}
    </div>
  );
}

export function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="border-t border-line px-4 py-3">
      <div className="mb-2 flex items-center justify-between"><h3 className="lbl">{title}</h3>{right}</div>
      {children}
    </section>
  );
}
