"use client";
import { useEffect, useState } from "react";
import { Section } from "@/components/result/primitives";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { API, post } from "@/lib/api";
import { ago, ist } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useOrca } from "@/lib/store";
import type { Alert } from "@/lib/types";

const CAT_ICON: Record<string, string> = { cyclone: "🌀", waves: "≋", wind: "➶", lightning: "ϟ", geofence: "⬡", boundary: "⟂", official: "⚑", rain: "☂", current: "↝" };

export default function Safety() {
  const { mode, scenario, flyTo } = useOrca();
  const [filter, setFilter] = useState<"all" | "severe" | "verified">("all");
  const list = useApi<Alert[]>(`/api/alerts?limit=200&mode=${mode}`, 60000);
  const [live, setLive] = useState<Alert[]>([]);
  const [scan, setScan] = useState<{ events: { type: string; region: string; hs?: number; ws?: number }[]; verified: { region: string; trace_id: string; decision: string; alerts: number }[]; alerts_generated: number } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [watch, setWatch] = useState({ name: "FV Sagarika", lat: "9.20", lon: "79.35", radius_km: "15" });
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const es = new EventSource(`${API}/api/alerts/stream`);
    es.onmessage = (m) => { try { const a = JSON.parse(m.data) as Alert; setLive((l) => [a, ...l].slice(0, 50)); } catch { /* ignore */ } };
    return () => es.close();
  }, []);

  const all = [...live.filter((a) => a.mode === mode), ...(list.data ?? [])].filter((a, i, arr) => arr.findIndex((b) => b.id === a.id) === i);
  const shown = all.filter((a) => filter === "all" || (filter === "severe" ? a.severity === "severe" : a.verified));

  const runScan = async () => {
    setScanning(true); setScan(null);
    try { setScan(await post(`/api/alerts/scan?mode=${mode}${mode === "DEMO" && scenario ? `&scenario=${scenario}` : ""}`)); list.reload(); }
    catch (e) { setMsg(String(e)); }
    finally { setScanning(false); }
  };
  const addWatch = async () => {
    try {
      await post("/api/alerts", { name: watch.name, lat: Number(watch.lat), lon: Number(watch.lon), radius_km: Number(watch.radius_km), kind: "point" });
      setMsg(`Watch registered for ${watch.name}; the monitor checks it against zones and boundaries every cycle.`);
    } catch (e) { setMsg(String(e)); }
  };
  const ack = async (id: string) => { await post(`/api/alerts/${id}/ack`); list.reload(); };

  return (
    <IntelPanel width={460}>
      <PanelHeader kicker="Safety & alerts" title="Alert centre" right={
        <button onClick={runScan} disabled={scanning} className="rounded bg-accent px-2.5 py-1 text-[12px] font-medium text-abyss disabled:opacity-50">{scanning ? "Scanning…" : "Run monitoring scan"}</button>} />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <Section title="How alerts are produced">
          <p className="text-[11.5px] leading-snug text-ink-2">
            <b className="text-ink">EVENT</b> (scan of 1 wave + 1 wind model at ~40 offshore stations, GDACS cyclones, registered watches) →
            <b className="text-ink"> VERIFY</b> (full multi-agent re-assessment of the sector with all models and advisories) →
            <b className="text-ink"> GENERATE</b> (only claims with an official advisory or ≥ 2 agreeing independent lineages are marked verified) →
            <b className="text-ink"> DELIVER</b> (stored, streamed live to this page).
          </p>
        </Section>
        {scan && (
          <Section title="Last scan">
            <p className="text-[12px] text-ink-2">{scan.events.length} event(s) · {scan.verified.length} verification run(s) · {scan.alerts_generated} alert(s)</p>
            {scan.events.map((e, i) => <p key={i} className="text-[11.5px] text-caution">▲ {e.type.replace("_", " ")} · {e.region.replace("_", " ")}{e.hs ? ` · Hs ${e.hs} m` : ""}{e.ws ? ` · ${e.ws} km/h` : ""}</p>)}
            {scan.verified.map((v) => <a key={v.trace_id} href={`/evidence?trace=${v.trace_id}`} className="block text-[11.5px] text-accent">↳ verified by {v.trace_id}: {v.decision} ({v.alerts} alerts)</a>)}
          </Section>
        )}
        <Section title={`Alerts · ${mode}`} right={
          <div className="flex gap-1 text-[11px]">{(["all", "severe", "verified"] as const).map((f) => <button key={f} onClick={() => setFilter(f)} className={`rounded px-1.5 py-0.5 ${filter === f ? "bg-panel-3 text-ink" : "text-ink-3"}`}>{f}</button>)}</div>}>
          {!shown.length && <p className="text-[12px] text-ink-3">No alerts. Alerts appear only when a threshold is crossed in real (LIVE/REPLAY) or clearly simulated (DEMO) data.</p>}
          {shown.map((a) => (
            <div key={a.id} className={`rise mb-2 rounded border p-2.5 ${a.status === "acknowledged" ? "opacity-55" : ""}`} style={{ borderColor: a.severity === "severe" ? "color-mix(in oklab, var(--danger) 50%, transparent)" : "var(--line-2)" }}>
              <div className="flex items-start gap-2">
                <span className="text-[14px]" style={{ color: a.severity === "severe" ? "var(--danger)" : "var(--caution)" }} aria-hidden>{CAT_ICON[a.category] ?? "▲"}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] text-ink">{a.title}</div>
                  <p className="mt-0.5 text-[11.5px] leading-snug text-ink-2">{a.message}</p>
                  <div className="mt-1 flex flex-wrap gap-x-3 text-[10.5px] text-ink-3">
                    <span style={{ color: a.severity === "severe" ? "var(--danger)" : "var(--caution)" }}>{a.severity.toUpperCase()}</span>
                    <span className={a.verified ? "text-go" : "text-ink-3"}>{a.verified ? "✓ verified" : "unverified signal"}</span>
                    <span>{a.verification}</span>
                    <span>{ago(a.created_at)}</span>
                    {a.valid_to && <span>until {ist(a.valid_to)}</span>}
                    <span className={a.mode === "DEMO" ? "text-demo" : a.mode === "REPLAY" ? "text-replay" : "text-live"}>{a.mode}</span>
                  </div>
                </div>
              </div>
              <div className="mt-1.5 flex gap-2 text-[11px]">
                {a.location && <button onClick={() => flyTo(a.location!.lat, a.location!.lon, 7)} className="text-accent">show on map</button>}
                {a.trace_id && <a href={`/evidence?trace=${a.trace_id}`} className="text-accent">evidence</a>}
                {a.status !== "acknowledged" && <button onClick={() => ack(a.id)} className="text-ink-3 hover:text-ink-2">acknowledge</button>}
              </div>
            </div>
          ))}
        </Section>
        <Section title="Register a vessel / point watch (geofencing)">
          <div className="grid grid-cols-4 gap-1.5 text-[12px]">
            <input value={watch.name} onChange={(e) => setWatch({ ...watch, name: e.target.value })} className="col-span-4 rounded border border-line-2 bg-panel-2 px-2 py-1 text-ink" aria-label="name" />
            {(["lat", "lon", "radius_km"] as const).map((k) => (
              <label key={k} className="text-[10.5px] text-ink-3">{k}<input value={watch[k]} onChange={(e) => setWatch({ ...watch, [k]: e.target.value })} className="num mt-0.5 w-full rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px] text-ink" /></label>
            ))}
            <button onClick={addWatch} className="self-end rounded border border-accent/60 py-1 text-accent">Add</button>
          </div>
          {msg && <p className="mt-1.5 text-[11.5px] text-ink-2">{msg}</p>}
        </Section>
      </div>
    </IntelPanel>
  );
}
