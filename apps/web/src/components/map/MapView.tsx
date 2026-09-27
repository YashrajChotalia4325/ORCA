"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MLMap, GeoJSONSource, RasterTileSource, MapMouseEvent } from "maplibre-gl";
import { get, modeQuery } from "@/lib/api";
import { useActiveTurn, useOrca } from "@/lib/store";
import { ist } from "@/lib/format";

type Gibs = { id: string; title: string; tile_template: string; maxzoom: number; latest_date?: string | null; time_dependent: boolean; available: boolean };
type Field = { layer: string; label: string; units: string; source: string; times: string[]; points: { lat: number; lon: number; v: (number | null)[]; d: (number | null)[] }[]; provenance?: { issued_at?: string; freshness?: { label: string; status: string } } | null; mode: string };

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const FIELD_STYLE: Record<string, { stops: [number, string][]; label: string }> = {
  waves: { label: "Hs (m)", stops: [[0, "#cde2fb"], [0.75, "#86b6ef"], [1.5, "#3987e5"], [2.5, "#1c5cab"], [4, "#0d366b"]] },
  wind: { label: "Wind (km/h)", stops: [[0, "#fde2d3"], [15, "#f5b08e"], [28, "#e8804f"], [45, "#d95926"], [70, "#8f3310"]] },
  currents: { label: "Current (km/h)", stops: [[0, "#cff2e4"], [1, "#8fdcbd"], [2.5, "#3fbf8f"], [4, "#199e70"], [6, "#0b5e41"]] },
};
export const GIBS_OVERLAYS = ["gibs_sst", "gibs_sst_anomaly", "gibs_chlorophyll", "gibs_precip"];
const DECISION_COLOR = ["match", ["get", "decision"], "GO", "#0ca30c", "CAUTION", "#fab219", "DONT_GO", "#d03b3b", "#8491a3"];
const LEVEL_COLOR = ["match", ["get", "level"], "NOMINAL", "#0ca30c", "CAUTION", "#fab219", "DANGER", "#d03b3b", "#8491a3"];

function arrowImage(): { width: number; height: number; data: Uint8Array } {
  const s = 24, c = document.createElement("canvas");
  c.width = s; c.height = s;
  const g = c.getContext("2d")!;
  g.strokeStyle = "rgba(230,240,248,0.95)"; g.fillStyle = "rgba(230,240,248,0.95)"; g.lineWidth = 2;
  g.beginPath(); g.moveTo(12, 21); g.lineTo(12, 5); g.stroke();
  g.beginPath(); g.moveTo(12, 2); g.lineTo(7, 9); g.lineTo(17, 9); g.closePath(); g.fill();
  return { width: s, height: s, data: new Uint8Array(g.getImageData(0, 0, s, s).data.buffer) };
}

function dateFor(latest: string | null | undefined, t: Date): string | null {
  if (!latest) return null;
  const d = t.toISOString().slice(0, 10);
  return d <= latest ? d : latest;
}

export interface MapViewProps { onMapClick?: (lat: number, lon: number) => void; virtualNow?: string | null }

export default function MapView({ onMapClick, virtualNow }: MapViewProps) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [gibs, setGibs] = useState<Gibs[]>([]);
  const [fields, setFields] = useState<Record<string, Field | null>>({});
  const { layers, basemap, timeOffsetH, focus, mode, scenario, highlight } = useOrca();
  const turn = useActiveTurn();
  const bb = turn?.bb;
  const clickRef = useRef(onMapClick);
  useEffect(() => { clickRef.current = onMapClick; }, [onMapClick]);
  const [wallNow, setWallNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setWallNow(Math.floor(Date.now() / 60000) * 60000);   // minute resolution is enough for layer timing
    const first = setTimeout(tick, 0);
    const i = setInterval(tick, 60000);
    return () => { clearTimeout(first); clearInterval(i); };
  }, []);

  const refNow = useMemo(() => new Date(virtualNow ?? bb?.virtual_now ?? wallNow ?? 0), [virtualNow, bb?.virtual_now, wallNow]);
  const targetTime = useMemo(() => new Date(refNow.getTime() + timeOffsetH * 3600e3), [refNow, timeOffsetH]);

  // ------------------------------------------------------------------ init
  useEffect(() => {
    let disposed = false;
    (async () => {
      const ml = await import("maplibre-gl");
      ml.setWorkerUrl(new URL("/maplibre/maplibre-gl-worker.mjs", window.location.origin).href);
      if (disposed || !el.current) return;
      const map = new ml.Map({
        container: el.current,
        center: [78.5, 13.5],
        zoom: 4.3,
        minZoom: 3.2,
        maxBounds: [[52, -12], [108, 34]],
        maxZoom: 12,
        attributionControl: { compact: true },
        style: {
          version: 8,
          sources: {
            land: { type: "geojson", data: EMPTY, attribution: "Land: Natural Earth (public domain)" },
            relief: { type: "raster", tiles: ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg"], tileSize: 256, maxzoom: 8, attribution: "NASA EOSDIS GIBS" },
          },
          layers: [
            { id: "bg", type: "background", paint: { "background-color": "#050b12" } },
            { id: "base-dark", type: "fill", source: "land", paint: { "fill-color": "#101b27", "fill-outline-color": "#23384d" } },
            { id: "base-coast", type: "line", source: "land", paint: { "line-color": "#2c4660", "line-width": 0.8 } },
            { id: "base-relief", type: "raster", source: "relief", layout: { visibility: "none" }, paint: { "raster-saturation": -0.3, "raster-brightness-max": 0.75 } },
          ],
        },
      });
      map.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
      map.addControl(new ml.ScaleControl({ unit: "nautical" }), "bottom-right");
      map.on("load", () => {
        map.addImage("arrow", arrowImage(), { sdf: false });
        const gj = (id: string) => map.addSource(id, { type: "geojson", data: EMPTY });
        ["eez", "boundaries", "zones", "ports", "cyclones", "field", "q-samples", "q-route", "q-segments", "q-zones", "q-cyclones", "q-stations", "q-evidence", "highlight"].forEach(gj);
        map.addLayer({ id: "eez-fill", type: "fill", source: "eez", paint: { "fill-color": ["case", ["get", "is_india"], "#43d3c6", "#5f7489"], "fill-opacity": 0.025 } });
        map.addLayer({ id: "eez-line", type: "line", source: "eez", paint: { "line-color": ["case", ["get", "is_india"], "#2a6f6a", "#34485c"], "line-width": 0.8 } });
        map.addLayer({ id: "field-dots", type: "circle", source: "field", paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 5, 6, 11, 8, 18], "circle-opacity": 0.55, "circle-blur": 0.6, "circle-color": "#3987e5" } });
        map.addLayer({ id: "field-arrows", type: "symbol", source: "field", layout: { "icon-image": "arrow", "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 0.45, 7, 0.8], "icon-rotate": ["+", ["coalesce", ["get", "d"], 0], 180], "icon-rotation-alignment": "map", "icon-allow-overlap": true }, paint: { "icon-opacity": 0.7 } });
        map.addLayer({ id: "zones-fill", type: "fill", source: "zones", paint: { "fill-color": ["match", ["get", "kind"], "mpa", "#199e70", "restricted", "#d03b3b", "seasonal_restriction", "#c98500", "geofence", "#b39cff", "#5f7489"], "fill-opacity": ["match", ["get", "kind"], "seasonal_restriction", 0.05, 0.16] } });
        map.addLayer({ id: "zones-line", type: "line", source: "zones", paint: { "line-color": ["match", ["get", "kind"], "mpa", "#2fc28f", "restricted", "#e05555", "seasonal_restriction", "#c98500", "geofence", "#b39cff", "#5f7489"], "line-width": 1.2, "line-dasharray": [2, 1.5] } });
        map.addLayer({ id: "boundaries-line", type: "line", source: "boundaries", paint: { "line-color": ["match", ["get", "kind"], "international", "#e66767", "#557089"], "line-width": ["match", ["get", "kind"], "international", 1.6, 0.8], "line-dasharray": [3, 2] } });
        map.addLayer({ id: "ports", type: "circle", source: "ports", paint: { "circle-radius": 3, "circle-color": "#03070c", "circle-stroke-color": "#93a7bb", "circle-stroke-width": 1.2 } });
        map.addLayer({ id: "cyc-fill", type: "fill", source: "cyclones", filter: ["==", ["get", "kind"], "wind_radius"], paint: { "fill-color": "#d03b3b", "fill-opacity": ["case", ["get", "active"], 0.14, 0.04] } });
        map.addLayer({ id: "cyc-track", type: "line", source: "cyclones", filter: ["==", ["get", "kind"], "track"], paint: { "line-color": "#ec835a", "line-width": 2, "line-dasharray": [2, 1] } });
        map.addLayer({ id: "cyc-center", type: "circle", source: "cyclones", filter: ["==", ["get", "kind"], "centroid"], paint: { "circle-radius": 7, "circle-color": ["case", ["get", "active"], "#d03b3b", "#5f7489"], "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
        map.addLayer({ id: "q-cyc-fill", type: "fill", source: "q-cyclones", filter: ["==", ["get", "kind"], "wind_radius"], paint: { "fill-color": "#d03b3b", "fill-opacity": 0.12 } });
        map.addLayer({ id: "q-cyc-cone", type: "line", source: "q-cyclones", filter: ["==", ["get", "kind"], "cone"], paint: { "line-color": "#ec835a", "line-width": 1, "line-dasharray": [1, 1] } });
        map.addLayer({ id: "q-cyc-track", type: "line", source: "q-cyclones", filter: ["==", ["get", "kind"], "track"], paint: { "line-color": "#ec835a", "line-width": 2.2 } });
        map.addLayer({ id: "q-zones-fill", type: "fill", source: "q-zones", paint: { "fill-color": ["case", ["get", "official"], "#3987e5", "#43d3c6"], "fill-opacity": 0.22 } });
        map.addLayer({ id: "q-zones-line", type: "line", source: "q-zones", paint: { "line-color": ["case", ["get", "official"], "#6da7ec", "#43d3c6"], "line-width": 1.6 } });
        map.addLayer({ id: "q-route-alt", type: "line", source: "q-route", filter: ["all", ["==", ["get", "kind"], "route"], ["!", ["get", "recommended"]]], paint: { "line-color": ["match", ["get", "id"], "shortest", "#93a7bb", "#6da7ec"], "line-width": 1.6, "line-dasharray": [2, 2], "line-opacity": 0.8 } });
        map.addLayer({ id: "q-route-casing", type: "line", source: "q-segments", layout: { "line-cap": "round" }, paint: { "line-color": "#03070c", "line-width": 7 } });
        map.addLayer({ id: "q-route-seg", type: "line", source: "q-segments", layout: { "line-cap": "round" }, paint: { "line-color": LEVEL_COLOR as never, "line-width": 4 } });
        map.addLayer({ id: "q-samples", type: "circle", source: "q-samples", paint: { "circle-radius": ["match", ["get", "role"], "primary", 6, 3.5], "circle-color": ["match", ["get", "role"], "primary", "#43d3c6", "#03070c"], "circle-stroke-color": "#43d3c6", "circle-stroke-width": 1.5 } });
        map.addLayer({ id: "q-stations", type: "circle", source: "q-stations", paint: { "circle-radius": 8, "circle-color": DECISION_COLOR as never, "circle-stroke-color": "#03070c", "circle-stroke-width": 2 } });
        map.addLayer({ id: "q-evidence", type: "circle", source: "q-evidence", paint: { "circle-radius": 3, "circle-color": "#b39cff", "circle-opacity": 0.8 } });
        map.addLayer({ id: "highlight", type: "circle", source: "highlight", paint: { "circle-radius": 16, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#43d3c6", "circle-stroke-width": 2.5 } });
        setReady(true);
      });
      const popup = new ml.Popup({ closeButton: false, closeOnClick: false, maxWidth: "280px" });
      const hover = (layer: string, html: (p: Record<string, unknown>) => string) => {
        map.on("mousemove", layer, (e) => {
          const f = e.features?.[0];
          if (!f) return;
          map.getCanvas().style.cursor = "pointer";
          popup.setLngLat(e.lngLat).setHTML(html(f.properties as Record<string, unknown>)).addTo(map);
        });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; popup.remove(); });
      };
      const esc = (s: unknown) => String(s ?? "").replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]!));
      hover("zones-fill", (p) => `<b>${esc(p.name)}</b><br/><span style="color:#93a7bb">${esc(p.kind)}${p.approximate ? " · approximate outline" : ""}${p.season && p.season !== "null" ? ` · season ${esc(p.season)}` : ""}</span><br/><span style="color:#5f7489">${esc(p.authority)}</span>`);
      hover("ports", (p) => `<b>${esc(p.name)}</b><br/><span style="color:#93a7bb">${esc(String(p.kind).replace("_", " "))} · ${esc(p.state)}</span>`);
      hover("boundaries-line", (p) => `<b>${esc(p.name)}</b><br/><span style="color:#93a7bb">${esc(p.line_type)}</span><br/><span style="color:#5f7489">Marine Regions (compiled; not legal delimitation)</span>`);
      hover("q-stations", (p) => `<b>${esc(p.label)}</b><br/>${esc(p.decision)} · risk ${esc(p.risk_index)}`);
      hover("q-route-seg", (p) => `<b>Segment ${esc(p.index)}</b> · ${esc(p.level)}<br/>Hs ${esc(p.wave)} m · wind ${esc(p.wind)} km/h<br/><span style="color:#93a7bb">ETA ${esc(ist(String(p.eta)))}</span>`);
      hover("q-zones-fill", (p) => `<b>${esc(p.id ?? p.name ?? "PFZ")}</b> ${p.official ? "· INCOIS PFZ" : "· ORCA-derived indicator"}${p.score ? `<br/>score ${esc(p.score)}` : ""}`);
      hover("cyc-center", (p) => `<b>${esc(p.name)}</b><br/>${p.active ? "ACTIVE" : "inactive"} · GDACS ${esc(p.alert)}<br/><span style="color:#93a7bb">${esc(p.severity)}</span>`);
      hover("field-dots", (p) => `<b>${p.v === null || p.v === undefined ? "—" : Number(p.v).toFixed(2)}</b> ${esc(p.units)}<br/><span style="color:#93a7bb">${esc(p.src)}</span>`);
      hover("q-evidence", (p) => `${esc(p.text)}`);
      map.on("click", (e: MapMouseEvent) => clickRef.current?.(e.lngLat.lat, e.lngLat.lng));
      mapRef.current = map;
    })();
    return () => { disposed = true; mapRef.current?.remove(); mapRef.current = null; };
  }, []);

  // ------------------------------------------------------------------ static data
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current!;
    get<{ layers: Record<string, GeoJSON.FeatureCollection> }>("/api/boundaries").then((b) => {
      (map.getSource("land") as GeoJSONSource).setData(b.layers.land);
      (map.getSource("eez") as GeoJSONSource).setData(b.layers.eez);
      (map.getSource("boundaries") as GeoJSONSource).setData(b.layers.maritime_boundaries);
      (map.getSource("zones") as GeoJSONSource).setData(b.layers.zones);
      (map.getSource("ports") as GeoJSONSource).setData(b.layers.ports);
    }).catch(() => undefined);
    get<{ gibs: Gibs[] }>("/api/map/layers").then((l) => setGibs(l.gibs)).catch(() => undefined);
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    get<GeoJSON.FeatureCollection>(`/api/map/cyclones?${modeQuery(mode, scenario)}`)
      .then((fc) => (mapRef.current?.getSource("cyclones") as GeoJSONSource | undefined)?.setData(fc)).catch(() => undefined);
  }, [ready, mode, scenario]);

  // ------------------------------------------------------------------ GIBS rasters (basemap + overlays)
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current!;
    for (const g of gibs) {
      const sid = `src-${g.id}`;
      const isBase = g.id === "gibs_truecolor";
      const want = isBase ? basemap === "satellite" : GIBS_OVERLAYS.includes(g.id) && layers[g.id];
      const date = g.time_dependent ? dateFor(g.latest_date, targetTime) : "default";
      const tiles = [g.tile_template.replace("{date}", date ?? "")];
      if (!map.getSource(sid)) {
        if (!want || !date) continue;
        map.addSource(sid, { type: "raster", tiles, tileSize: 256, maxzoom: g.maxzoom, attribution: "Imagery: NASA EOSDIS GIBS" });
        map.addLayer({ id: `lyr-${g.id}`, type: "raster", source: sid, paint: { "raster-opacity": isBase ? 1 : 0.55 } }, isBase ? "base-relief" : "eez-fill");
      } else {
        (map.getSource(sid) as RasterTileSource).setTiles(tiles);
      }
      map.setLayoutProperty(`lyr-${g.id}`, "visibility", want && date ? "visible" : "none");
    }
    map.setLayoutProperty("base-relief", "visibility", basemap === "relief" ? "visible" : "none");
    map.setLayoutProperty("base-dark", "visibility", basemap === "dark" ? "visible" : "none");
    map.setLayoutProperty("base-coast", "visibility", basemap === "satellite" ? "none" : "visible");
  }, [ready, gibs, basemap, layers, targetTime]);

  // ------------------------------------------------------------------ forecast fields
  const activeField = ["waves", "wind", "currents"].find((k) => layers[k]) ?? null;
  const requested = useRef(new Set<string>());
  useEffect(() => {
    if (!activeField) return;
    const key = `${activeField}:${mode}:${scenario}`;
    if (requested.current.has(key)) return;
    requested.current.add(key);
    get<Field>(`/api/map/field?layer=${activeField}&${modeQuery(mode, scenario)}`)
      .then((d) => setFields((f) => ({ ...f, [key]: d })))
      .catch(() => { requested.current.delete(key); });
  }, [activeField, mode, scenario]);

  const field = activeField ? fields[`${activeField}:${mode}:${scenario}`] ?? null : null;
  const fieldTime = useMemo(() => {
    if (!field || !field.times.length) return { idx: -1, t: null as string | null };
    let best = 0, bd = Infinity;
    field.times.forEach((t, i) => { const d = Math.abs(new Date(/Z|[+-]\d\d:\d\d$/.test(t) ? t : t + "Z").getTime() - targetTime.getTime()); if (d < bd) { bd = d; best = i; } });
    return bd <= 1.5 * 3600e3 ? { idx: best, t: field.times[best] } : { idx: -1, t: null };
  }, [field, targetTime]);

  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current!;
    const src = map.getSource("field") as GeoJSONSource;
    if (!field || !activeField || fieldTime.idx < 0) { src.setData(EMPTY); return; }
    const st = FIELD_STYLE[activeField];
    src.setData({
      type: "FeatureCollection",
      features: field.points.filter((p) => p.v[fieldTime.idx] !== null).map((p) => ({
        type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { v: p.v[fieldTime.idx], d: p.d[fieldTime.idx] ?? 0, units: field.units, src: field.source },
      })),
    });
    map.setPaintProperty("field-dots", "circle-color", ["interpolate", ["linear"], ["get", "v"], ...st.stops.flat()] as never);
  }, [ready, field, activeField, fieldTime]);

  // ------------------------------------------------------------------ query overlays
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current!;
    const f = bb?.map?.features ?? {};
    const set = (id: string, fc?: GeoJSON.FeatureCollection) => (map.getSource(id) as GeoJSONSource).setData(fc ?? EMPTY);
    set("q-samples", f.samples);
    const route = f.route;
    set("q-route", route);
    set("q-segments", route ? { type: "FeatureCollection", features: route.features.filter((x) => x.properties?.kind === "segment") } : undefined);
    set("q-zones", f.fishing_zones);
    set("q-cyclones", f.cyclones);
    set("q-stations", f.stations);
    set("q-evidence", f.evidence);
  }, [ready, bb]);

  // ------------------------------------------------------------------ visibility toggles
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current!;
    const vis = (ids: string[], on: boolean) => ids.forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none"));
    vis(["eez-fill", "eez-line"], !!layers.eez);
    vis(["boundaries-line"], !!layers.boundaries);
    vis(["zones-fill", "zones-line"], !!layers.zones);
    vis(["ports"], !!layers.ports);
    vis(["cyc-fill", "cyc-track", "cyc-center", "q-cyc-fill", "q-cyc-cone", "q-cyc-track"], !!layers.cyclones);
    vis(["field-dots", "field-arrows"], !!activeField);
    vis(["q-route-alt", "q-route-casing", "q-route-seg"], !!layers.route);
    vis(["q-zones-fill", "q-zones-line"], !!layers.fishing_zones);
    vis(["q-samples"], !!layers.samples);
    vis(["q-stations"], !!layers.stations);
    vis(["q-evidence"], !!layers.evidence);
  }, [ready, layers, activeField]);

  useEffect(() => {
    if (!ready || !focus) return;
    mapRef.current!.flyTo({ center: [focus.lon, focus.lat], zoom: focus.zoom ?? 7.5, speed: 1.4, essential: true });
  }, [ready, focus]);

  useEffect(() => {
    if (!ready) return;
    const src = mapRef.current!.getSource("highlight") as GeoJSONSource;
    src.setData(highlight?.lat !== undefined && highlight?.lon !== undefined
      ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [highlight.lon, highlight.lat] }, properties: {} }] }
      : EMPTY);
  }, [ready, highlight]);

  const gibsOn = gibs.filter((g) => GIBS_OVERLAYS.includes(g.id) && layers[g.id]);
  return (
    <div className="absolute inset-0">
      <div className="absolute inset-0"><div ref={el} style={{ width: "100%", height: "100%" }} /></div>
      {/* legend: honest provenance for every visible data layer */}
      <div className="pointer-events-none absolute bottom-7 left-3 flex max-w-[360px] flex-col gap-1.5">
        {activeField && (
          <div className="pointer-events-auto rounded-md border border-line-2 bg-panel/90 px-3 py-2 text-[11px] backdrop-blur">
            <div className="flex items-center justify-between gap-3">
              <span className="lbl">{FIELD_STYLE[activeField].label}</span>
              <span className="num text-ink-2">{fieldTime.t ? ist(/Z|[+-]\d\d:\d\d$/.test(fieldTime.t) ? fieldTime.t : fieldTime.t + "Z") : field ? "no forecast at this time" : "loading…"}</span>
            </div>
            <div className="mt-1.5 flex h-2 overflow-hidden rounded-sm">
              {FIELD_STYLE[activeField].stops.map(([, c], i) => <div key={i} className="flex-1" style={{ background: c }} />)}
            </div>
            <div className="num mt-0.5 flex justify-between text-[10px] text-ink-3">{FIELD_STYLE[activeField].stops.map(([v]) => <span key={v}>{v}</span>)}</div>
            {field && (
              <div className="mt-1 text-[10px] text-ink-3">
                {field.source}{field.provenance?.issued_at ? ` · run ${new Date(field.provenance.issued_at).toISOString().slice(11, 13)}Z` : ""} · {field.mode === "DEMO" ? "SIMULATED" : field.mode === "REPLAY" ? "REPLAY" : field.provenance?.freshness?.label ?? ""}
              </div>
            )}
          </div>
        )}
        {gibsOn.map((g) => (
          <div key={g.id} className="pointer-events-auto rounded-md border border-line-2 bg-panel/90 px-3 py-1.5 text-[10.5px] text-ink-2 backdrop-blur">
            <span className="text-ink">{g.title}</span> · NASA GIBS · <span className="num">{dateFor(g.latest_date, targetTime) ?? "n/a"}</span>
            {g.latest_date && targetTime.toISOString().slice(0, 10) > g.latest_date && <span className="text-caution"> (latest available)</span>}
            <span className="text-ink-3"> · imagery only</span>
          </div>
        ))}
      </div>
    </div>
  );
}
