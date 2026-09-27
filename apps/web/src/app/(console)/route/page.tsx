"use client";
import { useEffect, useState } from "react";
import TurnView from "@/components/TurnView";
import { Section } from "@/components/result/primitives";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useOrca } from "@/lib/store";

type Ports = { layers: { ports: GeoJSON.FeatureCollection } };
const PRESETS: [string, string, string][] = [["mumbai", "goa", "Mumbai → Goa"], ["kochi", "kavaratti", "Kochi → Kavaratti"], ["thoothukudi", "rameswaram", "Thoothukudi → Rameswaram"], ["chennai", "visakhapatnam", "Chennai → Visakhapatnam"]];

function tomorrow6(): string {
  const d = new Date(Date.now() + 24 * 3600e3);
  const ist = new Date(d.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  return `${ist.getFullYear()}-${String(ist.getMonth() + 1).padStart(2, "0")}-${String(ist.getDate()).padStart(2, "0")}T06:00`;
}

export default function RoutePlanner() {
  const { mode, scenario, conversationId, attachTurn, turns, toggleLayer } = useOrca();
  const ports = useApi<Ports>("/api/boundaries");
  const [o, setO] = useState("mumbai");
  const [d, setD] = useState("goa");
  const [dep, setDep] = useState(tomorrow6());
  const [vessel, setVessel] = useState("mechanized");
  const [speed, setSpeed] = useState("9");
  const [tid, setTid] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { toggleLayer("route", true); toggleLayer("waves", true); }, [toggleLayer]);
  const list = (ports.data?.layers.ports.features ?? []).map((f) => ({ id: String(f.properties?.id), name: String(f.properties?.name) })).sort((a, b) => a.name.localeCompare(b.name));

  const run = async () => {
    setErr(null);
    try {
      // departure entered in IST → ISO with +05:30
      const r = await post<{ query_id: string; trace_id: string }>("/api/route/analyze", {
        origin: o, destination: d, departure: `${dep}:00+05:30`, vessel_class: vessel, speed_kn: Number(speed), mode,
        scenario: mode === "DEMO" ? scenario : null, conversation_id: conversationId,
      });
      const names = `${list.find((p) => p.id === o)?.name} → ${list.find((p) => p.id === d)?.name}`;
      const p = attachTurn(r.query_id, r.trace_id, `Route ${names}, departing ${dep.replace("T", " ")} IST`);
      setTid(useOrca.getState().activeTurnId);
      await p;
    } catch (e) { setErr(String(e)); }
  };
  const turn = turns.find((t) => t.id === tid);
  return (
    <IntelPanel width={460}>
      <PanelHeader kicker="Route planner" title="Time-dependent A* over live forecasts" />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <Section title="Voyage">
          <div className="grid grid-cols-2 gap-2 text-[12px]">
            {[["From", o, setO], ["To", d, setD]].map(([l, v, s]) => (
              <label key={l as string} className="text-[10.5px] text-ink-3">{l as string}
                <select value={v as string} onChange={(e) => (s as (x: string) => void)(e.target.value)} className="mt-0.5 w-full rounded border border-line-2 bg-panel-2 px-2 py-1.5 text-[12.5px] text-ink">
                  {list.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
            ))}
            <label className="text-[10.5px] text-ink-3">Departure (IST)<input type="datetime-local" value={dep} onChange={(e) => setDep(e.target.value)} className="num mt-0.5 w-full rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px] text-ink" /></label>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[10.5px] text-ink-3">Vessel<select value={vessel} onChange={(e) => setVessel(e.target.value)} className="mt-0.5 w-full rounded border border-line-2 bg-panel-2 px-1 py-1.5 text-[12px] text-ink">
                <option value="small_craft">small craft</option><option value="mechanized">mechanised</option><option value="large_vessel">large</option></select></label>
              <label className="text-[10.5px] text-ink-3">Speed kn<input value={speed} onChange={(e) => setSpeed(e.target.value)} className="num mt-0.5 w-full rounded border border-line-2 bg-panel-2 px-2 py-1 text-[12px] text-ink" /></label>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {PRESETS.map(([a, b, l]) => <button key={l} onClick={() => { setO(a); setD(b); }} className="rounded border border-line-2 px-2 py-0.5 text-[11px] text-ink-2 hover:text-ink">{l}</button>)}
          </div>
          <button onClick={run} className="mt-2.5 w-full rounded bg-accent py-2 text-[13px] font-medium text-abyss">Optimise & evaluate route</button>
          {err && <p className="mt-1 text-[11.5px] text-danger">{err}</p>}
          <p className="mt-2 text-[11px] leading-snug text-ink-3">
            The router builds an hourly worst-of-models risk cube (waves, wind, gusts, currents, rain) and searches a land-masked grid. Restricted areas are impassable,
            protected areas cost ×6, fishing craft cannot cross into foreign EEZs. Shortest, recommended and lowest-risk options are compared segment by segment at ETA.
          </p>
        </Section>
        <TurnView turn={turn} empty={null} />
      </div>
    </IntelPanel>
  );
}
