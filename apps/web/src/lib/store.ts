"use client";
import { create } from "zustand";
import { ask, follow } from "./api";
import type { Blackboard, DataMode, TraceEvent } from "./types";

export interface Turn {
  id: string;
  text: string;
  queryId?: string;
  traceId?: string;
  status: "running" | "done" | "error";
  events: TraceEvent[];
  bb?: Blackboard;
  error?: string;
  mode: DataMode;
  scenario?: string | null;
  startedAt: number;
}

export type Basemap = "dark" | "satellite" | "relief";

export interface MapFocus { lat: number; lon: number; zoom?: number; key: number }

interface OrcaState {
  mode: DataMode;
  scenario: string | null;
  setMode: (m: DataMode, scenario?: string | null) => void;
  role: string | null;
  language: string | null;
  vessel: string | null;
  setPrefs: (p: Partial<Pick<OrcaState, "role" | "language" | "vessel">>) => void;

  conversationId: string | null;
  turns: Turn[];
  activeTurnId: string | null;
  runQuery: (text: string, extra?: { location?: { lat: number; lon: number } | null; speedKn?: number | null; newConversation?: boolean }) => Promise<Turn>;
  attachTurn: (queryId: string, traceId: string, text: string) => Promise<Turn>;
  clearConversation: () => void;

  layers: Record<string, boolean>;
  toggleLayer: (id: string, on?: boolean) => void;
  basemap: Basemap;
  setBasemap: (b: Basemap) => void;
  timeOffsetH: number;
  setTimeOffset: (h: number) => void;
  focus: MapFocus | null;
  flyTo: (lat: number, lon: number, zoom?: number) => void;
  highlight: { claimId?: string; lat?: number; lon?: number } | null;
  setHighlight: (h: OrcaState["highlight"]) => void;
  dockOpen: boolean;
  setDockOpen: (o: boolean) => void;
}

let turnSeq = 0;

export const useOrca = create<OrcaState>((set, getState) => ({
  mode: "LIVE",
  scenario: null,
  setMode: (m, scenario) => set({ mode: m, scenario: m === "DEMO" ? scenario ?? getState().scenario ?? "kochi_fishing" : null, conversationId: null }),
  role: null,
  language: null,
  vessel: null,
  setPrefs: (p) => set(p),

  conversationId: null,
  turns: [],
  activeTurnId: null,
  clearConversation: () => set({ conversationId: null, turns: [], activeTurnId: null }),

  runQuery: async (text, extra) => {
    const s = getState();
    const id = `t${++turnSeq}`;
    const turn: Turn = { id, text, status: "running", events: [], mode: s.mode, scenario: s.scenario, startedAt: Date.now() };
    set({ turns: [...s.turns, turn], activeTurnId: id, dockOpen: true });
    const patch = (p: Partial<Turn>) =>
      set((st) => ({ turns: st.turns.map((t) => (t.id === id ? { ...t, ...p } : t)) }));
    try {
      const acc = await ask({
        text, mode: s.mode, scenario: s.scenario, conversationId: extra?.newConversation ? null : s.conversationId,
        role: s.role, language: s.language, vesselClass: s.vessel, location: extra?.location ?? null, speedKn: extra?.speedKn ?? null,
      });
      set({ conversationId: acc.conversation_id });
      patch({ queryId: acc.query_id, traceId: acc.trace_id });
      const bb = await follow(acc.query_id, (ev) =>
        set((st) => ({ turns: st.turns.map((t) => (t.id === id ? { ...t, events: [...t.events, ev] } : t)) })));
      patch({ bb, status: "done" });
      if (bb.map?.center) getState().flyTo(bb.map.center.lat, bb.map.center.lon, bb.map.zoom ?? undefined);
      if (bb.map?.layers) set((st) => ({ layers: { ...st.layers, ...Object.fromEntries(bb.map.layers.map((l) => [l, true])) } }));
    } catch (e) {
      patch({ status: "error", error: e instanceof Error ? e.message : String(e) });
    }
    return getState().turns.find((t) => t.id === id)!;
  },

  attachTurn: async (queryId, traceId, text) => {
    const s = getState();
    const id = `t${++turnSeq}`;
    set({ turns: [...s.turns, { id, text, queryId, traceId, status: "running", events: [], mode: s.mode, scenario: s.scenario, startedAt: Date.now() }], activeTurnId: id, dockOpen: true });
    try {
      const bb = await follow(queryId, (ev) =>
        set((st) => ({ turns: st.turns.map((t) => (t.id === id ? { ...t, events: [...t.events, ev] } : t)) })));
      set((st) => ({ turns: st.turns.map((t) => (t.id === id ? { ...t, bb, status: "done" } : t)), conversationId: bb.conversation_id }));
      if (bb.map?.center) getState().flyTo(bb.map.center.lat, bb.map.center.lon, bb.map.zoom ?? undefined);
      if (bb.map?.layers) set((st) => ({ layers: { ...st.layers, ...Object.fromEntries(bb.map.layers.map((l) => [l, true])) } }));
    } catch (e) {
      set((st) => ({ turns: st.turns.map((t) => (t.id === id ? { ...t, status: "error", error: String(e) } : t)) }));
    }
    return getState().turns.find((t) => t.id === id)!;
  },

  layers: { zones: true, boundaries: true, eez: true, ports: true, cyclones: true, samples: true, route: true, fishing_zones: true, evidence: true, stations: true, waves: false, wind: false, currents: false },
  toggleLayer: (id, on) => set((st) => ({ layers: { ...st.layers, [id]: on ?? !st.layers[id] } })),
  basemap: "dark",
  setBasemap: (b) => set({ basemap: b }),
  timeOffsetH: 0,
  setTimeOffset: (h) => set({ timeOffsetH: h }),
  focus: null,
  flyTo: (lat, lon, zoom) => set({ focus: { lat, lon, zoom, key: Date.now() } }),
  highlight: null,
  setHighlight: (h) => set({ highlight: h }),
  dockOpen: true,
  setDockOpen: (o) => set({ dockOpen: o }),
}));

export function useActiveTurn(): Turn | undefined {
  return useOrca((s) => s.turns.find((t) => t.id === s.activeTurnId));
}
