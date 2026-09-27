"use client";
import { useEffect, useState } from "react";
import { ClaimCard } from "@/components/result/EvidenceDrawer";
import { ConflictTable } from "@/components/result/ResultCard";
import { DecisionBadge } from "@/components/result/primitives";
import { EventLog, PipelineStrip } from "@/components/shell/AgentDock";
import { StagePanel } from "@/components/shell/ConsoleShell";
import { get } from "@/lib/api";
import { ist, pct } from "@/lib/format";
import { useApi, useQueryParam } from "@/lib/hooks";
import { useActiveTurn, useOrca } from "@/lib/store";
import type { Blackboard, Claim, Decision } from "@/lib/types";

type Trace = { trace_id: string; created_at: string; intent: string; decision: Decision | null; mode: string };

export default function Evidence() {
  const param = useQueryParam("trace");
  const turn = useActiveTurn();
  const traces = useApi<Trace[]>("/api/traces?limit=40");
  const [picked, setId] = useState<string | null>(null);
  const id = picked ?? param ?? turn?.traceId ?? traces.data?.[0]?.trace_id ?? null;
  const [bb, setBb] = useState<Blackboard | null>(null);
  const { flyTo, setHighlight } = useOrca();
  useEffect(() => { if (id) get<Blackboard>(`/api/query/${id}`).then(setBb).catch(() => setBb(null)); }, [id]);
  const [cat, setCat] = useState("all");
  const claims = (bb?.claims ?? []).filter((c) => cat === "all" || c.category === cat);
  const cats = [...new Set((bb?.claims ?? []).map((c) => c.category))];
  const focus = (c: Claim) => { if (c.map_focus) { setHighlight({ lat: c.map_focus.lat, lon: c.map_focus.lon }); flyTo(c.map_focus.lat, c.map_focus.lon); } };
  return (
    <StagePanel>
      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-5 px-6 py-6 lg:grid-cols-[220px_minmax(0,1fr)] 2xl:grid-cols-[260px_minmax(0,1fr)_420px]">
        <aside>
          <div className="lbl mb-2">Traces</div>
          <div className="flex flex-col gap-1">
            {traces.data?.map((t) => (
              <button key={t.trace_id} onClick={() => setId(t.trace_id)} className={`rounded border px-2 py-1.5 text-left ${id === t.trace_id ? "border-accent/70 bg-panel-2" : "border-line bg-panel hover:border-line-2"}`}>
                <div className="num text-[11px] text-ink">{t.trace_id}</div>
                <div className="flex items-center justify-between text-[10.5px] text-ink-3"><span>{t.intent?.toLowerCase().replaceAll("_", " ")} · {t.mode}</span>{t.decision && <DecisionBadge decision={t.decision} size="sm" />}</div>
              </button>
            ))}
          </div>
        </aside>
        <main className="min-w-0">
          {!bb && <p className="text-ink-3">Select a trace.</p>}
          {bb && (
            <>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="lbl">Evidence & provenance · {bb.mode}</div>
                  <h1 className="mt-1 text-[18px] font-light text-ink">“{bb.request.text}”</h1>
                  <div className="num mt-1 text-[11px] text-ink-3">{bb.trace_id} · {ist(bb.created_at)} · reasoning clock {ist(bb.virtual_now)} · {(bb.timings.total_ms / 1000).toFixed(1)} s</div>
                </div>
                {bb.final_assessment && <div className="text-right"><DecisionBadge decision={bb.final_assessment.decision} size="lg" /><div className="num mt-1 text-[13px] text-accent">confidence {pct(bb.final_assessment.confidence)}</div></div>}
              </div>
              <div className="mt-3"><PipelineStrip events={bb.events} /></div>
              <div className="mt-4 flex items-center gap-1 text-[11px]">
                {["all", ...cats].map((c) => <button key={c} onClick={() => setCat(c)} className={`rounded px-2 py-0.5 ${cat === c ? "bg-panel-3 text-ink" : "text-ink-3"}`}>{c}</button>)}
                <span className="ml-auto text-ink-3">{bb.claims.length} claims · {bb.evidence.length} items · {new Set(bb.evidence.map((e) => e.lineage)).size} independent lineages</span>
              </div>
              <div className="mt-2 flex flex-col gap-2">{claims.map((c) => <ClaimCard key={c.id} c={c} items={bb.evidence.filter((e) => e.claim_id === c.id)} onFocus={focus} />)}</div>
            </>
          )}
        </main>
        <aside className="flex flex-col gap-4 lg:col-span-2 2xl:col-span-1">
          {bb && bb.conflicts.length > 0 && <div><div className="lbl mb-2">Conflicts</div><ConflictTable conflicts={bb.conflicts} /></div>}
          {bb && bb.failures.length > 0 && (
            <div><div className="lbl mb-2">Excluded sources</div>{bb.failures.map((f, i) => <p key={i} className="mb-1 text-[11.5px] text-ink-2"><span className="text-danger">✕</span> {f.source} — <span className="num">{f.status}</span>: {f.reason}</p>)}</div>
          )}
          {bb && bb.final_assessment?.confidence_breakdown && (
            <div className="rounded border border-line-2 bg-panel p-3 text-[11.5px]">
              <div className="lbl mb-1">Confidence computation</div>
              <div className="num text-accent">{bb.final_assessment.confidence_breakdown.formula}</div>
              <div className="mt-1 text-ink-2">Q {bb.final_assessment.confidence_breakdown.evidence_quality.toFixed(2)} · G {bb.final_assessment.confidence_breakdown.agreement.toFixed(2)} · C {bb.final_assessment.confidence_breakdown.completeness.toFixed(2)} → {pct(bb.final_assessment.confidence_breakdown.value)}</div>
              <div className="mt-1 text-ink-3">weakest link: {bb.final_assessment.confidence_breakdown.weakest_link}</div>
              {bb.final_assessment.confidence_breakdown.notes.map((n, i) => <div key={i} className="text-ink-3">· {n}</div>)}
            </div>
          )}
          {bb && (
            <div>
              <div className="lbl mb-2">Full reasoning trace ({bb.events.length} events)</div>
              <div className="h-[420px] rounded border border-line-2 bg-panel p-2"><EventLog events={bb.events} max={2000} /></div>
            </div>
          )}
        </aside>
      </div>
    </StagePanel>
  );
}
