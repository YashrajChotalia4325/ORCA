"use client";
import { useState } from "react";
import { useOrca, type Basemap } from "@/lib/store";
import { IcLayers } from "../shell/icons";

const OFFSETS = [-6, -3, 0, 3, 6, 12, 24];

export function TimeSlider() {
  const { timeOffsetH, setTimeOffset } = useOrca();
  return (
    <div className="flex items-center gap-1 rounded-md border border-line-2 bg-panel/90 p-1 backdrop-blur" role="radiogroup" aria-label="map time">
      <span className="lbl px-1.5">Time</span>
      {OFFSETS.map((h) => (
        <button key={h} role="radio" aria-checked={timeOffsetH === h} onClick={() => setTimeOffset(h)}
          className={`num rounded px-2 py-0.5 text-[11px] ${timeOffsetH === h ? "bg-accent text-abyss" : "text-ink-2 hover:bg-panel-3"}`}>
          {h === 0 ? "NOW" : `${h > 0 ? "+" : ""}${h}h`}
        </button>
      ))}
    </div>
  );
}

const GROUPS: { title: string; items: { id: string; label: string; note?: string }[] }[] = [
  { title: "Forecast fields", items: [
    { id: "waves", label: "Wave height", note: "MFWAM" }, { id: "wind", label: "Wind", note: "GFS" }, { id: "currents", label: "Currents", note: "SMOC" }] },
  { title: "Satellite (NASA GIBS)", items: [
    { id: "gibs_sst", label: "SST (MUR L4)" }, { id: "gibs_sst_anomaly", label: "SST anomaly" },
    { id: "gibs_chlorophyll", label: "Chlorophyll-a (PACE)" }, { id: "gibs_precip", label: "Rain rate (IMERG)" }] },
  { title: "Boundaries & zones", items: [
    { id: "eez", label: "EEZ" }, { id: "boundaries", label: "Maritime boundaries" }, { id: "zones", label: "Protected / restricted (approx.)" }, { id: "ports", label: "Ports & harbours" }] },
  { title: "Hazards & results", items: [
    { id: "cyclones", label: "Cyclones (GDACS)" }, { id: "route", label: "Routes & risk segments" }, { id: "fishing_zones", label: "Fishing zones" },
    { id: "stations", label: "Coastal stations" }, { id: "samples", label: "Sample points" }, { id: "evidence", label: "Evidence locations" }] },
];

export function LayerPanel() {
  const { layers, toggleLayer, basemap, setBasemap } = useOrca();
  const [open, setOpen] = useState(false);
  const fieldIds = ["waves", "wind", "currents"];
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md border border-line-2 bg-panel/90 px-2.5 py-1.5 text-[12px] text-ink-2 backdrop-blur hover:text-ink">
        <IcLayers width={15} height={15} /> Layers
      </button>
      {open && (
        <div className="rise absolute right-0 top-9 z-30 w-[250px] rounded-md border border-line-2 bg-panel p-3 shadow-2xl">
          <div className="lbl mb-1.5">Basemap</div>
          <div className="mb-3 grid grid-cols-3 gap-1">
            {(["dark", "satellite", "relief"] as Basemap[]).map((b) => (
              <button key={b} onClick={() => setBasemap(b)}
                className={`rounded border px-1.5 py-1 text-[11px] capitalize ${basemap === b ? "border-accent text-accent" : "border-line-2 text-ink-2"}`}>{b === "satellite" ? "VIIRS" : b}</button>
            ))}
          </div>
          {GROUPS.map((g) => (
            <div key={g.title} className="mb-2.5">
              <div className="lbl mb-1">{g.title}</div>
              {g.items.map((it) => (
                <label key={it.id} className="flex cursor-pointer items-center justify-between py-[3px] text-[12px] text-ink-2 hover:text-ink">
                  <span className="flex items-center gap-2">
                    <input type="checkbox" className="accent-[var(--accent)]" checked={!!layers[it.id]}
                      onChange={(e) => {
                        if (fieldIds.includes(it.id) && e.target.checked) fieldIds.forEach((f) => f !== it.id && toggleLayer(f, false));
                        toggleLayer(it.id, e.target.checked);
                      }} />
                    {it.label}
                  </span>
                  {it.note && <span className="text-[10px] text-ink-3">{it.note}</span>}
                </label>
              ))}
            </div>
          ))}
          <p className="mt-1 border-t border-line pt-2 text-[10.5px] leading-snug text-ink-3">
            GIBS layers are imagery for context; ORCA never reads numbers from tiles. Zone outlines marked approximate are not legal boundaries.
          </p>
        </div>
      )}
    </div>
  );
}
