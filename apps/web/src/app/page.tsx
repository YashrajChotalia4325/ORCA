"use client";
// Home page: one tab per stakeholder group. Each tab only routes people to the existing ORCA
// capabilities they need — fishermen and community groups get the plain-language check,
// authorities the operational console pages, educators the guided material, and scientists
// the full console (the original landing content lives in the Science tab).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode } from "react";
import SeaCheck from "@/components/home/SeaCheck";
import HeroCanvas from "@/components/landing/HeroCanvas";
import { OrcaMark } from "@/components/shell/icons";
import { API } from "@/lib/api";
import { useApi, useHash } from "@/lib/hooks";
import { useOrca } from "@/lib/store";
import type { SourceRow } from "@/lib/types";

const TABS = [
  { id: "fishermen", icon: "🎣", label: "Fishermen", sub: "Is it safe to go?" },
  { id: "authorities", icon: "🛡", label: "Authorities", sub: "Coast Guard · fisheries · disaster · ports" },
  { id: "community", icon: "🤝", label: "Community groups", sub: "Unions · co-ops · NGOs · panchayats" },
  { id: "education", icon: "🎓", label: "Education", sub: "Learn how ORCA decides" },
  { id: "science", icon: "🔬", label: "Science & research", sub: "Full data console" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const FLOW = [
  { k: "ASK", d: "Any of 8 Indian languages or English. Intent, place, vessel and an exact IST time window are resolved deterministically." },
  { k: "PLAN", d: "The planner decomposes the question and selects agents — then re-plans when data is missing or sources conflict." },
  { k: "OBSERVE", d: "Parallel retrieval from wave, weather, satellite, advisory and geospatial sources, each with provenance and freshness." },
  { k: "CORRELATE", d: "Space-time alignment over the whole trip or route: every sample point, every hour, every model." },
  { k: "VERIFY", d: "Claims are checked source by source. Disagreements are surfaced, never averaged. Confidence is a documented formula." },
  { k: "DECIDE", d: "A deterministic risk model issues GO / CAUTION / DON'T GO — or refuses when critical data is missing." },
];

export default function Home() {
  const hash = useHash();
  const tab: TabId = (TABS.find((t) => t.id === hash)?.id ?? "fishermen");
  const pick = (id: TabId) => { window.history.pushState(null, "", `#${id}`); window.dispatchEvent(new HashChangeEvent("hashchange")); };
  return (
    <div className="min-h-screen bg-[#f3f7fb] text-slate-900" style={{ colorScheme: "light" }}>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <OrcaMark size={30} />
            <div>
              <div className="text-[20px] font-bold tracking-[0.2em] text-slate-900">ORCA</div>
              <div className="text-[12.5px] text-slate-500">Sea safety and ocean intelligence for India&apos;s coast</div>
            </div>
          </div>
          <span className="ml-auto rounded-full bg-amber-50 px-3 py-1 text-[12.5px] text-amber-800">Prototype · official IMD / INCOIS warnings always come first</span>
        </div>
        <nav className="mx-auto max-w-[1240px] overflow-x-auto px-2 [scrollbar-width:none] sm:px-4" aria-label="Who are you?">
          <div role="tablist" className="flex min-w-max gap-1">
            {TABS.map((t) => (
              <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} onClick={() => pick(t.id)}
                className={`flex items-center gap-2.5 border-b-[3px] px-4 py-3 text-left transition-colors ${tab === t.id ? "border-sky-700 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                <span className="text-[22px]" aria-hidden>{t.icon}</span>
                <span>
                  <span className="block text-[15.5px] font-semibold">{t.label}</span>
                  <span className="block text-[12px] text-slate-500">{t.sub}</span>
                </span>
              </button>
            ))}
          </div>
        </nav>
      </header>

      <main id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="mx-auto max-w-[1240px] px-4 py-6 sm:px-6 sm:py-8">
        {tab === "fishermen" && <Fishermen />}
        {tab === "authorities" && <Authorities />}
        {tab === "community" && <Community />}
        {tab === "education" && <Education />}
        {tab === "science" && <Science />}
      </main>

      <footer className="mx-auto max-w-[1240px] px-4 pb-10 text-[12.5px] leading-relaxed text-slate-500 sm:px-6">
        ORCA is a decision-support prototype built for Smart India Hackathon problem SIH26176. It is not an official authority and is not endorsed by
        ISRO, INCOIS, IMD or any agency. Official warnings always take precedence.
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------ shared */
function Intro({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-6 max-w-[820px]">
      <h1 className="text-[26px] font-bold leading-tight text-slate-900 sm:text-[30px]">{title}</h1>
      <p className="mt-2 text-[16px] leading-relaxed text-slate-600">{children}</p>
    </div>
  );
}

function ToolCard({ href, icon, title, text, who, onOpen }: { href: string; icon: string; title: string; text: string; who?: string; onOpen?: () => void }) {
  const external = href.startsWith("http") || href.endsWith(".pdf");
  const body = (
    <>
      <div className="text-[28px]" aria-hidden>{icon}</div>
      <h3 className="mt-2 text-[18px] font-semibold text-slate-900 group-hover:text-sky-800">{title} <span aria-hidden>→</span></h3>
      <p className="mt-1 text-[14.5px] leading-snug text-slate-600">{text}</p>
      {who && <p className="mt-3 text-[12.5px] text-slate-500">For: {who}</p>}
    </>
  );
  const cls = "group block rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-sky-300 hover:shadow";
  return external
    ? <a href={href} target="_blank" rel="noopener" className={cls}>{body}</a>
    : <Link href={href} onClick={onOpen} className={cls}>{body}</Link>;
}

/* ------------------------------------------------------------------ tabs */
function Fishermen() {
  return <SeaCheck variant="fisherman" />;
}

function Authorities() {
  const setPrefs = useOrca((s) => s.setPrefs);
  const asAuthority = () => setPrefs({ role: "authority" });
  return (
    <>
      <Intro title="For coastal authorities">
        Situation overview, verified alerts and route checks for the Coast Guard, State Fisheries Departments, disaster-management authorities,
        port authorities and the Navy. Every answer carries its evidence, sources and a reference number.
      </Intro>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <ToolCard href="/command" onOpen={asAuthority} icon="🗺" title="Coastal situation overview" who="Coast Guard, SDMA / DDMA, Fisheries Departments"
          text="Map of the whole coast with sea state, cyclones, protected areas and maritime boundaries." />
        <ToolCard href="/safety" onOpen={asAuthority} icon="🚨" title="Alerts & vessel watches" who="Coast Guard, disaster management, harbour masters"
          text="Verified alerts as they happen, an on-demand monitoring scan, and geofence watches for a vessel or a point." />
        <ToolCard href="/ask?q=Show%20cyclone%20risk%20across%20the%20Odisha%20coast%20for%20the%20next%2024%20hours" onOpen={asAuthority} icon="📋" title="Regional risk report"
          who="District collectors, SDMA / DDMA, Fisheries Departments"
          text="Ask for a stretch of coast — e.g. “cyclone risk across the Odisha coast for the next 24 hours” — and get a per-station report." />
        <ToolCard href="/route" onOpen={asAuthority} icon="🧭" title="Check a route" who="Port authorities, shipping, Navy"
          text="Lower-risk route between two ports at departure time, with the exact point where it would enter a protected area." />
        <ToolCard href="/ocean" onOpen={asAuthority} icon="🌊" title="Live sea conditions" who="Harbour masters, operations rooms"
          text="Wave, wind and current forecasts on the map, plus satellite imagery with real dates." />
        <ToolCard href="/evidence" onOpen={asAuthority} icon="🗂" title="Look up a past answer" who="Inquiries, audits, insurance verification"
          text="Open any answer by its reference number (ORCA-…) to see every source, conflict and timestamp behind it." />
      </div>
    </>
  );
}

function Community() {
  return (
    <>
      <Intro title="For fishermen's unions, co-operatives, NGOs and panchayats">
        Prepare a sea-safety message for your village in its own language and share it on WhatsApp, or copy it for a notice board or loudspeaker announcement.
        Each message carries a reference number, so it can be checked later — useful for insurance claims and records.
      </Intro>
      <SeaCheck variant="community" />
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <ToolCard href="/safety" icon="🚨" title="Current warnings" who="Union and co-operative offices"
          text="All alerts ORCA has raised, with whether each one is verified by an official advisory or by two independent sources." />
        <ToolCard href="/evidence" icon="🗂" title="Check a reference number" who="Insurers, boat-owner associations"
          text="Open a past message by its reference number to see exactly what the sea forecast said at the time." />
      </div>
    </>
  );
}

const SCENARIOS: { id: string; icon: string; title: string; lesson: string; q: string }[] = [
  { id: "kochi_fishing", icon: "🎣", title: "A normal fishing morning", lesson: "How a CAUTION decision is reached, and why it tells you to be back before a certain time.", q: "Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?" },
  { id: "approaching_cyclone", icon: "🌀", title: "A cyclone is coming", lesson: "Why being inside a cyclone's wind radius means DON'T GO, and how ORCA looks further ahead.", q: "Is it safe to fish off Visakhapatnam tomorrow morning?" },
  { id: "conflicting_sources", icon: "⚖", title: "Forecasts disagree", lesson: "Why ORCA never averages forecasts, and how it asks a third model to break the tie.", q: "Is it safe to fish 25 km off Chennai tomorrow morning?" },
  { id: "total_outage", icon: "📡", title: "Data is missing", lesson: "Why a trustworthy system says “I don't know” instead of guessing.", q: "Is it safe to fish 20 km off Kochi tomorrow morning?" },
  { id: "pfz_mangaluru", icon: "🐟", title: "Where are the fish?", lesson: "How sea temperature and chlorophyll from satellites point to productive water.", q: "Show potential fishing zones near Mangaluru" },
  { id: "protected_geofence", icon: "🐢", title: "A protected area", lesson: "How a route is checked against a marine national park, minute by minute.", q: "Plan a route from Thoothukudi to Rameswaram for a fishing boat tomorrow morning" },
];

function Education() {
  const router = useRouter();
  const setMode = useOrca((s) => s.setMode);
  const tryScenario = (id: string, q: string) => { setMode("DEMO", id); router.push(`/ask?q=${encodeURIComponent(q)}`); };
  return (
    <>
      <Intro title="For fisheries schools, maritime institutes and students">
        Learn how sea-state forecasts become a safety decision, using safe sample situations. Nothing here uses real conditions — every sample is clearly labelled.
      </Intro>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <ToolCard href="/judge" icon="▶" title="Guided demonstration" who="Classrooms, first-time visitors"
          text="A step-by-step walk-through: the question, the agents working in parallel, the evidence and the decision." />
        <ToolCard href="/ORCA-Guide.pdf" icon="📘" title="Read the beginner's guide (PDF)" who="Students, instructors"
          text="41 pages from zero: ocean data, AI agents, how ORCA's 13 agents were designed and how they work together." />
        <ToolCard href="/agents" icon="🕸" title="Watch the agents work" who="Computer-science and AI courses"
          text="See the agent network light up as a question is answered, and what each agent contributed." />
      </div>

      <h2 className="mt-10 text-[20px] font-bold text-slate-900">Practice situations</h2>
      <p className="mt-1 text-[15px] text-slate-600">Each one opens ORCA with sample data and a ready-made question.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {SCENARIOS.map((s) => (
          <button key={s.id} type="button" onClick={() => tryScenario(s.id, s.q)}
            className="group rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-violet-300 hover:shadow">
            <div className="text-[26px]" aria-hidden>{s.icon}</div>
            <h3 className="mt-1 text-[17px] font-semibold text-slate-900 group-hover:text-violet-800">{s.title} <span aria-hidden>→</span></h3>
            <p className="mt-1 text-[14px] leading-snug text-slate-600">{s.lesson}</p>
            <p className="mt-2 text-[12.5px] italic text-slate-500">“{s.q}”</p>
          </button>
        ))}
      </div>

      <h2 className="mt-10 text-[20px] font-bold text-slate-900">How ORCA reaches a decision</h2>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {FLOW.map((f, i) => (
          <li key={f.k} className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="text-[13px] font-bold tracking-[0.15em] text-sky-700">{String(i + 1).padStart(2, "0")} · {f.k}</div>
            <p className="mt-1 text-[14.5px] leading-snug text-slate-700">{f.d}</p>
          </li>
        ))}
      </ol>
      <div className="mt-6"><ToolCard href="/eval" icon="✅" title="How ORCA is tested" text="The 100-question evaluation: accuracy, groundedness and consistency across languages." /></div>
    </>
  );
}

function Science() {
  const sources = useApi<{ total: number; counts: Record<string, number>; sources: SourceRow[] }>("/api/sources");
  const live = sources.data?.sources.filter((s) => s.status === "OPERATIONAL") ?? [];
  const TOOLS: [string, string, string][] = [
    ["/command", "Command centre", "map, regional risk, alerts"],
    ["/ocean", "Live ocean", "multi-model forecast fields, GIBS imagery"],
    ["/ask", "Ask ORCA", "free-form questions with the full trace"],
    ["/research", "Research", "trends, period comparison, hypotheses"],
    ["/fishing", "Fishing intelligence", "SST fronts × chlorophyll indicator"],
    ["/route", "Route", "time-dependent A* and segment risk"],
    ["/sources", "Data sources", "access status, freshness, health"],
    ["/agents", "Agent network", "LangGraph supersteps, typed outputs"],
    ["/evidence", "Evidence", "claims, conflicts, confidence maths"],
    ["/health", "System health", "caches, circuit breakers, monitor"],
    ["/eval", "Evaluation", "100-query suite and metrics"],
    ["/judge", "Judge mode", "guided demonstration"],
  ];
  return (
    <div className="relative overflow-hidden rounded-2xl bg-abyss text-ink" style={{ colorScheme: "dark" }}>
      <HeroCanvas />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_40%,transparent_0%,rgba(3,7,12,0.55)_55%,rgba(3,7,12,0.95)_100%)]" />
      <div className="relative z-10 grid grid-cols-1 gap-10 p-6 sm:p-10 lg:grid-cols-[1.2fr_1fr]">
        <section>
          <div className="lbl mb-4 text-accent">SIH26176 · Space Technology · Agentic marine intelligence</div>
          <h2 className="text-[44px] font-light leading-[1.05] tracking-[-0.02em] sm:text-[56px]">Ask the Ocean.<br /><span className="text-accent">ORCA</span> Reasons.</h2>
          <p className="mt-5 max-w-[560px] text-[16px] leading-relaxed text-ink-2">
            Thirteen specialised agents, orchestrated with LangGraph, turn live Earth observation, oceanographic and geospatial data into explainable,
            evidence-backed decisions. LIVE mode uses only real external data; REPLAY and DEMO are always labelled.
          </p>
          <div className="mt-8 flex flex-wrap gap-x-8 gap-y-3 text-[13px]">
            <Stat k="sources registered" v={sources.data?.total} />
            <Stat k="responding now" v={sources.data ? live.length : undefined} color="var(--live)" />
            <Stat k="need credentials / no public API" v={sources.data ? (sources.data.counts.CREDENTIALS_REQUIRED ?? 0) + (sources.data.counts.NO_PUBLIC_API ?? 0) : undefined} color="var(--ink-2)" />
            <Stat k="specialised agents" v={13} />
          </div>
          {sources.error && <p className="mt-3 text-[12px] text-caution">API not reachable at the moment — the console shows sources as unavailable rather than invent status.</p>}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/command" className="rounded-md bg-accent px-5 py-3 text-[14px] font-medium text-abyss hover:brightness-110">Open the console</Link>
            <a href={`${API}/docs`} target="_blank" rel="noopener" className="rounded-md border border-line-2 bg-panel/60 px-5 py-3 text-[14px] text-ink hover:border-accent/60">API documentation</a>
          </div>
        </section>
        <section className="grid grid-cols-2 content-start gap-2">
          {TOOLS.map(([href, title, d]) => (
            <Link key={href} href={href} className="rounded-lg border border-line-2 bg-panel/70 p-3 backdrop-blur-md transition-colors hover:border-accent/60">
              <div className="text-[14px] text-ink">{title}</div>
              <div className="text-[11.5px] leading-snug text-ink-3">{d}</div>
            </Link>
          ))}
        </section>
      </div>
    </div>
  );
}

function Stat({ k, v, color }: { k: string; v?: number; color?: string }) {
  return <div><div className="num text-[26px] font-light" style={{ color: color ?? "var(--ink)" }}>{v ?? "—"}</div><div className="lbl">{k}</div></div>;
}
