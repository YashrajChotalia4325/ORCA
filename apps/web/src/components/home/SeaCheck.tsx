"use client";
// The simple "is it safe / where to fish" check for fishermen and the community groups that relay
// advice to them. It asks the same multi-agent pipeline as the console (role = fisherman, forced
// output language) and shows only the verified decision, reasons and advice in plain words.
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode, type SVGProps } from "react";
import * as I from "@/components/shell/icons";
import harboursData from "@/data/harbours.json";
import { API, ask, follow } from "@/lib/api";
import { DECISION } from "@/lib/format";
import { useStoredState } from "@/lib/hooks";
import { LANGS, UI, type Lang, type UIKey } from "@/lib/i18n";
import type { Blackboard, Decision } from "@/lib/types";

type Harbour = { id: string; name: string; state: string | null; names: Partial<Record<string, string>> };
const HARBOURS = (harboursData.harbours as Harbour[]).slice().sort((a, b) => (a.state ?? "").localeCompare(b.state ?? "") || a.name.localeCompare(b.name));
const BY_STATE = HARBOURS.reduce<Record<string, Harbour[]>>((m, h) => { (m[h.state ?? "Other"] ??= []).push(h); return m; }, {});

const WHEN = [
  { id: "today", key: "today", Icon: I.IcSun, en: "today" },
  { id: "morning", key: "tmrMorning", Icon: I.IcSunrise, en: "tomorrow morning" },
  { id: "evening", key: "tmrEvening", Icon: I.IcSunset, en: "tomorrow evening" },
] as const;
const BOATS = [
  { id: "small_craft", key: "small", Icon: I.IcBoatSmall },
  { id: "mechanized", key: "mech", Icon: I.IcTrawler },
  { id: "large_vessel", key: "large", Icon: I.IcShip },
] as const;

// decision colours and glyphs are the console's (lib/format DECISION); only the words are localised
const WORD: Record<Decision, UIKey> = { GO: "GO", CAUTION: "CAUTION", DONT_GO: "DONT_GO", INSUFFICIENT_DATA: "NA", NOT_APPLICABLE: "NA" };
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

type Kind = "safety" | "zones";
type Result = { bb: Blackboard; kind: Kind; practice: boolean; harbour: Harbour; when: string };
type ZoneRow = { id: string; score: number; distance_km: number; bearing: number; depth?: number | null };

function Chip({ on, onClick, children, big = false }: { on: boolean; onClick: () => void; children: ReactNode; big?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on}
      className={`min-w-0 break-words rounded-md border px-3 text-left leading-snug transition-colors ${big ? "min-h-[60px] py-2 text-[16px]" : "min-h-[44px] py-1.5 text-[15px]"} ${on ? "border-accent bg-panel-3 font-medium text-accent" : "border-line-2 bg-panel-2 text-ink-2 hover:border-accent/50 hover:text-ink"}`}>
      {children}
    </button>
  );
}

function Legend({ icon: Icon, children }: { icon: (p: SVGProps<SVGSVGElement>) => ReactNode; children: ReactNode }) {
  return <legend className="mb-2 flex items-center gap-2 font-cond text-[13px] uppercase tracking-[0.12em] text-ink-3"><Icon width={16} height={16} />{children}</legend>;
}

export default function SeaCheck({ variant = "fisherman" }: { variant?: "fisherman" | "community" }) {
  const [lang, setLang] = useStoredState<Lang>("orca.lang", "en");
  const [harbourId, setHarbourId] = useStoredState<string>("orca.harbour", "kochi");
  const [when, setWhen] = useStoredState<(typeof WHEN)[number]["id"]>("orca.when", "morning");
  const [boat, setBoat] = useStoredState<(typeof BOATS)[number]["id"]>("orca.boat", "small_craft");
  const [practice, setPractice] = useState(false);
  const [running, setRunning] = useState<{ kind: Kind; started: number; done: number; total: number } | null>(null);
  const [now, setNow] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState(false);
  const [copied, setCopied] = useState(false);
  const t = UI[lang] ?? UI.en;
  const harbour = HARBOURS.find((h) => h.id === harbourId) ?? HARBOURS[0];
  const vessel = BOATS.find((b) => b.id === boat)?.id ?? "small_craft";
  const local = (h: Harbour) => (lang !== "en" && h.names[lang]) || h.name;

  // wake the (free-tier) API while the user is still choosing
  useEffect(() => { fetch(`${API}/`).catch(() => undefined); }, []);
  useEffect(() => {
    if (!running) return;
    const i = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(i);
  }, [running]);

  const run = async (kind: Kind, asPractice = practice) => {
    const w = WHEN.find((x) => x.id === when) ?? WHEN[1];
    const text = kind === "safety" ? `Is it safe to fish off ${harbour.name} ${w.en}?` : `Show potential fishing zones near ${harbour.name}`;
    setRunning({ kind, started: Date.now(), done: 0, total: 0 });
    setNow(Date.now()); setResult(null); setError(false); setCopied(false);
    try {
      const acc = await ask({
        text, mode: asPractice ? "DEMO" : "LIVE", scenario: asPractice ? (kind === "zones" ? "pfz_mangaluru" : "kochi_fishing") : null,
        role: "fisherman", language: UI[lang] ? lang : "en", vesselClass: vessel,
      });
      const bb = await follow(acc.query_id, (e) => setRunning((r) => r && {
        ...r,
        total: e.type === "plan" && Array.isArray(e.data?.tasks) ? r.total + (e.data.tasks as unknown[]).length : r.total,
        done: e.type === "agent_end" && e.agent !== "planner" ? r.done + 1 : r.done,
      }));
      setResult({ bb, kind, practice: asPractice, harbour, when: t[w.key] });
    } catch {
      setError(true);
    } finally {
      setRunning(null);
    }
  };

  const decision: Decision = result?.bb.final_assessment?.decision ?? "INSUFFICIENT_DATA";
  const look = { ...DECISION[decision], key: WORD[decision] };
  const sec = (id: string) => result?.bb.response?.sections.find((s) => s.id === id);
  const why = sec("why")?.items ?? [];
  const advice = sec("recommendations")?.items ?? [];
  const zones = (sec("zones")?.table ?? []) as unknown as ZoneRow[];
  const waited = running ? Math.max(0, (now - running.started) / 1000) : 0;

  const message = useMemo(() => {
    if (!result) return "";
    const lines = [`${look.glyph} ${t[look.key]} — ${local(result.harbour)}${result.kind === "safety" ? `, ${result.when}` : ""}`];
    if (result.kind === "safety" && result.bb.response?.headline) lines.push(result.bb.response.headline);
    if (result.kind === "zones") lines.push("", `${t.zones}:`, ...zones.slice(0, 5).map((z, i) => `• ${t.area} ${i + 1}: ${Math.round(z.distance_km)} km ${COMPASS[Math.round(z.bearing / 45) % 8]} ${t.fromHarbour}`), t.zonesNote);
    if (why.length) lines.push("", `${t.why}:`, ...why.map((x) => `• ${x}`));
    if (advice.length) lines.push("", `${t.advice}:`, ...advice.map((x) => `• ${x}`));
    if (result.practice) lines.push("", t.practiceOn);
    lines.push("", t.official, `ORCA ${t.ref}: ${result.bb.trace_id}`);
    return lines.join("\n");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- derived from result + language only
  }, [result, lang]);

  const copy = async () => {
    try { await navigator.clipboard.writeText(message); setCopied(true); } catch { setCopied(false); }
  };
  const share = async () => {
    if (navigator.share) { try { await navigator.share({ text: message }); return; } catch { /* cancelled */ } }
    window.open(`https://wa.me/?text=${encodeURIComponent(message)}`, "_blank", "noopener");
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      {/* ---------------- choices */}
      <div className="rounded-lg border border-line-2 bg-panel p-5 sm:p-6">
        <fieldset>
          <Legend icon={I.IcLanguage}>{t.chooseLang}</Legend>
          <div className="flex flex-wrap gap-2">
            {LANGS.map((l) => <Chip key={l.id} on={lang === l.id} onClick={() => setLang(l.id)}><span lang={l.id} className="block whitespace-nowrap px-1 text-center">{l.name}</span></Chip>)}
          </div>
        </fieldset>

        <fieldset className="mt-6">
          <Legend icon={I.IcAnchor}>{t.harbour}</Legend>
          <select value={harbour.id} onChange={(e) => setHarbourId(e.target.value)} aria-label={t.harbour}
            className="min-h-[54px] w-full rounded-md border border-line-2 bg-panel-2 px-3 text-[18px] text-ink focus:border-accent focus:outline-none">
            {Object.entries(BY_STATE).map(([state, hs]) => (
              <optgroup key={state} label={state}>
                {hs.map((h) => <option key={h.id} value={h.id}>{local(h)}{lang !== "en" && h.names[lang] ? ` (${h.name})` : ""}</option>)}
              </optgroup>
            ))}
          </select>
        </fieldset>

        <fieldset className="mt-6">
          <Legend icon={I.IcClock}>{t.when}</Legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {WHEN.map((w) => <Chip key={w.id} big on={when === w.id} onClick={() => setWhen(w.id)}><span className="flex items-center gap-2.5"><w.Icon width={22} height={22} className="shrink-0" />{t[w.key]}</span></Chip>)}
          </div>
        </fieldset>

        <fieldset className="mt-6">
          <Legend icon={I.IcBoatSmall}>{t.boat}</Legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {BOATS.map((b) => <Chip key={b.id} big on={boat === b.id} onClick={() => setBoat(b.id)}><span className="flex items-center gap-2.5"><b.Icon width={22} height={22} className="shrink-0" />{t[b.key]}</span></Chip>)}
          </div>
        </fieldset>

        <div className="mt-7 grid gap-3">
          <button type="button" disabled={!!running} onClick={() => run("safety")}
            className="flex min-h-[60px] items-center justify-center gap-2.5 rounded-md bg-accent px-4 py-2 text-[19px] font-medium leading-snug text-abyss hover:brightness-110 disabled:opacity-50"><I.IcOcean width={22} height={22} />{t.checkSafe}</button>
          <button type="button" disabled={!!running} onClick={() => run("zones")}
            className="flex min-h-[60px] items-center justify-center gap-2.5 rounded-md border border-accent/70 bg-panel-2 px-4 py-2 text-[19px] font-medium leading-snug text-accent hover:bg-panel-3 disabled:opacity-50"><I.IcFish width={22} height={22} />{t.findFish}</button>
        </div>
        <label className="mt-4 flex cursor-pointer items-center gap-2.5 text-[14.5px] text-ink-2">
          <input type="checkbox" checked={practice} onChange={(e) => setPractice(e.target.checked)} className="h-5 w-5 accent-[var(--demo)]" />
          {t.practice}
        </label>
      </div>

      {/* ---------------- answer */}
      <div aria-live="polite" className="min-h-[200px]">
        {!running && !result && !error && (
          <div className="grid-bg flex h-full min-h-[240px] flex-col items-center justify-center rounded-lg border border-dashed border-line-2 bg-panel/60 p-8 text-center">
            <I.IcOcean width={44} height={44} className="text-accent" />
            <p className="mt-3 text-[22px] font-light text-ink">{t.appTitle}</p>
            <p className="mt-1 text-[15px] text-ink-3">{local(harbour)} · {t[WHEN.find((w) => w.id === when)?.key ?? "tmrMorning"]} · {t[BOATS.find((b) => b.id === boat)?.key ?? "small"]}</p>
          </div>
        )}

        {running && (
          <div className="rounded-lg border border-line-2 bg-panel p-8 text-center">
            <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-line-2 border-t-accent" aria-hidden />
            <p className="mt-4 text-[19px] text-ink">{t.checking}</p>
            {running.total > 0 && (
              <div className="mx-auto mt-4 h-2 max-w-[320px] overflow-hidden rounded-full bg-panel-3">
                <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.min(100, (running.done / running.total) * 100)}%` }} />
              </div>
            )}
            {waited > 8 && running.total === 0 && <p className="mt-3 text-[15px] text-ink-3">{t.waking}</p>}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-danger/60 bg-panel p-6 text-center">
            <p className="text-[18px] text-danger">{t.error}</p>
            <button type="button" onClick={() => run(result?.kind ?? "safety")} className="mt-3 min-h-[48px] rounded-md border border-danger/70 px-5 text-[16px] text-ink hover:bg-panel-3">{t.tryAgain}</button>
          </div>
        )}

        {result && (
          <div className="overflow-hidden rounded-lg border border-line-2 bg-panel">
            {result.practice && <div className="demo-tape px-5 py-2 text-center font-cond text-[13.5px] uppercase tracking-[0.1em] text-demo">{t.practiceOn}</div>}
            <div className="border-l-4 px-5 py-6 sm:px-6" style={{ borderColor: look.color, background: `color-mix(in oklab, ${look.color} 14%, var(--panel))` }}>
              <div className="flex items-center gap-4">
                <span className="text-[40px] leading-none" style={{ color: look.color }} aria-hidden>{look.glyph}</span>
                <div>
                  <div className="text-[30px] font-semibold leading-tight sm:text-[34px]" style={{ color: look.color }}>{t[look.key]}</div>
                  {result.kind === "safety" && result.bb.response?.headline && <p className="mt-1 text-[17px] leading-snug text-ink">{result.bb.response.headline}</p>}
                </div>
              </div>
              <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] text-ink-2">
                <span className="flex items-center gap-1.5"><I.IcAnchor width={15} height={15} />{local(result.harbour)}</span>
                {result.kind === "safety" && <span className="flex items-center gap-1.5"><I.IcClock width={15} height={15} />{result.when}</span>}
                {result.bb.final_assessment && decision !== "INSUFFICIENT_DATA" && <span>{t.confidence} <span className="num">{Math.round(result.bb.final_assessment.confidence * 100)}%</span></span>}
              </p>
            </div>

            <div className="space-y-5 px-5 py-5 sm:px-6">
              {decision === "INSUFFICIENT_DATA" && !result.practice && (
                <div className="rounded-md border border-line-2 bg-panel-2 p-4 text-[16px] text-ink-2">
                  {t.noDataTip}
                  <button type="button" onClick={() => { setPractice(true); run(result.kind, true); }} className="mt-3 block min-h-[44px] rounded-md border border-demo/70 px-4 text-[15px] text-demo hover:bg-panel-3">{t.practice}</button>
                </div>
              )}

              {result.kind === "zones" && (
                <div>
                  <h3 className="flex items-center gap-2 text-[18px] font-medium text-ink"><I.IcFish width={20} height={20} className="text-accent" />{t.zones}</h3>
                  {zones.length === 0 ? <p className="mt-1 text-[16px] text-ink-2">{t.noZones}</p> : (
                    <ul className="mt-2 space-y-2">
                      {zones.slice(0, 5).map((z, i) => (
                        <li key={z.id} className="flex items-center gap-4 rounded-md border border-line-2 bg-panel-2 p-3">
                          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full border border-line-2 bg-panel-3 text-accent" aria-hidden>
                            <I.IcArrowUp width={24} height={24} style={{ transform: `rotate(${z.bearing}deg)` }} />
                          </span>
                          <div className="text-[16px] text-ink">
                            <div className="font-medium">{t.area} {i + 1} · <span style={{ color: z.score >= 0.7 ? "var(--go)" : "var(--caution)" }}>{z.score >= 0.7 ? t.good : t.possible}</span></div>
                            <div className="text-[14.5px] text-ink-2"><span className="num">{Math.round(z.distance_km)} km {COMPASS[Math.round(z.bearing / 45) % 8]}</span> {t.fromHarbour}{z.depth ? <> · {t.depth} <span className="num">{Math.round(Math.abs(z.depth))} m</span></> : null}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-2 text-[14px] text-ink-3">{t.zonesNote}</p>
                </div>
              )}

              {why.length > 0 && (
                <div>
                  <h3 className="font-cond text-[15px] font-medium uppercase tracking-[0.1em] text-ink-2">{t.why}</h3>
                  <ul className="mt-1.5 space-y-1.5 text-[16px] leading-snug text-ink">{why.map((x, i) => <li key={i} className="flex gap-2"><span className="text-ink-3" aria-hidden>•</span><span>{x}</span></li>)}</ul>
                </div>
              )}
              {advice.length > 0 && (
                <div>
                  <h3 className="font-cond text-[15px] font-medium uppercase tracking-[0.1em] text-ink-2">{t.advice}</h3>
                  <ul className="mt-1.5 space-y-1.5 text-[16px] leading-snug text-ink">{advice.map((x, i) => <li key={i} className="flex gap-2"><span className="text-accent" aria-hidden>✓</span><span>{x}</span></li>)}</ul>
                </div>
              )}

              <p className="flex items-start gap-2 rounded-md border border-caution/40 bg-panel-2 px-4 py-3 text-[15px] text-caution"><I.IcAlert width={18} height={18} className="mt-0.5 shrink-0" />{t.official}</p>

              {variant === "community" && (
                <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
                  <button type="button" onClick={share} className="flex min-h-[44px] items-center gap-2 rounded-md bg-accent px-4 text-[15px] font-medium text-abyss hover:brightness-110"><I.IcShare width={17} height={17} />{t.share}</button>
                  <button type="button" onClick={copy} className="flex min-h-[44px] items-center gap-2 rounded-md border border-line-2 px-4 text-[15px] text-ink-2 hover:border-accent/60 hover:text-ink"><I.IcCopy width={17} height={17} />{copied ? `✓ ${t.copied}` : t.copy}</button>
                  <span className="ml-auto text-[13px] text-ink-3">{t.ref}: <Link href={`/evidence?trace=${result.bb.trace_id}`} className="num text-accent underline-offset-2 hover:underline">{result.bb.trace_id}</Link></span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
