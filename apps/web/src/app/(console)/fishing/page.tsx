"use client";
import { useEffect, useState } from "react";
import TurnView from "@/components/TurnView";
import { Section } from "@/components/result/primitives";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { useApi } from "@/lib/hooks";
import { useOrca } from "@/lib/store";

type Ports = { layers: { ports: GeoJSON.FeatureCollection } };

export default function Fishing() {
  const { runQuery, turns, toggleLayer } = useOrca();
  const ports = useApi<Ports>("/api/boundaries");
  const [pid, setPid] = useState("Mangaluru");
  const [myTurn, setMyTurn] = useState<string | null>(null);
  useEffect(() => { toggleLayer("gibs_chlorophyll", true); toggleLayer("fishing_zones", true); }, [toggleLayer]);
  const names = (ports.data?.layers.ports.features ?? []).map((f) => String(f.properties?.name)).sort();
  const turn = turns.find((t) => t.id === myTurn);
  const go = async (q: string) => { const t = runQuery(q); setMyTurn(useOrca.getState().activeTurnId); await t; };
  return (
    <IntelPanel width={460}>
      <PanelHeader kicker="Fishing intelligence" title="Productive-water indicator & PFZ" />
      <div className="scroll-thin flex-1 overflow-y-auto">
        <Section title="Harbour">
          <div className="flex gap-2">
            <select value={pid} onChange={(e) => setPid(e.target.value)} className="flex-1 rounded border border-line-2 bg-panel-2 px-2 py-1.5 text-[12.5px] text-ink">
              {names.map((n) => <option key={n}>{n}</option>)}
            </select>
            <button onClick={() => go(`Show potential fishing zones near ${pid}`)} className="rounded bg-accent px-3 text-[12px] font-medium text-abyss">Find zones</button>
          </div>
          <button onClick={() => go(`Is it safe to fish off ${pid} tomorrow morning?`)} className="mt-1.5 text-[11.5px] text-accent">…or check tomorrow-morning safety off {pid} →</button>
          <p className="mt-2 text-[11px] leading-snug text-ink-3">
            ORCA&apos;s indicator combines satellite SST fronts (|∇SST|) with chlorophyll-a — the same physical rationale as INCOIS PFZ advisories — but it is an
            ORCA-derived, probabilistic habitat indicator. It never claims fish are present. Official INCOIS PFZ advisories are shown separately when accessible.
          </p>
        </Section>
        <TurnView turn={turn} empty={<p className="px-4 py-3 text-[12px] text-ink-3">Choose a harbour. The chlorophyll layer (PACE, NASA GIBS) is switched on for visual context.</p>} />
      </div>
    </IntelPanel>
  );
}
