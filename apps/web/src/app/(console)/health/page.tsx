"use client";
import Link from "next/link";
import { StagePanel } from "@/components/shell/ConsoleShell";
import { DecisionBadge } from "@/components/result/primitives";
import { ago, AGENT_LABEL, ist, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Decision } from "@/lib/types";

interface H {
  uptime_s: number; default_mode: string; auth_required: boolean;
  llm: { available: boolean; model?: string | null; tokens_in: number; tokens_out: number };
  sources: { total: number; operational: number };
  agents: { count: number; stats: { agent: string; runs: number; avg_ms: number; ok: number; failed: number }[] };
  queries: { total: number; avg_ms?: number | null; active: number };
  http: { calls: number; cache_hits: number; cache_hit_rate?: number | null; per_source: Record<string, { calls: number; failures: number; latency_p50_ms?: number | null; latency_p95_ms?: number | null; circuit: string; success_rate?: number | null; last_error?: string | null }> };
  monitor: { enabled: boolean; cycles: number; last_run?: string | null; alerts_generated: number; errors: string[] };
  snapshots: { id: string; recorded_at: string; requests: number; queries: { text: string }[] }[];
}
type Trace = { trace_id: string; created_at: string; intent: string; decision: Decision | null; mode: string; confidence: number | null; duration_ms: number | null; n_agents: number; n_sources: number; n_conflicts: number; llm_input_tokens: number; llm_output_tokens: number };

function Kpi({ k, v, sub }: { k: string; v: React.ReactNode; sub?: string }) {
  return <div className="rounded-md border border-line-2 bg-panel px-4 py-3"><div className="num text-[24px] font-light text-ink">{v}</div><div className="lbl">{k}</div>{sub && <div className="mt-0.5 text-[10.5px] text-ink-3">{sub}</div>}</div>;
}

export default function Health() {
  const h = useApi<H>("/api/system/health", 15000).data;
  const traces = useApi<Trace[]>("/api/traces?limit=25", 15000).data;
  return (
    <StagePanel>
      <div className="mx-auto max-w-[1320px] px-6 py-6">
        <div className="lbl">System health & observability</div>
        <h1 className="mt-1 text-[22px] font-light text-ink">Latency, availability, cache, agents and traces</h1>
        {h && (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
              <Kpi k="uptime" v={`${(h.uptime_s / 3600).toFixed(1)} h`} />
              <Kpi k="sources up" v={`${h.sources.operational}/${h.sources.total}`} />
              <Kpi k="queries" v={h.queries.total} sub={h.queries.avg_ms ? `avg ${(h.queries.avg_ms / 1000).toFixed(1)} s` : undefined} />
              <Kpi k="upstream calls" v={h.http.calls} sub={`${h.http.cache_hits} cache hits`} />
              <Kpi k="cache hit rate" v={pct(h.http.cache_hit_rate)} />
              <Kpi k="LLM tokens" v={h.llm.tokens_in + h.llm.tokens_out} sub={h.llm.available ? h.llm.model ?? "" : "LLM off — templates"} />
              <Kpi k="monitor cycles" v={h.monitor.cycles} sub={h.monitor.last_run ? `last ${ago(h.monitor.last_run)}` : "not run yet"} />
            </div>
            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
              <section>
                <h2 className="lbl mb-2">Upstream sources (LIVE transport)</h2>
                <table className="w-full overflow-hidden rounded-md border border-line-2 text-[12px]">
                  <thead className="bg-panel-2 text-left text-ink-3"><tr>{["source", "calls", "success", "p50", "p95", "circuit"].map((x) => <th key={x} className="px-3 py-1.5 font-normal">{x}</th>)}</tr></thead>
                  <tbody>{Object.entries(h.http.per_source).sort().map(([k, s]) => (
                    <tr key={k} className="border-t border-line bg-panel" title={s.last_error ?? ""}>
                      <td className="num px-3 py-1.5 text-ink">{k}</td><td className="num px-3 py-1.5">{s.calls}</td>
                      <td className="num px-3 py-1.5" style={{ color: (s.success_rate ?? 1) < 0.9 ? "var(--caution)" : "var(--go)" }}>{pct(s.success_rate)}</td>
                      <td className="num px-3 py-1.5">{s.latency_p50_ms ? `${Math.round(s.latency_p50_ms)} ms` : "—"}</td>
                      <td className="num px-3 py-1.5">{s.latency_p95_ms ? `${Math.round(s.latency_p95_ms)} ms` : "—"}</td>
                      <td className="px-3 py-1.5" style={{ color: s.circuit === "CLOSED" ? "var(--ink-3)" : "var(--danger)" }}>{s.circuit}</td>
                    </tr>))}</tbody>
                </table>
              </section>
              <section>
                <h2 className="lbl mb-2">Agents (all modes)</h2>
                <table className="w-full overflow-hidden rounded-md border border-line-2 text-[12px]">
                  <thead className="bg-panel-2 text-left text-ink-3"><tr>{["agent", "runs", "avg latency", "success rate", "failed"].map((x) => <th key={x} className="px-3 py-1.5 font-normal">{x}</th>)}</tr></thead>
                  <tbody>{h.agents.stats.map((a) => (
                    <tr key={a.agent} className="border-t border-line bg-panel">
                      <td className="px-3 py-1.5 text-ink">{AGENT_LABEL[a.agent] ?? a.agent}</td><td className="num px-3 py-1.5">{a.runs}</td>
                      <td className="num px-3 py-1.5">{a.avg_ms >= 1000 ? `${(a.avg_ms / 1000).toFixed(2)} s` : `${Math.round(a.avg_ms)} ms`}</td>
                      <td className="num px-3 py-1.5">{pct(a.ok / Math.max(1, a.runs))}</td>
                      <td className="num px-3 py-1.5" style={{ color: a.failed ? "var(--caution)" : undefined }}>{a.failed}</td>
                    </tr>))}</tbody>
                </table>
                <p className="mt-1.5 text-[10.5px] text-ink-3">“Failed” includes intended failures in the degraded / outage demo scenarios.</p>
              </section>
            </div>
            <section className="mt-6">
              <h2 className="lbl mb-2">Recent traces</h2>
              <table className="w-full overflow-hidden rounded-md border border-line-2 text-[12px]">
                <thead className="bg-panel-2 text-left text-ink-3"><tr>{["trace", "time", "mode", "intent", "decision", "confidence", "agents", "sources", "conflicts", "duration", "LLM tok"].map((x) => <th key={x} className="px-3 py-1.5 font-normal">{x}</th>)}</tr></thead>
                <tbody>{traces?.map((t) => (
                  <tr key={t.trace_id} className="border-t border-line bg-panel hover:bg-panel-2">
                    <td className="num px-3 py-1.5"><Link href={`/evidence?trace=${t.trace_id}`} className="text-accent">{t.trace_id}</Link></td>
                    <td className="num px-3 py-1.5">{ist(t.created_at)}</td><td className="px-3 py-1.5">{t.mode}</td>
                    <td className="px-3 py-1.5 text-ink-2">{t.intent?.toLowerCase().replaceAll("_", " ")}</td>
                    <td className="px-3 py-1.5">{t.decision && <DecisionBadge decision={t.decision} size="sm" />}</td>
                    <td className="num px-3 py-1.5">{pct(t.confidence)}</td><td className="num px-3 py-1.5">{t.n_agents}</td><td className="num px-3 py-1.5">{t.n_sources}</td>
                    <td className="num px-3 py-1.5">{t.n_conflicts}</td><td className="num px-3 py-1.5">{t.duration_ms ? `${(t.duration_ms / 1000).toFixed(1)} s` : "—"}</td>
                    <td className="num px-3 py-1.5">{t.llm_input_tokens + t.llm_output_tokens}</td>
                  </tr>))}</tbody>
              </table>
            </section>
            <section className="mt-6">
              <h2 className="lbl mb-2">Replay snapshots (recorded real data)</h2>
              {h.snapshots.map((s) => <p key={s.id} className="text-[12px] text-ink-2"><span className="num text-ink">{s.id}</span> · recorded {ist(s.recorded_at)} · {s.requests} upstream responses · {s.queries.length} questions: {s.queries.map((q) => q.text).join(" | ")}</p>)}
            </section>
          </>
        )}
      </div>
    </StagePanel>
  );
}
