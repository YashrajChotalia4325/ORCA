"use client";
import { Fragment, useState } from "react";
import { StagePanel } from "@/components/shell/ConsoleShell";
import { post } from "@/lib/api";
import { ago, SOURCE_STATUS } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { SourceRow } from "@/lib/types";

const hrs = (s?: number | null) => (s ? (s >= 86400 ? `${(s / 86400).toFixed(0)} d` : `${(s / 3600).toFixed(0)} h`) : "—");

export default function Sources() {
  const { data, error, reload } = useApi<{ total: number; counts: Record<string, number>; sources: SourceRow[]; last_probe?: string }>("/api/sources", 60000);
  const [probing, setProbing] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const probe = async () => { setProbing(true); try { await post("/api/sources/probe"); await reload(); } finally { setProbing(false); } };
  const groups: [string, (s: SourceRow) => boolean][] = [
    ["Live integrations", (s) => s.integration === "live" && s.role !== "tiebreaker"],
    ["Tie-breaker models (queried only on conflict or failure)", (s) => s.role === "tiebreaker"],
    ["Authoritative sources behind credentials / without public API", (s) => s.integration === "adapter"],
    ["Static reference data", (s) => s.integration === "reference"],
  ];
  return (
    <StagePanel>
      <div className="mx-auto max-w-[1280px] px-6 py-6">
        <div className="flex items-end justify-between">
          <div>
            <div className="lbl">Data source explorer</div>
            <h1 className="mt-1 text-[22px] font-light text-ink">Every source, its real access status and freshness</h1>
            <p className="mt-1 max-w-[860px] text-[12.5px] text-ink-2">Status comes from live probes and per-request health (circuit breakers, latency, failures). Sources that need credentials or have no documented public API are shown as such — ORCA never displays them as live and excludes them from answers.</p>
          </div>
          <div className="text-right">
            <button onClick={probe} disabled={probing} className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-abyss disabled:opacity-50">{probing ? "Probing…" : "Probe all now"}</button>
            <div className="mt-1 text-[11px] text-ink-3">last probe {ago(data?.last_probe)}</div>
          </div>
        </div>
        {error && <p className="mt-4 text-danger">{error}</p>}
        {data && (
          <div className="mt-4 flex flex-wrap gap-4">
            {Object.entries(data.counts).map(([k, v]) => (
              <div key={k} className="rounded-md border border-line-2 bg-panel px-4 py-2">
                <div className="num text-[22px] font-light" style={{ color: SOURCE_STATUS[k]?.color }}>{v}</div>
                <div className="lbl">{SOURCE_STATUS[k]?.label ?? k}</div>
              </div>
            ))}
          </div>
        )}
        {data && groups.map(([title, f]) => {
          const rows = data.sources.filter(f);
          if (!rows.length) return null;
          return (
            <section key={title} className="mt-6">
              <h2 className="lbl mb-2">{title}</h2>
              <div className="overflow-hidden rounded-md border border-line-2">
                <table className="w-full text-[12px]">
                  <thead className="bg-panel-2 text-left text-ink-3">
                    <tr>{["Source", "Datasets / variables", "Kind", "Resolution", "Refresh", "Status", "Latest product / probe", "Latency p50", "Calls · fail · cache"].map((h) => <th key={h} className="px-3 py-2 font-normal">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {rows.map((s) => {
                      const st = SOURCE_STATUS[s.status] ?? SOURCE_STATUS.UNKNOWN;
                      const ds = s.datasets[0];
                      return (<Fragment key={s.id}>
                        <tr onClick={() => setOpen(open === s.id ? null : s.id)} className="cursor-pointer border-t border-line bg-panel hover:bg-panel-2">
                          <td className="px-3 py-2"><div className="text-ink">{s.name}</div><div className="text-[10.5px] text-ink-3">{s.organization}{s.distributor ? ` · via ${s.distributor}` : ""}</div></td>
                          <td className="px-3 py-2 text-ink-2">{s.datasets.map((d) => d.variables.join(", ")).join(" · ")}</td>
                          <td className="px-3 py-2 text-ink-2">{ds?.kind.toLowerCase()}</td>
                          <td className="px-3 py-2 text-ink-2">{ds?.spatial_resolution}<div className="text-[10.5px] text-ink-3">{ds?.temporal_resolution}</div></td>
                          <td className="num px-3 py-2 text-ink-2">{hrs(ds?.update_interval_s)}{ds?.expected_latency_s ? <div className="text-[10.5px] text-ink-3">latency {hrs(ds.expected_latency_s)}</div> : null}</td>
                          <td className="px-3 py-2"><span className="flex items-center gap-1.5 font-cond text-[10.5px] font-semibold tracking-wider" style={{ color: st.color }}><span className={`h-2 w-2 rounded-full ${s.status === "OPERATIONAL" ? "pulse" : ""}`} style={{ background: st.color }} />{st.label}</span></td>
                          <td className="max-w-[260px] px-3 py-2 text-[11px] text-ink-2">{s.probe?.detail ?? "—"}<div className="text-[10px] text-ink-3">{s.probe?.at ? `probed ${ago(s.probe.at)}` : ""}</div></td>
                          <td className="num px-3 py-2 text-ink-2">{s.health?.latency_p50_ms ? `${Math.round(s.health.latency_p50_ms)} ms` : "—"}</td>
                          <td className="num px-3 py-2 text-ink-2">{s.health ? `${s.health.calls} · ${s.health.failures} · ${s.health.cache_hits}` : "—"}{s.health?.circuit && s.health.circuit !== "CLOSED" && <div className="text-[10px] text-danger">circuit {s.health.circuit}</div>}</td>
                        </tr>
                        {open === s.id && (
                          <tr key={s.id + "-d"} className="border-t border-line bg-panel-2/70">
                            <td colSpan={9} className="px-4 py-3 text-[11.5px] text-ink-2">
                              <div className="grid grid-cols-3 gap-4">
                                <div><div className="lbl mb-1">Access</div>{s.access}{s.auth_env.length ? <> · env: <span className="num">{s.auth_env.join(", ")}</span> ({s.configured ? "configured" : "not configured"})</> : null}<div className="mt-1">Authority tier <span className="num">{s.authority_tier}</span> · weight {s.authority_weight.toFixed(2)}</div><div className="mt-1">Licence: {s.license || "—"}</div>{s.rate_limit && <div>Rate limit: {s.rate_limit}</div>}</div>
                                <div><div className="lbl mb-1">Datasets</div>{s.datasets.map((d) => <div key={d.id} className="mb-1"><span className="text-ink">{d.title}</span> <span className="num text-ink-3">{d.id}</span><div className="text-ink-3">{d.coverage}</div></div>)}</div>
                                <div><div className="lbl mb-1">Notes</div>{s.notes.map((n, i) => <p key={i} className="mb-1">{n}</p>)}{s.health?.last_error && <p className="text-danger">last error: {s.health.last_error}</p>}{(s.docs_url || s.homepage) && <a className="text-accent" href={s.docs_url || s.homepage} target="_blank" rel="noreferrer">documentation ↗</a>}</div>
                              </div>
                            </td>
                          </tr>)}
                      </Fragment>);
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}
      </div>
    </StagePanel>
  );
}
