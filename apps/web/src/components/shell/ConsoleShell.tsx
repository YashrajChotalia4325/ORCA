"use client";
import dynamic from "next/dynamic";
import { createContext, useCallback, useContext, useState } from "react";
import { LayerPanel, TimeSlider } from "../map/MapControls";
import AgentDock from "./AgentDock";
import NavRail from "./NavRail";
import TopBar, { ModeBanner } from "./TopBar";

const MapView = dynamic(() => import("../map/MapView"), { ssr: false });

type ClickHandler = ((lat: number, lon: number) => void) | undefined;
const MapClickCtx = createContext<(h: ClickHandler) => void>(() => undefined);
/** Pages register a map click handler (e.g. Live Ocean point inspector). */
export const useMapClick = () => useContext(MapClickCtx);

export default function ConsoleShell({ children }: { children: React.ReactNode }) {
  const [onClick, setOnClick] = useState<ClickHandler>(undefined);
  const register = useCallback((h: ClickHandler) => setOnClick(() => h), []);
  return (
    <MapClickCtx.Provider value={register}>
      <div className="flex h-screen flex-col overflow-hidden bg-abyss">
        <TopBar />
        <ModeBanner />
        <div className="flex min-h-0 flex-1">
          <NavRail />
          <div className="flex min-w-0 flex-1 flex-col">
            <main className="relative min-h-0 flex-1">
              <MapView onMapClick={onClick} />
              <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-2">
                <div className="pointer-events-auto"><TimeSlider /></div>
              </div>
              <div className="absolute right-14 top-3 z-20"><LayerPanel /></div>
              {children}
            </main>
            <AgentDock />
          </div>
        </div>
      </div>
    </MapClickCtx.Provider>
  );
}

/** Right-hand intelligence panel floating over the map. */
export function IntelPanel({ children, width = 440 }: { children: React.ReactNode; width?: number }) {
  return (
    <aside style={{ width: `min(${width}px, calc(100% - 24px))` }} className="absolute bottom-3 right-3 top-14 z-10 flex flex-col overflow-hidden rounded-lg border border-line-2 bg-panel/95 shadow-2xl backdrop-blur-md">
      {children}
    </aside>
  );
}

/** Full-stage panel covering the map (data-heavy pages). */
export function StagePanel({ children }: { children: React.ReactNode }) {
  return <div className="absolute inset-0 z-30 overflow-y-auto bg-abyss scroll-thin grid-bg">{children}</div>;
}

export function PanelHeader({ kicker, title, right }: { kicker: string; title: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div>
        <div className="lbl">{kicker}</div>
        <h1 className="mt-0.5 text-[16px] font-medium text-ink">{title}</h1>
      </div>
      {right}
    </div>
  );
}
