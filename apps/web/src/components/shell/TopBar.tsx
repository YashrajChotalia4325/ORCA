"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { useActiveTurn, useOrca } from "@/lib/store";
import type { DataMode, Scenario } from "@/lib/types";
import { OrcaMark } from "./icons";

interface Health {
  sources: { total: number; operational: number; by_status: Record<string, number> };
  agents: { count: number };
  llm: { available: boolean; model?: string | null };
  monitor: { enabled: boolean; last_run?: string | null; cycles: number };
  snapshots: { id: string; recorded_at: string }[];
}

function Clock({ label, tz, date }: { label: string; tz: string; date: Date | null }) {
  const t = !date ? "--:--:--" : date.toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  return (
    <div className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="lbl">{label}</span>
      <span className="num text-[12.5px] text-ink">{t}</span>
    </div>
  );
}

const MODES: { id: DataMode; color: string; hint: string }[] = [
  { id: "LIVE", color: "var(--live)", hint: "Only real external data" },
  { id: "REPLAY", color: "var(--replay)", hint: "Recorded real responses, original timestamps" },
  { id: "DEMO", color: "var(--demo)", hint: "Clearly-labelled synthetic scenarios" },
];

export default function TopBar() {
  const { mode, scenario, setMode } = useOrca();
  const turn = useActiveTurn();
  const [h, setH] = useState<Health | null>(null);
  const [alerts, setAlerts] = useState<number>(0);
  const [scen, setScen] = useState<Scenario[]>([]);
  const [now, setNow] = useState<Date | null>(null);   // set after mount (avoids SSR/client clock mismatch)
  const [err, setErr] = useState(false);

  useEffect(() => {
    const load = () => {
      get<Health>("/api/system/health").then((x) => { setH(x); setErr(false); }).catch(() => setErr(true));
      get<unknown[]>(`/api/alerts?status=active&limit=200&mode=${useOrca.getState().mode}`).then((a) => setAlerts(a.length)).catch(() => undefined);
    };
    const first = setTimeout(() => { load(); setNow(new Date()); }, 0);
    const i = setInterval(load, 30000);
    const c = setInterval(() => setNow(new Date()), 1000);
    get<Scenario[]>("/api/demo/scenarios").then(setScen).catch(() => undefined);
    const unsub = useOrca.subscribe((st, prev) => { if (st.mode !== prev.mode) load(); });
    return () => { clearTimeout(first); clearInterval(i); clearInterval(c); unsub(); };
  }, []);

  const scenarioObj = scen.find((s) => s.id === scenario);
  const virtual = mode === "DEMO" && scenarioObj ? new Date(scenarioObj.now) : mode === "REPLAY" && h?.snapshots?.length ? new Date(h.snapshots[h.snapshots.length - 1].recorded_at) : null;

  return (
    <header className="relative z-30 flex h-11 shrink-0 items-center gap-3 overflow-hidden border-b border-line bg-panel px-3">
      <Link href="/" className="flex items-center gap-2 pr-2">
        <OrcaMark />
        <span className="font-cond text-[15px] font-semibold tracking-[0.22em] text-ink">ORCA</span>
      </Link>

      <div className="flex items-center rounded-md border border-line-2 p-0.5" role="radiogroup" aria-label="data mode">
        {MODES.map((m) => (
          <button key={m.id} title={m.hint} aria-label={`${m.id} mode — ${m.hint}`} onClick={() => setMode(m.id)} role="radio" aria-checked={mode === m.id}
            className={`flex items-center gap-1.5 rounded px-2.5 py-1 font-cond text-[11px] font-semibold tracking-[0.14em] transition-colors ${mode === m.id ? "bg-panel-3 text-ink" : "text-ink-3 hover:text-ink-2"}`}>
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${mode === m.id && m.id === "LIVE" ? "pulse" : ""}`} style={{ background: mode === m.id ? m.color : "var(--ink-3)" }} />
            {m.id}
          </button>
        ))}
      </div>
      {mode === "DEMO" && (
        <select value={scenario ?? ""} onChange={(e) => setMode("DEMO", e.target.value)}
          aria-label="demo scenario" className="w-[190px] shrink-0 truncate rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px] text-ink focus:outline-none xl:w-[250px]">
          {scen.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
      )}

      <div className="ml-2 hidden items-center gap-5 lg:flex">
        <div className="flex items-baseline gap-1.5" title="Sources currently responding / registered">
          <span className="lbl">Sources</span>
          <span className="num text-[12.5px]"><span style={{ color: "var(--live)" }}>{h?.sources.operational ?? "–"}</span><span className="text-ink-3">/{h?.sources.total ?? "–"}</span></span>
        </div>
        <div className="flex items-baseline gap-1.5"><span className="lbl">Agents</span><span className="num text-[12.5px]">{h?.agents.count ?? "–"}</span></div>
        <Link href="/safety" className="flex items-baseline gap-1.5"><span className="lbl">Alerts</span><span className="num text-[12.5px]" style={{ color: alerts ? "var(--caution)" : undefined }}>{alerts}</span></Link>
        <div className="hidden items-baseline gap-1.5 2xl:flex" title="LLM is optional; used only for interpretation fallback and grounded narration">
          <span className="lbl">LLM</span><span className="text-[11.5px] text-ink-2">{h ? (h.llm.available ? "on · grounded" : "off · templates") : "–"}</span>
        </div>
        {err && <span className="text-[11.5px] text-danger">API unreachable</span>}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-4">
        {turn?.traceId && (
          <Link href={`/evidence?trace=${turn.traceId}`} className="num hidden rounded border xl:inline border-line-2 px-2 py-0.5 text-[11px] text-ink-2 hover:text-ink" title="Inspect full reasoning trace">
            {turn.traceId}
          </Link>
        )}
        {virtual && <Clock label={mode === "DEMO" ? "Scenario" : "Recorded"} tz="Asia/Kolkata" date={virtual} />}
        <span className="hidden lg:inline"><Clock label="UTC" tz="UTC" date={now} /></span>
        <Clock label="IST" tz="Asia/Kolkata" date={now} />
      </div>
    </header>
  );
}

export function ModeBanner() {
  const { mode, scenario } = useOrca();
  if (mode === "LIVE") return null;
  return (
    <div className={`relative z-20 flex h-6 shrink-0 items-center justify-center gap-2 border-b border-line text-[11px] font-medium tracking-wide ${mode === "DEMO" ? "demo-tape text-demo" : "replay-tape text-replay"}`}>
      {mode === "DEMO"
        ? <>DEMO MODE — every environmental value is SIMULATED · scenario <span className="num">{scenario}</span> · agents, risk model and evidence logic are the real ones</>
        : <>REPLAY MODE — recorded real responses from public endpoints, shown with their original timestamps · never LIVE</>}
    </div>
  );
}
