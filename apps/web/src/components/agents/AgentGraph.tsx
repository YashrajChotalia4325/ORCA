"use client";
import { useMemo, useState } from "react";
import { AGENT_LABEL } from "@/lib/format";
import type { AgentRecord, Blackboard, TraceEvent } from "@/lib/types";

type NodeState = "idle" | "selected" | "running" | "done" | "partial" | "failed";
const POS: Record<string, [number, number]> = {
  planner: [400, 40],
  geospatial: [400, 118],
  ocean: [110, 214], weather: [230, 214], satellite: [350, 214], advisory: [470, 214], fisheries: [590, 214], research: [705, 214],
  route: [170, 300],
  hazard: [330, 380],
  evidence: [470, 452],
  alert: [330, 530], communication: [610, 530],
  orca: [470, 600],
};
const EDGES: [string, string][] = [
  ["planner", "geospatial"], ...["ocean", "weather", "satellite", "advisory", "fisheries", "research"].map((a) => ["geospatial", a] as [string, string]),
  ["ocean", "route"], ["weather", "route"], ["route", "hazard"], ["ocean", "hazard"], ["weather", "hazard"], ["advisory", "hazard"],
  ["hazard", "evidence"], ["satellite", "evidence"], ["fisheries", "evidence"], ["research", "evidence"], ["satellite", "research"], ["weather", "research"],
  ["evidence", "alert"], ["evidence", "communication"], ["communication", "orca"], ["alert", "orca"], ["planner", "evidence"],
];
const COLOR: Record<NodeState, string> = { idle: "var(--line-2)", selected: "var(--ink-3)", running: "var(--accent)", done: "var(--go)", partial: "var(--caution)", failed: "var(--danger)" };

export function deriveStates(events: TraceEvent[], bb?: Blackboard | null) {
  const st: Record<string, NodeState> = {};
  const info: Record<string, { ms: number; runs: number; summary: string; tools: Set<string>; sources: Set<string>; failures: number }> = {};
  const planned = new Set<string>();
  for (const e of events) {
    if (e.type === "plan" && Array.isArray(e.data?.tasks)) (e.data.tasks as { agent: string }[]).forEach((t) => planned.add(t.agent));
    if (!e.agent) continue;
    const i = (info[e.agent] ??= { ms: 0, runs: 0, summary: "", tools: new Set(), sources: new Set(), failures: 0 });
    if (e.type === "agent_start") st[e.agent] = "running";
    if (e.type === "tool" && e.data?.tool) i.tools.add(String(e.data.tool));
    if (e.type === "tool" && e.data?.source_id) i.sources.add(String(e.data.source_id));
    if (e.type === "agent_end") {
      const s = String(e.data?.status ?? "SUCCEEDED");
      st[e.agent] = s === "FAILED" ? "failed" : s === "PARTIAL" ? "partial" : "done";
      i.ms += Number(e.data?.duration_ms ?? 0); i.runs += 1; i.summary = e.message; i.failures += Number(e.data?.failures ?? 0);
    }
  }
  planned.forEach((a) => { if (!st[a]) st[a] = "selected"; });
  if (events.some((e) => e.type === "done")) st.orca = "done";
  else if (events.length) st.orca = "selected";
  const recs: Record<string, AgentRecord[]> = {};
  if (bb) Object.values(bb.agents).forEach((r) => (recs[r.agent] ??= []).push(r));
  return { st, info, planned, recs };
}

export default function AgentGraph({ events, bb, height = 640, onSelect }: { events: TraceEvent[]; bb?: Blackboard | null; height?: number; onSelect?: (a: string) => void }) {
  const { st, info, planned, recs } = useMemo(() => deriveStates(events, bb), [events, bb]);
  const [sel, setSel] = useState<string | null>(null);
  const active = (a: string) => st[a] && st[a] !== "idle";
  return (
    <svg viewBox="0 0 810 640" style={{ height }} className="w-full" role="img" aria-label="agent network">
      <defs>
        <marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--line-2)" /></marker>
      </defs>
      {EDGES.map(([a, b]) => {
        const [x1, y1] = POS[a], [x2, y2] = POS[b];
        const on = active(a) && active(b);
        const flowing = on && st[b] === "running";
        return <path key={a + b} d={`M${x1},${y1 + 18} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2 - 18}`} fill="none"
          stroke={on ? "var(--accent)" : "var(--line)"} strokeOpacity={on ? 0.55 : 0.8} strokeWidth={on ? 1.5 : 1} className={flowing ? "flow" : undefined} markerEnd="url(#ah)" />;
      })}
      {Object.entries(POS).map(([a, [x, y]]) => {
        const s: NodeState = st[a] ?? "idle";
        const i = info[a];
        const isOrca = a === "orca";
        const w = isOrca ? 150 : 108, h = 36;
        return (
          <g key={a} transform={`translate(${x - w / 2},${y - h / 2})`} className="cursor-pointer" onClick={() => { setSel(a); onSelect?.(a); }}>
            <rect width={w} height={h} rx={isOrca ? 18 : 6} fill={s === "running" ? "color-mix(in oklab, var(--accent) 16%, var(--panel-2))" : "var(--panel-2)"}
              stroke={sel === a ? "var(--ink)" : COLOR[s]} strokeWidth={s === "idle" ? 1 : 1.6} opacity={s === "idle" ? 0.45 : 1} />
            {s === "running" && <rect width={w} height={h} rx={isOrca ? 18 : 6} fill="none" stroke="var(--accent)" strokeWidth="1" className="pulse" />}
            <text x={w / 2} y={15} textAnchor="middle" fontSize="11.5" fill={s === "idle" ? "var(--ink-3)" : "var(--ink)"} fontFamily="var(--font-plex-cond)" fontWeight={600} letterSpacing="0.06em">
              {isOrca ? "ORCA RESPONSE" : (AGENT_LABEL[a] ?? a).toUpperCase()}
            </text>
            <text x={w / 2} y={28} textAnchor="middle" fontSize="9.5" fill={COLOR[s]} fontFamily="var(--font-plex-mono)">
              {s === "running" ? "running…" : i?.runs ? `${Math.round(i.ms)} ms${i.runs > 1 ? ` · ${i.runs} runs` : ""}${i.failures ? ` · ${i.failures} src ✕` : ""}` : s === "selected" ? "planned" : s === "done" ? "done" : planned.has(a) ? "planned" : "not needed"}
            </text>
          </g>
        );
      })}
      {sel && sel !== "orca" && (
        <foreignObject x="560" y="300" width="245" height="140">
          <div className="h-full overflow-y-auto rounded-md border border-line-2 bg-panel p-2 text-[10.5px] text-ink-2 scroll-thin">
            <div className="font-cond text-[11px] font-semibold tracking-wider text-ink">{(AGENT_LABEL[sel] ?? sel).toUpperCase()}</div>
            <div className="mt-0.5">{info[sel]?.summary || (planned.has(sel) ? "planned" : "not selected by the planner for this question")}</div>
            {info[sel]?.tools.size ? <div className="mt-1"><span className="text-ink-3">tools </span>{[...info[sel].tools].join(", ")}</div> : null}
            {info[sel]?.sources.size ? <div className="mt-0.5"><span className="text-ink-3">sources </span>{[...info[sel].sources].join(", ")}</div> : null}
            {recs[sel]?.map((r) => r.error && <div key={r.task_id} className="mt-0.5 text-danger">{r.error}</div>)}
          </div>
        </foreignObject>
      )}
    </svg>
  );
}
