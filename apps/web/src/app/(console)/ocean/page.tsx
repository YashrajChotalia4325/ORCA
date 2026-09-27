"use client";
import { useEffect, useRef, useState } from "react";
import { FreshTag, ModelChart, Section } from "@/components/result/primitives";
import { IntelPanel, PanelHeader, useMapClick } from "@/components/shell/ConsoleShell";
import { get, modeQuery } from "@/lib/api";
import { useOrca } from "@/lib/store";
import type { FreshnessStatus } from "@/lib/types";

type PS = { units: string; times: string[]; values: (number | null)[]; provenance: { source: string; issued_at?: string; freshness: { status: FreshnessStatus; label: string }; spatial_resolution: string } };
type PointResp = { models: Record<string, { source: string; failures: { reason: string }[]; series: Record<string, PS> }> };
type SatResp = Record<string, { value: { value: number; units: string; valid_time: string; grid_location: { lat: number; lon: number }; provenance: { freshness: { status: FreshnessStatus; label: string } } } | null; failures: { reason: string }[] }>;

const PANELS: { key: string; label: string; from: "ocean" | "weather"; units: string }[] = [
  { key: "wave_height", label: "Significant wave height", from: "ocean", units: "m" },
  { key: "swell_height", label: "Swell height", from: "ocean", units: "m" },
  { key: "current_speed", label: "Surface current", from: "ocean", units: "km/h" },
  { key: "wind_speed", label: "Wind (10 m)", from: "weather", units: "km/h" },
  { key: "wind_gusts", label: "Gusts", from: "weather", units: "km/h" },
  { key: "precipitation", label: "Rain rate", from: "weather", units: "mm/h" },
];

export default function LiveOcean() {
  const { mode, scenario, layers, toggleLayer, setHighlight } = useOrca();
  const register = useMapClick();
  const [pt, setPt] = useState<{ lat: number; lon: number } | null>(null);
  const [result, setData] = useState<{ key: string; ocean?: PointResp; weather?: PointResp; sat?: SatResp; err?: string } | null>(null);
  const ptKey = pt ? `${pt.lat.toFixed(3)},${pt.lon.toFixed(3)}:${mode}:${scenario}` : "";
  const data = result && result.key === ptKey ? result : null;

  const inspect = (lat: number, lon: number) => {
    setPt({ lat, lon });
    setHighlight({ lat, lon });
    const key = `${lat.toFixed(3)},${lon.toFixed(3)}:${mode}:${scenario}`;
    const q = `lat=${lat.toFixed(3)}&lon=${lon.toFixed(3)}&hours=48&${modeQuery(mode, scenario)}`;
    Promise.all([get<PointResp>(`/api/ocean?${q}`), get<PointResp>(`/api/weather?${q}`), get<SatResp>(`/api/satellite?${q}`)])
      .then(([ocean, weather, sat]) => setData({ key, ocean, weather, sat }))
      .catch((e) => setData({ key, err: String(e) }));
  };
  const inspectRef = useRef(inspect);
  useEffect(() => { inspectRef.current = inspect; });
  useEffect(() => {
    register((lat, lon) => inspectRef.current(lat, lon));
    return () => register(undefined);
  }, [register]);
  useEffect(() => { if (!["waves", "wind", "currents"].some((k) => layers[k])) toggleLayer("waves", true); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fields = [["waves", "Waves · MFWAM"], ["wind", "Wind · GFS"], ["currents", "Currents · SMOC"]];
  const sats = [["gibs_sst", "SST"], ["gibs_sst_anomaly", "SST anomaly"], ["gibs_chlorophyll", "Chlorophyll"], ["gibs_precip", "Rain"]];
  return (
    <IntelPanel width={450}>
      <PanelHeader kicker="Live ocean" title="Forecast fields & satellite layers" />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <Section title="Forecast field (one at a time)">
          <div className="flex flex-wrap gap-1.5">
            {fields.map(([id, l]) => (
              <button key={id} onClick={() => { fields.forEach(([f]) => toggleLayer(f, f === id ? !layers[id] : false)); }}
                className={`rounded border px-2.5 py-1 text-[12px] ${layers[id] ? "border-accent text-accent" : "border-line-2 text-ink-2"}`}>{l}</button>
            ))}
          </div>
          <div className="lbl mb-1.5 mt-3">Satellite imagery (NASA GIBS, real daily dates)</div>
          <div className="flex flex-wrap gap-1.5">
            {sats.map(([id, l]) => (
              <button key={id} onClick={() => toggleLayer(id)} className={`rounded border px-2.5 py-1 text-[12px] ${layers[id] ? "border-accent-2 text-accent-2" : "border-line-2 text-ink-2"}`}>{l}</button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-ink-3">Use the time bar (top-left) to move −6 h … +24 h. Forecast fields exist only from the model&apos;s first forecast hour; satellite layers show the latest product that actually exists for the chosen day.</p>
        </Section>
        <Section title="Point inspector">
          {!pt && <p className="text-[12px] text-ink-2">Click anywhere at sea to compare every model at that point.</p>}
          {pt && <div className="num mb-2 text-[12px] text-accent">{pt.lat.toFixed(3)}°N {pt.lon.toFixed(3)}°E</div>}
          {pt && !data && <p className="scanline rounded bg-panel-2 px-2 py-1 text-[12px] text-ink-2">querying models…</p>}
          {data?.err && <p className="text-[12px] text-danger">{data.err}</p>}
          {data?.sat && (
            <div className="mb-3 grid grid-cols-3 gap-2">
              {Object.entries(data.sat).map(([k, v]) => (
                <div key={k} className="rounded border border-line-2 p-2">
                  <div className="lbl">{({ sst: "Sat. SST", sst_anomaly: "SST anom.", chlorophyll: "Chl-a" } as Record<string, string>)[k]}</div>
                  {v.value ? <><div className="num text-[15px] text-ink">{v.value.value.toFixed(2)}<span className="text-[10.5px] text-ink-3"> {v.value.units}</span></div><div className="text-[10px] text-ink-3">product {v.value.valid_time.slice(0, 10)}</div></>
                    : <div className="text-[11px] text-ink-3" title={v.failures[0]?.reason}>unavailable</div>}
                </div>
              ))}
            </div>
          )}
          {data?.ocean && data.weather && PANELS.map((p) => {
            const src = p.from === "ocean" ? data.ocean! : data.weather!;
            const series = Object.entries(src.models).filter(([, m]) => m.series[p.key]).map(([, m]) => ({ name: m.source, times: m.series[p.key].times, values: m.series[p.key].values }));
            const provs = Object.entries(src.models).filter(([, m]) => m.series[p.key]).map(([, m]) => m.series[p.key].provenance);
            const failed = Object.values(src.models).filter((m) => !Object.keys(m.series).length);
            if (!series.length) return null;
            return (
              <div key={p.key} className="mb-3">
                <div className="mb-0.5 text-[12px] text-ink">{p.label}</div>
                <ModelChart series={series} units={p.units} height={84} />
                <div className="mt-0.5 flex flex-wrap gap-x-3">{provs.map((pv) => <span key={pv.source} className="text-[10px] text-ink-3">{pv.source}{pv.issued_at ? ` run ${pv.issued_at.slice(11, 13)}Z` : ""} · <FreshTag status={pv.freshness.status} /></span>)}</div>
                {failed.length > 0 && <div className="text-[10px] text-danger">{failed.map((f) => `${f.source}: ${f.failures[0]?.reason ?? "no data"}`).join(" · ")}</div>}
              </div>
            );
          })}
        </Section>
      </div>
    </IntelPanel>
  );
}
