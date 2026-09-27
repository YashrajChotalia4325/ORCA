"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import HeroCanvas from "@/components/landing/HeroCanvas";
import { OrcaMark } from "@/components/shell/icons";
import { get } from "@/lib/api";
import type { SourceRow } from "@/lib/types";

const FLOW = [
  { k: "ASK", d: "Any of 8 Indian languages or English. Intent, place, vessel and an exact IST time window are resolved deterministically." },
  { k: "PLAN", d: "The planner decomposes the question and selects agents — then re-plans when data is missing or sources conflict." },
  { k: "OBSERVE", d: "Parallel retrieval from wave, weather, satellite, advisory and geospatial sources, each with provenance and freshness." },
  { k: "CORRELATE", d: "Space-time alignment over the whole trip or route: every sample point, every hour, every model." },
  { k: "VERIFY", d: "Claims are checked source by source. Disagreements are surfaced, never averaged. Confidence is a documented formula." },
  { k: "DECIDE", d: "A deterministic risk model issues GO / CAUTION / DON'T GO — or refuses when critical data is missing." },
];

export default function Landing() {
  const [sources, setSources] = useState<{ total: number; counts: Record<string, number>; sources: SourceRow[] } | null>(null);
  const [step, setStep] = useState(0);
  useEffect(() => {
    get<{ total: number; counts: Record<string, number>; sources: SourceRow[] }>("/api/sources").then(setSources).catch(() => setSources(null));
    const i = setInterval(() => setStep((s) => (s + 1) % FLOW.length), 2200);
    return () => clearInterval(i);
  }, []);
  const live = sources?.sources.filter((s) => s.status === "OPERATIONAL") ?? [];
  const runs = live.map((s) => s.probe?.detail).filter((d) => d?.startsWith("latest run")).slice(0, 1);

  return (
    <div className="relative min-h-screen overflow-hidden bg-abyss">
      <HeroCanvas />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_40%,transparent_0%,rgba(3,7,12,0.55)_55%,rgba(3,7,12,0.95)_100%)]" />
      <header className="relative z-10 flex items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2.5"><OrcaMark size={26} /><span className="font-cond text-[17px] font-semibold tracking-[0.25em]">ORCA</span></div>
        <nav className="flex items-center gap-6 text-[13px] text-ink-2">
          <Link href="/sources" className="hover:text-ink">Data sources</Link>
          <Link href="/agents" className="hover:text-ink">Agent network</Link>
          <Link href="/eval" className="hover:text-ink">Evaluation</Link>
          <Link href="/command" className="rounded border border-line-2 px-3 py-1.5 text-ink hover:border-accent/60">Open console</Link>
        </nav>
      </header>

      <main className="relative z-10 mx-auto grid max-w-[1240px] grid-cols-1 gap-12 px-8 pb-16 pt-[9vh] lg:grid-cols-[1.25fr_1fr]">
        <section>
          <div className="lbl mb-5 text-accent">SIH26176 · Space Technology · Agentic marine intelligence</div>
          <h1 className="text-[64px] font-light leading-[1.02] tracking-[-0.02em] text-ink">Ask the Ocean.<br /><span className="text-accent">ORCA</span> Reasons.</h1>
          <p className="mt-6 max-w-[560px] text-[17px] leading-relaxed text-ink-2">
            An agentic marine intelligence system that turns live Earth observation, oceanographic and geospatial data into explainable decisions.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link href="/judge" className="rounded-md bg-accent px-5 py-3 text-[14px] font-medium text-abyss hover:brightness-110">▶ Judge mode — guided demonstration</Link>
            <Link href="/ask" className="rounded-md border border-line-2 bg-panel/60 px-5 py-3 text-[14px] text-ink hover:border-accent/60">Ask ORCA</Link>
            <Link href="/command" className="rounded-md border border-line-2 bg-panel/60 px-5 py-3 text-[14px] text-ink hover:border-accent/60">Command center</Link>
          </div>
          <div className="mt-10 flex flex-wrap gap-x-8 gap-y-3 text-[13px]">
            <Stat k="sources registered" v={sources?.total} />
            <Stat k="responding now" v={sources ? live.length : undefined} color="var(--live)" />
            <Stat k="need credentials / no public API" v={sources ? (sources.counts.CREDENTIALS_REQUIRED ?? 0) + (sources.counts.NO_PUBLIC_API ?? 0) : undefined} color="var(--ink-2)" />
            <Stat k="specialised agents" v={13} />
          </div>
          {runs[0] && <p className="mt-3 text-[12px] text-ink-3">Most recent forecast run seen by ORCA: {runs[0]} · every answer shows exact data timestamps.</p>}
          {!sources && <p className="mt-3 text-[12px] text-caution">API not reachable at the moment — the console will show sources as unavailable rather than invent status.</p>}
        </section>

        <section className="self-center rounded-xl border border-line-2 bg-panel/70 p-6 backdrop-blur-md">
          <div className="lbl mb-4">How ORCA reaches a decision</div>
          <ol className="flex flex-col gap-1">
            {FLOW.map((f, i) => (
              <li key={f.k} onMouseEnter={() => setStep(i)} className={`grid grid-cols-[124px_1fr] items-start gap-3 rounded-md px-3 py-2.5 transition-colors ${i === step ? "bg-panel-3" : ""}`}>
                <span className={`font-cond text-[14px] font-semibold tracking-[0.18em] ${i === step ? "text-accent" : i < step ? "text-ink-2" : "text-ink-3"}`}>
                  <span className="num mr-2 text-[11px] text-ink-3">{String(i + 1).padStart(2, "0")}</span>{f.k}
                </span>
                <span className={`text-[13px] leading-snug ${i === step ? "text-ink" : "text-ink-3"}`}>{f.d}</span>
              </li>
            ))}
          </ol>
          <div className="mt-4 border-t border-line pt-3 text-[11.5px] leading-relaxed text-ink-3">
            LIVE mode uses only real external data; REPLAY and DEMO are always labelled. ORCA is a decision-support prototype — not an official authority,
            and not endorsed by ISRO, INCOIS, IMD or any agency. Official warnings always take precedence.
          </div>
        </section>
      </main>
    </div>
  );
}

function Stat({ k, v, color }: { k: string; v?: number; color?: string }) {
  return <div><div className="num text-[26px] font-light" style={{ color: color ?? "var(--ink)" }}>{v ?? "—"}</div><div className="lbl">{k}</div></div>;
}
