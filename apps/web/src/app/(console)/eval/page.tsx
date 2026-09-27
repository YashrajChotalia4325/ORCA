"use client";
import { useState } from "react";
import { StagePanel } from "@/components/shell/ConsoleShell";
import { post } from "@/lib/api";
import { ist, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Summary = { run_at: string; duration_s: number; metrics: Record<string, number | boolean | null>; understanding: Record<string, number | null>; pipeline: Record<string, number | boolean | null> };
type Eval = { id: string; created_at: string; summary: Summary; results: { understanding: Record<string, unknown>[]; pipeline: Record<string, unknown>[] } };

const METRICS: [string, string, "pct" | "ms" | "inv"][] = [
  ["groundedness", "Groundedness", "pct"], ["source_correctness", "Source correctness", "pct"], ["evidence_completeness", "Evidence completeness", "pct"],
  ["temporal_correctness", "Temporal correctness", "pct"], ["spatial_correctness", "Spatial correctness", "pct"], ["agent_routing_accuracy", "Agent routing", "pct"],
  ["tool_selection_accuracy", "Tool selection", "pct"], ["risk_consistency", "Risk consistency", "pct"], ["hallucination_rate", "Hallucination rate", "inv"],
  ["latency_p50_ms", "Latency p50", "ms"], ["latency_p95_ms", "Latency p95", "ms"], ["intent_accuracy", "Intent accuracy", "pct"],
  ["language_accuracy", "Language detection", "pct"], ["decision_accuracy", "Decision accuracy", "pct"],
];

export default function EvalPage() {
  const latest = useApi<Eval>("/api/eval/latest");
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => { setRunning(true); setErr(null); try { await post("/api/eval/run"); await latest.reload(); } catch (e) { setErr(String(e)); } finally { setRunning(false); } };
  const e = latest.data;
  return (
    <StagePanel>
      <div className="mx-auto max-w-[1320px] px-6 py-6">
        <div className="flex items-end justify-between">
          <div>
            <div className="lbl">Evaluation · orca-eval-v1</div>
            <h1 className="mt-1 text-[22px] font-light text-ink">100 marine queries · 14 end-to-end scenario runs</h1>
            <p className="mt-1 max-w-[900px] text-[12.5px] text-ink-2">Understanding metrics run on all 100 queries (8 languages); pipeline metrics execute the full multi-agent system in DEMO scenarios (deterministic, no network). The dataset was authored alongside ORCA — treat it as a regression suite, not an independent benchmark.</p>
          </div>
          <button onClick={run} disabled={running} className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-abyss disabled:opacity-50">{running ? "Running (≈1 min)…" : "Run evaluation"}</button>
        </div>
        {err && <p className="mt-3 text-danger">{err}</p>}
        {!e && !running && <p className="mt-6 text-ink-3">{latest.error ?? "No run yet."}</p>}
        {e && (
          <>
            <div className="mt-2 text-[11.5px] text-ink-3">run {e.id} · {ist(e.summary.run_at)} · {e.summary.duration_s} s</div>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
              {METRICS.map(([k, l, f]) => {
                const v = e.summary.metrics[k] as number | null;
                const good = f === "inv" ? (v ?? 1) === 0 : f === "pct" ? (v ?? 0) >= 0.95 : true;
                return (
                  <div key={k} className="rounded-md border border-line-2 bg-panel px-3 py-3">
                    <div className="num text-[22px] font-light" style={{ color: good ? "var(--ink)" : "var(--caution)" }}>{f === "ms" ? `${((v ?? 0) / 1000).toFixed(2)} s` : pct(v)}</div>
                    <div className="lbl">{l}</div>
                  </div>
                );
              })}
            </div>
            <section className="mt-6">
              <h2 className="lbl mb-2">End-to-end runs</h2>
              <table className="w-full overflow-hidden rounded-md border border-line-2 text-[11.5px]">
                <thead className="bg-panel-2 text-left text-ink-3"><tr>{["scenario", "question", "expected", "got", "grounded", "provenance", "routing", "tools", "latency", "trace"].map((x) => <th key={x} className="px-2.5 py-1.5 font-normal">{x}</th>)}</tr></thead>
                <tbody>{e.results.pipeline.map((r, i) => (
                  <tr key={i} className="border-t border-line bg-panel">
                    <td className="num px-2.5 py-1.5 text-ink-2">{String(r.scenario)}</td><td className="max-w-[360px] truncate px-2.5 py-1.5 text-ink">{String(r.text)}</td>
                    <td className="px-2.5 py-1.5">{String(r.expected)}</td>
                    <td className="px-2.5 py-1.5" style={{ color: r.decision_ok ? "var(--go)" : "var(--danger)" }}>{String(r.decision)}</td>
                    {["grounded", "provenance_complete", "agents_ok", "tools_ok"].map((k) => <td key={k} className="px-2.5 py-1.5" style={{ color: r[k] ? "var(--go)" : "var(--danger)" }}>{r[k] ? "✓" : "✕"}</td>)}
                    <td className="num px-2.5 py-1.5">{String(r.latency_ms)} ms</td>
                    <td className="num px-2.5 py-1.5"><a className="text-accent" href={`/evidence?trace=${r.trace_id}`}>{String(r.trace_id)}</a></td>
                  </tr>))}</tbody>
              </table>
            </section>
            <section className="mt-6">
              <h2 className="lbl mb-2">Understanding cases ({e.results.understanding.length})</h2>
              <div className="grid grid-cols-1 gap-1 md:grid-cols-2">
                {e.results.understanding.map((r) => {
                  const ok = r.intent_ok && r.lang_ok && r.place_ok && r.temporal_ok;
                  return <div key={String(r.id)} className="flex items-center gap-2 rounded border border-line bg-panel px-2 py-1 text-[11px]">
                    <span style={{ color: ok ? "var(--go)" : "var(--danger)" }}>{ok ? "✓" : "✕"}</span><span className="num text-ink-3">{String(r.id)}</span>
                    <span className="truncate text-ink-2">{String(r.text)}</span><span className="num ml-auto shrink-0 text-ink-3">{String(r.intent).toLowerCase()} · {String(r.lang)}</span></div>;
                })}
              </div>
            </section>
          </>
        )}
      </div>
    </StagePanel>
  );
}
