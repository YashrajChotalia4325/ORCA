"use client";
import { useEffect, useMemo, useRef } from "react";
import { AGENT_LABEL, FRESH, STAGES, STAGE_LABEL } from "@/lib/format";
import { useActiveTurn, useOrca } from "@/lib/store";
import type { FreshnessStatus, TraceEvent } from "@/lib/types";

export function stagesReached(events: TraceEvent[]): { reached: Set<string>; current: string | null } {
  const reached = new Set<string>();
  let current: string | null = null;
  for (const e of events) if (e.type === "stage" && e.stage) { reached.add(e.stage); current = e.stage; }
  if (events.some((e) => e.type === "done")) { STAGES.forEach((s) => reached.has(s) || null); current = null; }
  return { reached, current };
}

export function PipelineStrip({ events, compact = false }: { events: TraceEvent[]; compact?: boolean }) {
  const { reached, current } = stagesReached(events);
  const done = events.some((e) => e.type === "done");
  return (
    <ol className="flex items-center gap-[3px] overflow-x-auto scroll-thin" aria-label="reasoning pipeline">
      {STAGES.map((s, i) => {
        const on = reached.has(s);
        const cur = s === current && !done;
        return (
          <li key={s} className="flex items-center gap-[3px]">
            <span title={s}
              className={`whitespace-nowrap rounded-sm border px-1.5 py-[2px] font-cond text-[10px] tracking-[0.08em] transition-colors ${cur ? "scanline border-accent text-accent" : on ? "border-line-2 bg-panel-3 text-ink" : "border-line text-ink-3"}`}>
              {compact ? STAGE_LABEL[s].slice(0, 5) : STAGE_LABEL[s]}
            </span>
            {i < STAGES.length - 1 && <span className={`h-px w-2 ${on ? "bg-accent/60" : "bg-line"}`} />}
          </li>
        );
      })}
    </ol>
  );
}

const TYPE_COLOR: Record<string, string> = {
  stage: "var(--ink-3)", plan: "var(--accent)", dispatch: "var(--ink-3)", agent_start: "var(--ink-2)", agent_end: "var(--ink)", tool: "var(--ink-2)",
  replan: "var(--replay)", conflict: "var(--caution)", evidence: "var(--demo)", alert: "var(--serious)", error: "var(--danger)", done: "var(--accent)", start: "var(--accent)",
};

export function EventLog({ events, max = 400 }: { events: TraceEvent[]; max?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight }); }, [events.length]);
  const t0 = events[0] ? new Date(events[0].at).getTime() : 0;
  return (
    <div ref={ref} className="scroll-thin h-full overflow-y-auto pr-2 font-mono text-[11px] leading-[1.55]">
      {events.slice(-max).filter((e) => e.type !== "stage").map((e) => (
        <div key={e.seq} className="rise flex gap-2">
          <span className="w-[46px] shrink-0 text-right text-ink-3">+{((new Date(e.at).getTime() - t0) / 1000).toFixed(2)}s</span>
          <span className="w-[92px] shrink-0 truncate" style={{ color: TYPE_COLOR[e.type] ?? "var(--ink-2)" }}>
            {e.agent ? AGENT_LABEL[e.agent] ?? e.agent : e.type}
          </span>
          <span className={`min-w-0 ${e.type === "agent_end" ? "text-ink" : "text-ink-2"}`}>
            {e.type === "replan" && <b className="text-replay">RE-PLAN · </b>}
            {e.type === "conflict" && <b className="text-caution">CONFLICT · </b>}
            {e.type === "agent_end" && e.data?.status ? <span style={{ color: e.data.status === "FAILED" ? "var(--danger)" : e.data.status === "PARTIAL" ? "var(--caution)" : "var(--go)" }}>{String(e.data.status)} · </span> : null}
            {e.message}
            {typeof e.data?.duration_ms === "number" && <span className="text-ink-3"> · {Math.round(e.data.duration_ms as number)} ms</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function SourceChips({ events }: { events: TraceEvent[] }) {
  const src = useMemo(() => {
    const m = new Map<string, { ok?: boolean; fresh?: string; msg: string }>();
    for (const e of events) {
      if (e.type !== "tool" || !e.data?.source_id) continue;
      const id = String(e.data.source_id);
      const prev = m.get(id);
      const ok = typeof e.data.ok === "boolean" ? (e.data.ok as boolean) : prev?.ok;
      m.set(id, { ok, fresh: (e.data.freshness as string) ?? prev?.fresh, msg: e.message });
    }
    return [...m.entries()];
  }, [events]);
  if (!src.length) return <p className="text-[11px] text-ink-3">Sources contacted by agents appear here with their freshness.</p>;
  return (
    <div className="flex flex-wrap gap-1">
      {src.map(([id, s]) => {
        const f = s.fresh ? FRESH[s.fresh as FreshnessStatus] : null;
        const color = s.ok === false ? "var(--danger)" : f?.color ?? "var(--ink-3)";
        return (
          <span key={id} title={s.msg} className="flex items-center gap-1 rounded-sm border border-line-2 px-1.5 py-[1px] text-[10.5px] text-ink-2">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
            <span className="num">{id}</span>
            <span style={{ color }} className="font-cond text-[9.5px] tracking-wider">{s.ok === false ? "FAILED" : f?.label ?? ""}</span>
          </span>
        );
      })}
    </div>
  );
}

export default function AgentDock() {
  const turn = useActiveTurn();
  const { dockOpen, setDockOpen } = useOrca();
  const events = turn?.events ?? [];
  const running = turn?.status === "running";
  return (
    <section className={`z-20 shrink-0 border-t border-line bg-panel transition-[height] duration-200 ${dockOpen ? "h-[184px]" : "h-8"}`} aria-label="agent activity">
      <div className="flex h-8 items-center gap-3 border-b border-line px-3">
        <button onClick={() => setDockOpen(!dockOpen)} className="lbl hover:text-ink-2">{dockOpen ? "▾" : "▴"} Agent activity</button>
        {turn && <span className="truncate text-[11.5px] text-ink-2">“{turn.text}”</span>}
        {running && <span className="flex items-center gap-1.5 text-[11px] text-accent"><span className="pulse h-1.5 w-1.5 rounded-full bg-accent" />running</span>}
        {turn?.bb && <span className="num ml-auto text-[11px] text-ink-3">{turn.bb.trace_id} · {((turn.bb.timings?.total_ms ?? 0) / 1000).toFixed(1)} s · {Object.keys(turn.bb.agents).length} agent runs</span>}
      </div>
      {dockOpen && (
        <div className="grid h-[152px] grid-cols-[minmax(0,1fr)_minmax(240px,30%)] gap-4 px-3 py-2">
          <div className="flex min-h-0 min-w-0 flex-col gap-2">
            <PipelineStrip events={events} />
            <div className="min-h-0 flex-1">
              {events.length ? <EventLog events={events} /> : <p className="pt-2 text-[12px] text-ink-3">Ask ORCA a question — every step of intent parsing, planning, retrieval, verification and decision will stream here.</p>}
            </div>
          </div>
          <div className="min-h-0 overflow-y-auto scroll-thin border-l border-line pl-3">
            <div className="lbl mb-1.5">Data freshness</div>
            <SourceChips events={events} />
          </div>
        </div>
      )}
    </section>
  );
}
