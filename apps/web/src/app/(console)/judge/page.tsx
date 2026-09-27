"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import AgentGraph from "@/components/agents/AgentGraph";
import ResultCard, { ConflictTable } from "@/components/result/ResultCard";
import { ConfidenceRing, DecisionBadge, FreshTag, LevelTag } from "@/components/result/primitives";
import { PipelineStrip } from "@/components/shell/AgentDock";
import { IntelPanel } from "@/components/shell/ConsoleShell";
import { AGENT_LABEL, fmtVal, ist, SOURCE_STATUS, utc } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { get } from "@/lib/api";
import { useOrca, type Turn } from "@/lib/store";
import type { DataMode, PlanTask, SourceRow } from "@/lib/types";

const QUESTION = "Is it safe to sail from Kochi tomorrow at 5 AM?";
const STEPS = ["System status", "The question", "Planner", "Agents in parallel", "Live evidence", "Conflicts & confidence", "Decision", "Timestamps & provenance", "Stress tests"];
const ACT2: { scenario: string; label: string; what: string; q?: string }[] = [
  { scenario: "approaching_cyclone", label: "Approaching cyclone", what: "wind-radius point-in-polygon → DON'T GO, official warnings, horizon extension (RP3), alerts" },
  { scenario: "conflicting_sources", label: "Sources disagree", what: "no averaging, conflict table, tie-breaker models added by re-planning (RP2)" },
  { scenario: "degraded_sources", label: "API failure", what: "MFWAM + ICON + CoastWatch down → continues, lists exclusions, lower confidence" },
  { scenario: "total_outage", label: "Critical data missing", what: "all wave models down → refuses: NO RELIABLE ASSESSMENT" },
  { scenario: "mumbai_goa_route", label: "Route intelligence", what: "time-dependent A*, segment risk at ETA, shortest vs recommended" },
  { scenario: "protected_geofence", label: "Protected-area geofence", what: "route ∩ MPA, minutes to entry, hard-constraint re-route (RP4)" },
];

function Typing({ text, onDone }: { text: string; onDone: () => void }) {
  const [n, setN] = useState(0);
  const done = useRef(false);
  useEffect(() => {
    if (n >= text.length) { if (!done.current) { done.current = true; setTimeout(onDone, 500); } return; }
    const t = setTimeout(() => setN(n + 1), 38);
    return () => clearTimeout(t);
  }, [n, text, onDone]);
  return <p className="font-light text-[22px] leading-snug text-ink">“{text.slice(0, n)}<span className="pulse text-accent">▍</span>”</p>;
}

export default function Judge() {
  const { mode, setMode, runQuery, turns } = useOrca();
  const [step, setStep] = useState(0);
  const [auto, setAuto] = useState(true);
  const [tid, setTid] = useState<string | null>(null);
  const [act2, setAct2] = useState<string | null>(null);
  const [runMode] = useState<DataMode>(mode === "DEMO" ? "DEMO" : mode);
  const sources = useApi<{ counts: Record<string, number>; total: number; sources: SourceRow[] }>("/api/sources");
  const turn: Turn | undefined = turns.find((t) => t.id === tid);
  const bb = turn?.bb;
  const events = useMemo(() => turn?.events ?? [], [turn?.events]);
  const plan = useMemo(() => (events.find((e) => e.type === "plan")?.data?.tasks ?? []) as PlanTask[], [events]);
  const timeEv = events.find((e) => e.message.startsWith("time window"));

  const start = async () => {
    const p = runQuery(QUESTION, { newConversation: true });
    setTid(useOrca.getState().activeTurnId);
    await p;
  };
  // auto-advance on real progress, never on a fake timer ahead of the data
  useEffect(() => {
    if (!auto) return;
    const t = setTimeout(() => {
      if (step === 0 && sources.data) setStep(1);
      else if (step === 2 && plan.length) setStep(3);
      else if (step === 3 && turn?.status === "done") setStep(4);
      else if (step >= 4 && step < 7 && bb) setStep(step + 1);
    }, step === 0 ? 3500 : step === 2 ? 2600 : step >= 4 ? 6500 : 800);
    return () => clearTimeout(t);
  }, [auto, step, sources.data, plan.length, turn?.status, bb]);

  const runAct2 = async (s: string) => {
    setAct2(s);
    setMode("DEMO", s);
    const sc = ACT2.find((a) => a.scenario === s)!;
    const scen = await get<{ id: string; query: string }[]>("/api/demo/scenarios");
    const q = sc.q ?? scen.find((x) => x.id === s)?.query ?? QUESTION;
    const p = runQuery(q, { newConversation: true });
    setTid(useOrca.getState().activeTurnId);
    await p;
  };

  const live = sources.data?.sources.filter((s) => s.status === "OPERATIONAL") ?? [];
  const blocked = sources.data?.sources.filter((s) => ["CREDENTIALS_REQUIRED", "NO_PUBLIC_API"].includes(s.status)) ?? [];
  return (
    <IntelPanel width={660}>
      <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
        <div className="lbl text-accent">Judge mode</div>
        <div className="flex flex-1 gap-1 overflow-x-auto scroll-thin">
          {STEPS.map((s, i) => (
            <button key={s} onClick={() => { setAuto(false); setStep(i); }} className={`whitespace-nowrap rounded px-2 py-0.5 text-[11px] ${i === step ? "bg-accent text-abyss" : i < step ? "text-ink-2" : "text-ink-3"}`}>{i + 1}. {s}</button>
          ))}
        </div>
        <button onClick={() => setAuto(!auto)} className="text-[11px] text-ink-3 hover:text-ink-2">{auto ? "❚❚ auto" : "▶ auto"}</button>
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto">
        {step === 0 && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">1 · What ORCA can see right now</h2>
            <p className="mt-1 text-[12.5px] text-ink-2">Mode <b className="text-ink">{runMode}</b>. Status comes from live probes — nothing below is simulated.</p>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {live.map((s) => (
                <div key={s.id} className="rounded border border-line-2 bg-panel-2 px-3 py-2">
                  <div className="flex items-center justify-between text-[12px]"><span className="text-ink">{s.name}</span><span className="font-cond text-[10px] font-semibold tracking-wider text-live">● LIVE</span></div>
                  <div className="text-[10.5px] text-ink-3">{s.probe?.detail ?? s.organization}</div>
                </div>
              ))}
            </div>
            <div className="lbl mb-1.5 mt-4">Authoritative but not machine-accessible from here (shown honestly, excluded from answers)</div>
            <div className="flex flex-wrap gap-1.5">{blocked.map((s) => <span key={s.id} className="rounded-sm border border-line-2 px-2 py-0.5 text-[11px] text-ink-2" title={s.probe?.detail}>{s.name} · <span style={{ color: SOURCE_STATUS[s.status]?.color }}>{SOURCE_STATUS[s.status]?.label}</span></span>)}</div>
          </div>
        )}
        {step === 1 && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">2 · A fisherman asks</h2>
            <div className="mt-6"><Typing text={QUESTION} onDone={() => { if (!tid) start(); setStep(2); }} /></div>
          </div>
        )}
        {step === 2 && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">3 · The planner decomposes it</h2>
            <PipelineStrip events={events} compact />
            {timeEv && <p className="num mt-3 rounded bg-panel-2 px-3 py-2 text-[12px] text-accent">{timeEv.message}</p>}
            <ol className="mt-3 flex flex-col gap-1.5">
              {plan.map((t, i) => (
                <li key={t.id} className="rise grid grid-cols-[22px_120px_1fr] gap-2 text-[12.5px]" style={{ animationDelay: `${i * 90}ms` }}>
                  <span className="num text-ink-3">{i + 1}</span><span className="text-ink">{AGENT_LABEL[t.agent] ?? t.agent}</span>
                  <span className="text-ink-2">{t.reason}{t.depends_on.length ? <span className="text-ink-3"> ← {t.depends_on.map((d) => AGENT_LABEL[d] ?? d).join(", ")}</span> : null}</span>
                </li>
              ))}
            </ol>
            {!plan.length && <p className="mt-3 text-[12px] text-ink-3">planning…</p>}
          </div>
        )}
        {step === 3 && (
          <div className="rise p-4">
            <h2 className="px-1 text-[20px] font-light text-ink">4 · Agents work in parallel on a shared blackboard</h2>
            <AgentGraph events={events} bb={bb} height={440} />
            <PipelineStrip events={events} compact />
          </div>
        )}
        {step === 4 && bb?.risk && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">5 · Live evidence over the whole trip window</h2>
            <p className="mt-1 text-[12.5px] text-ink-2">{bb.understanding?.time_window?.label} · {bb.outputs.geospatial?.samples?.length} sample points (assessment point, transit, ring) · every hour · every model. Worst case is used — no averaging.</p>
            <table className="mt-3 w-full text-[12.5px]">
              <tbody>{bb.risk.factors.map((f) => (
                <tr key={f.id} className="border-t border-line">
                  <td className="py-1.5 text-ink">{f.label}</td>
                  <td className="num py-1.5 text-right text-ink">{f.available ? (f.value === null ? "none active" : fmtVal(f.value, f.units)) : "unavailable"}</td>
                  <td className="py-1.5 pl-3 text-[11px] text-ink-3">{f.per_source.length ? `${f.per_source.length} sources${f.spread ? ` · spread ${f.spread}` : ""}` : ""}</td>
                  <td className="py-1.5 text-right"><LevelTag level={f.level} /></td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        {step === 5 && bb && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">6 · Do the sources agree? How sure are we?</h2>
            <div className="mt-3 flex items-center gap-4">
              {bb.final_assessment && <ConfidenceRing value={bb.final_assessment.confidence} breakdown={bb.final_assessment.confidence_breakdown} />}
              <p className="text-[12px] text-ink-2">{bb.final_assessment?.confidence_breakdown?.formula}<br /><span className="text-ink-3">weakest link: {bb.final_assessment?.confidence_breakdown?.weakest_link}</span></p>
            </div>
            <div className="mt-4">{bb.conflicts.length ? <ConflictTable conflicts={bb.conflicts} /> : <p className="text-[12.5px] text-ink-2">No material disagreement between sources for this window.</p>}</div>
            {bb.plan.replans.map((r, i) => <p key={i} className="mt-2 text-[12px] text-replay">↻ re-plan {r.rule}: {r.detail}</p>)}
          </div>
        )}
        {step === 6 && bb && <ResultCard bb={bb} />}
        {step === 7 && bb && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">8 · Exact timestamps for every datum</h2>
            <table className="mt-3 w-full text-[11.5px]">
              <thead className="text-ink-3"><tr><th className="text-left font-normal">source</th><th className="text-left font-normal">variable</th><th className="text-right font-normal">valid</th><th className="text-right font-normal">model run</th><th className="text-right font-normal">retrieved</th><th className="text-right font-normal">status</th></tr></thead>
              <tbody>{bb.evidence.filter((e) => e.provenance.kind !== "REFERENCE").slice(0, 22).map((e) => (
                <tr key={e.id} className="border-t border-line">
                  <td className="py-1 text-ink">{e.source}</td><td className="py-1 text-ink-2">{e.variable}</td>
                  <td className="num py-1 text-right">{ist(e.valid_time)}</td><td className="num py-1 text-right">{utc(e.provenance.issued_at)}</td>
                  <td className="num py-1 text-right">{utc(e.provenance.retrieval_timestamp)}</td>
                  <td className="py-1 text-right"><FreshTag status={e.provenance.freshness.status} /></td>
                </tr>))}</tbody>
            </table>
            <p className="mt-2 text-[11px] text-ink-3">Trace {bb.trace_id} — the complete reasoning is inspectable under Evidence and Agents.</p>
          </div>
        )}
        {step === 8 && (
          <div className="rise p-5">
            <h2 className="text-[20px] font-light text-ink">9 · Stress tests (DEMO scenarios, clearly labelled)</h2>
            <p className="mt-1 text-[12.5px] text-ink-2">Same agents, same risk model — only the data layer is simulated so hard cases can be shown on demand.</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {ACT2.map((a) => (
                <button key={a.scenario} onClick={() => runAct2(a.scenario)} className={`rounded border p-3 text-left ${act2 === a.scenario ? "border-demo" : "border-line-2 hover:border-demo/60"}`}>
                  <div className="text-[13px] text-ink">{a.label}</div><div className="mt-0.5 text-[11px] text-ink-3">{a.what}</div>
                </button>
              ))}
            </div>
            {act2 && turn && <div className="mt-4 rounded border border-line-2">{turn.status === "done" && turn.bb ? <ResultCard bb={turn.bb} /> : <div className="p-3"><PipelineStrip events={events} compact /></div>}</div>}
          </div>
        )}
        {step >= 4 && step <= 7 && !bb && <div className="p-5"><p className="text-[12.5px] text-ink-2">Waiting for the agents to finish…</p><PipelineStrip events={events} compact /></div>}
      </div>
      <div className="flex items-center gap-2 border-t border-line px-4 py-2.5">
        <button onClick={() => { setAuto(false); setStep(Math.max(0, step - 1)); }} className="rounded border border-line-2 px-3 py-1 text-[12px] text-ink-2">← Back</button>
        <button onClick={() => { setAuto(false); if (step === 1 && !tid) start(); setStep(Math.min(STEPS.length - 1, step + 1)); }} className="rounded bg-accent px-3 py-1 text-[12px] font-medium text-abyss">Next →</button>
        {bb?.final_assessment && <span className="ml-auto flex items-center gap-2"><DecisionBadge decision={bb.final_assessment.decision} size="sm" /><span className="num text-[10.5px] text-ink-3">{bb.trace_id}</span></span>}
      </div>
    </IntelPanel>
  );
}
