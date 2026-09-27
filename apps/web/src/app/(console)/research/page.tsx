"use client";
import { useEffect, useState } from "react";
import TurnView from "@/components/TurnView";
import { ModelChart, Section } from "@/components/result/primitives";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { useOrca } from "@/lib/store";

const PLACES = ["Kochi", "Mangaluru", "Ratnagiri", "Mumbai", "Chennai", "Visakhapatnam", "Thoothukudi", "Kollam", "Veraval", "Paradip"];
const TEMPLATES: Record<string, (p: string, n: number) => string> = {
  chl_decline: (p, n) => `Why did chlorophyll concentration decline off ${p} over the past ${n} days?`,
  sst_rise: (p, n) => `Why did SST increase near ${p} in the last ${n} days?`,
  compare: (p) => `Compare this week's marine conditions near ${p} with last week`,
  productivity: (p, n) => `Why is productivity lower off ${p} over the past ${n} days?`,
};

export default function Research() {
  const { runQuery, turns, toggleLayer, setPrefs } = useOrca();
  const [place, setPlace] = useState("Kochi");
  const [tpl, setTpl] = useState("chl_decline");
  const [days, setDays] = useState(14);
  const [tid, setTid] = useState<string | null>(null);
  useEffect(() => { toggleLayer("gibs_sst_anomaly", true); }, [toggleLayer]);
  const turn = turns.find((t) => t.id === tid);
  const series = turn?.bb?.outputs?.satellite?.series as Record<string, { times: string[]; values: (number | null)[] }> | undefined;
  const wind = turn?.bb?.outputs?.weather?.primary_series?.wind_speed as Record<string, { times: string[]; values: (number | null)[] }> | undefined;
  const q = TEMPLATES[tpl](place, days);
  const go = async () => { setPrefs({ role: "researcher" }); const p = runQuery(q); setTid(useOrca.getState().activeTurnId); await p; setPrefs({ role: null }); };
  return (
    <IntelPanel width={480}>
      <PanelHeader kicker="Research mode" title="Observation · correlation · hypothesis · conclusion" />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <Section title="Question">
          <div className="grid grid-cols-3 gap-2 text-[12px]">
            <select value={place} onChange={(e) => setPlace(e.target.value)} className="rounded border border-line-2 bg-panel-2 px-2 py-1.5 text-ink">{PLACES.map((p) => <option key={p}>{p}</option>)}</select>
            <select value={tpl} onChange={(e) => setTpl(e.target.value)} className="rounded border border-line-2 bg-panel-2 px-2 py-1.5 text-ink">
              <option value="chl_decline">chlorophyll decline</option><option value="sst_rise">SST increase</option><option value="productivity">low productivity</option><option value="compare">week vs week</option>
            </select>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-line-2 bg-panel-2 px-2 py-1.5 text-ink">{[7, 10, 14, 21].map((n) => <option key={n} value={n}>{n} days</option>)}</select>
          </div>
          <p className="mt-2 rounded border border-line bg-panel-2 px-2.5 py-1.5 text-[12.5px] text-ink">{q}</p>
          <button onClick={go} className="mt-2 w-full rounded bg-accent py-1.5 text-[12.5px] font-medium text-abyss">Analyse</button>
          <p className="mt-2 text-[11px] leading-snug text-ink-3">Daily area-means of satellite SST, SST anomaly and chlorophyll (NOAA CoastWatch) plus model wind history are compared across periods (Welch t-test), trended and correlated (lagged Pearson). Hypotheses are evaluated against explicit evidence; ORCA never infers causation from correlation and will say so when the question&apos;s premise is not supported.</p>
        </Section>
        {series && Object.keys(series).length > 0 && (
          <Section title="Satellite time series (daily area mean)">
            {Object.entries(series).map(([k, s]) => (
              <div key={k} className="mb-2">
                <div className="mb-0.5 text-[12px] text-ink">{({ sst: "Sea-surface temperature (°C)", sst_anomaly: "SST anomaly (°C)", chlorophyll: "Chlorophyll-a (mg/m³)" } as Record<string, string>)[k] ?? k}</div>
                <ModelChart series={[{ name: "NOAA CoastWatch", times: s.times, values: s.values }]} units={k === "chlorophyll" ? "mg/m³" : "°C"} height={78} />
              </div>
            ))}
            {wind && Object.entries(wind).slice(0, 1).map(([sid, s]) => <div key={sid}><div className="mb-0.5 text-[12px] text-ink">Wind speed history ({sid})</div><ModelChart series={[{ name: sid, times: s.times, values: s.values }]} units="km/h" height={78} /></div>)}
          </Section>
        )}
        <TurnView turn={turn} empty={null} />
      </div>
    </IntelPanel>
  );
}
