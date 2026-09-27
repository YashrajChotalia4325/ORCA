"use client";
import Link from "next/link";
import { useEffect } from "react";
import { DecisionBadge, Section } from "@/components/result/primitives";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { ago, ist, SOURCE_STATUS } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useOrca } from "@/lib/store";
import type { Alert, Decision, Scenario } from "@/lib/types";

const SECTORS = ["Gujarat coast", "Maharashtra coast", "Karnataka coast", "Kerala coast", "Tamil Nadu coast", "Andhra Pradesh coast", "Odisha coast", "West Bengal coast"];

interface Health { sources: { total: number; operational: number; by_status: Record<string, number> }; monitor: { enabled: boolean; last_run?: string | null; cycles: number; last_events?: { type: string; region: string; hs?: number; ws?: number }[]; alerts_generated: number }; queries: { total: number; avg_ms?: number | null } }
interface Trace { trace_id: string; created_at: string; intent: string; decision: Decision | null; mode: string; confidence: number | null; duration_ms: number | null; query_id: string }

export default function CommandCenter() {
  const { mode, scenario, runQuery, toggleLayer } = useOrca();
  const health = useApi<Health>("/api/system/health", 30000);
  const alerts = useApi<Alert[]>(`/api/alerts?status=active&limit=6&mode=${mode}`, 30000);
  const traces = useApi<Trace[]>("/api/traces?limit=8", 20000);
  const scen = useApi<Scenario[]>("/api/demo/scenarios");
  const sc = scen.data?.find((s) => s.id === scenario);
  useEffect(() => { toggleLayer("waves", true); toggleLayer("cyclones", true); }, [toggleLayer]);
  const h = health.data;
  return (
    <IntelPanel width={430}>
      <PanelHeader kicker="Command center" title="Indian seas — situation overview" right={<Link href="/ask" className="rounded bg-accent px-2.5 py-1 text-[12px] font-medium text-abyss">Ask ORCA</Link>} />
      <div className="scroll-thin flex-1 overflow-y-auto">
        {mode === "DEMO" && sc && (
          <Section title="Demo scenario">
            <div className="text-[13px] text-ink">{sc.title}</div>
            <p className="mt-1 text-[12px] leading-snug text-ink-2">{sc.description}</p>
            <div className="mt-2 flex flex-wrap gap-1">{sc.demonstrates.map((d) => <span key={d} className="rounded-sm border border-line-2 px-1.5 py-[1px] text-[10.5px] text-ink-3">{d}</span>)}</div>
            <button onClick={() => runQuery(sc.query)} className="mt-2.5 rounded bg-demo px-3 py-1.5 text-[12px] font-medium text-abyss">Run: “{sc.query}”</button>
          </Section>
        )}
        <Section title="Data sources">
          {h ? (
            <>
              <div className="flex items-baseline gap-2"><span className="num text-[26px] font-light text-live">{h.sources.operational}</span><span className="text-[12px] text-ink-2">of {h.sources.total} sources responding in LIVE</span></div>
              <div className="mt-2 flex h-2 overflow-hidden rounded-sm">
                {Object.entries(h.sources.by_status).map(([k, v]) => <div key={k} title={`${k}: ${v}`} style={{ flex: v, background: SOURCE_STATUS[k]?.color ?? "var(--na)" }} className="border-r-2 border-panel last:border-0" />)}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 text-[10.5px] text-ink-3">{Object.entries(h.sources.by_status).map(([k, v]) => <span key={k}><span style={{ color: SOURCE_STATUS[k]?.color }}>■</span> {SOURCE_STATUS[k]?.label ?? k} {v}</span>)}</div>
              <Link href="/sources" className="mt-1.5 inline-block text-[11.5px] text-accent">Inspect every source →</Link>
            </>
          ) : <p className="text-[12px] text-ink-3">{health.error ?? "loading…"}</p>}
        </Section>
        <Section title="Proactive monitoring" right={h?.monitor.last_run ? <span className="text-[10.5px] text-ink-3">last scan {ago(h.monitor.last_run)}</span> : null}>
          {h && (h.monitor.enabled ? (
            <div className="text-[12px] text-ink-2">
              {h.monitor.cycles} scan cycle(s) · {h.monitor.alerts_generated} alert(s) generated
              {h.monitor.last_events?.length ? <ul className="mt-1 text-[11.5px]">{h.monitor.last_events.slice(0, 5).map((e, i) => <li key={i}>▲ {e.type.replace("_", " ")} — {e.region.replace("_", " ")}{e.hs ? ` · Hs ${e.hs} m` : ""}{e.ws ? ` · wind ${e.ws} km/h` : ""}</li>)}</ul> : <p className="mt-1 text-[11.5px] text-ink-3">No threshold crossings in the last scan.</p>}
            </div>
          ) : <p className="text-[12px] text-ink-3">Monitor disabled.</p>)}
        </Section>
        <Section title="Active alerts" right={<Link href="/safety" className="text-[11px] text-accent">Alert centre →</Link>}>
          {alerts.data?.length ? alerts.data.map((a) => (
            <div key={a.id} className="border-t border-line py-1.5 text-[12px] first:border-0">
              <div className="flex items-center gap-2"><span style={{ color: a.severity === "severe" ? "var(--danger)" : "var(--caution)" }}>{a.severity === "severe" ? "■" : "▲"}</span><span className="text-ink">{a.title}</span></div>
              <div className="text-[11px] text-ink-3">{ago(a.created_at)} · {a.verified ? "verified" : "unverified signal"} · {a.mode}</div>
            </div>
          )) : <p className="text-[12px] text-ink-3">No active alerts in {mode} mode.</p>}
        </Section>
        <Section title="Regional risk scan (authority view)">
          <div className="grid grid-cols-2 gap-1.5">
            {SECTORS.map((s) => (
              <button key={s} onClick={() => runQuery(`Show hazards across the ${s} for the next 24 hours`)}
                className="rounded border border-line-2 px-2 py-1.5 text-left text-[11.5px] text-ink-2 hover:border-accent/60 hover:text-ink">{s}</button>
            ))}
          </div>
          <p className="mt-1.5 text-[10.5px] text-ink-3">Each scan assesses 2–8 offshore stations with all models and advisories; results appear on the map and in Ask ORCA.</p>
        </Section>
        <Section title="Recent traces">
          {traces.data?.map((t) => (
            <Link key={t.trace_id} href={`/evidence?trace=${t.trace_id}`} className="grid grid-cols-[1fr_auto] items-center gap-2 border-t border-line py-1.5 text-[11.5px] first:border-0 hover:bg-panel-2/50">
              <span className="min-w-0"><span className="num text-ink-2">{t.trace_id}</span><span className="text-ink-3"> · {t.intent?.toLowerCase().replaceAll("_", " ")} · {t.mode} · {ist(t.created_at, false)}</span></span>
              {t.decision && <DecisionBadge decision={t.decision} size="sm" />}
            </Link>
          ))}
        </Section>
      </div>
    </IntelPanel>
  );
}
