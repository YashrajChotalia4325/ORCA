"use client";
// The simple "is it safe / where to fish" check for fishermen and the community groups that relay
// advice to them. It asks the same multi-agent pipeline as the console (role = fisherman, forced
// output language) and shows only the verified decision, reasons and advice in plain words.
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import harboursData from "@/data/harbours.json";
import { API, ask, follow } from "@/lib/api";
import { useStoredState } from "@/lib/hooks";
import { LANGS, UI, type Lang, type UIKey } from "@/lib/i18n";
import type { Blackboard, Decision } from "@/lib/types";

type Harbour = { id: string; name: string; state: string | null; names: Partial<Record<string, string>> };
const HARBOURS = (harboursData.harbours as Harbour[]).slice().sort((a, b) => (a.state ?? "").localeCompare(b.state ?? "") || a.name.localeCompare(b.name));
const BY_STATE = HARBOURS.reduce<Record<string, Harbour[]>>((m, h) => { (m[h.state ?? "Other"] ??= []).push(h); return m; }, {});

const WHEN = [
  { id: "today", key: "today", icon: "☀️", en: "today" },
  { id: "morning", key: "tmrMorning", icon: "🌅", en: "tomorrow morning" },
  { id: "evening", key: "tmrEvening", icon: "🌇", en: "tomorrow evening" },
] as const;
const BOATS = [
  { id: "small_craft", key: "small", icon: "🛶" },
  { id: "mechanized", key: "mech", icon: "🚤" },
  { id: "large_vessel", key: "large", icon: "🚢" },
] as const;

const LOOK: Record<Decision, { key: UIKey; bg: string; fg: string; glyph: string }> = {
  GO: { key: "GO", bg: "#dcf5e3", fg: "#0b6b2c", glyph: "●" },
  CAUTION: { key: "CAUTION", bg: "#fff1cc", fg: "#8a5a00", glyph: "▲" },
  DONT_GO: { key: "DONT_GO", bg: "#fde0e0", fg: "#a61b1b", glyph: "■" },
  INSUFFICIENT_DATA: { key: "NA", bg: "#e8ecf1", fg: "#3d4a5c", glyph: "◇" },
  NOT_APPLICABLE: { key: "NA", bg: "#e8ecf1", fg: "#3d4a5c", glyph: "◇" },
};
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

type Kind = "safety" | "zones";
type Result = { bb: Blackboard; kind: Kind; practice: boolean; harbour: Harbour; when: string };
type ZoneRow = { id: string; score: number; distance_km: number; bearing: number; depth?: number | null };

function Chip({ on, onClick, children, big = false }: { on: boolean; onClick: () => void; children: ReactNode; big?: boolean }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on}
      className={`min-w-0 rounded-xl border-2 px-2.5 text-left leading-snug transition-colors break-words ${big ? "min-h-[64px] py-2 text-[16px]" : "min-h-[44px] py-1.5 text-[15px]"} ${on ? "border-sky-600 bg-sky-50 font-semibold text-sky-900" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"}`}>
      {children}
    </button>
  );
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
  const look = LOOK[decision];
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
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <fieldset>
          <legend className="mb-2 text-[14px] font-semibold uppercase tracking-wide text-slate-500">🗣 {t.chooseLang}</legend>
          <div className="flex flex-wrap gap-2">
            {LANGS.map((l) => <Chip key={l.id} on={lang === l.id} onClick={() => setLang(l.id)}><span lang={l.id} className="block whitespace-nowrap px-1 text-center">{l.name}</span></Chip>)}
          </div>
        </fieldset>

        <label className="mt-6 block">
          <span className="mb-2 block text-[14px] font-semibold uppercase tracking-wide text-slate-500">⚓ {t.harbour}</span>
          <select value={harbour.id} onChange={(e) => setHarbourId(e.target.value)}
            className="min-h-[56px] w-full rounded-xl border-2 border-slate-200 bg-white px-3 text-[18px] text-slate-900 focus:border-sky-600 focus:outline-none">
            {Object.entries(BY_STATE).map(([state, hs]) => (
              <optgroup key={state} label={state}>
                {hs.map((h) => <option key={h.id} value={h.id}>{local(h)}{lang !== "en" && h.names[lang] ? ` (${h.name})` : ""}</option>)}
              </optgroup>
            ))}
          </select>
        </label>

        <fieldset className="mt-6">
          <legend className="mb-2 text-[14px] font-semibold uppercase tracking-wide text-slate-500">🕒 {t.when}</legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {WHEN.map((w) => <Chip key={w.id} big on={when === w.id} onClick={() => setWhen(w.id)}><span className="flex items-center gap-2.5"><span className="text-[24px]" aria-hidden>{w.icon}</span>{t[w.key]}</span></Chip>)}
          </div>
        </fieldset>

        <fieldset className="mt-6">
          <legend className="mb-2 text-[14px] font-semibold uppercase tracking-wide text-slate-500">⛵ {t.boat}</legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {BOATS.map((b) => <Chip key={b.id} big on={boat === b.id} onClick={() => setBoat(b.id)}><span className="flex items-center gap-2.5"><span className="text-[24px]" aria-hidden>{b.icon}</span>{t[b.key]}</span></Chip>)}
          </div>
        </fieldset>

        <div className="mt-7 grid gap-3">
          <button type="button" disabled={!!running} onClick={() => run("safety")}
            className="min-h-[64px] rounded-2xl bg-sky-700 px-4 py-2 text-[19px] font-semibold leading-snug text-white shadow hover:bg-sky-800 disabled:opacity-60">🌊 {t.checkSafe}</button>
          <button type="button" disabled={!!running} onClick={() => run("zones")}
            className="min-h-[64px] rounded-2xl border-2 border-sky-700 bg-white px-4 py-2 text-[19px] font-semibold leading-snug text-sky-800 hover:bg-sky-50 disabled:opacity-60">🐟 {t.findFish}</button>
        </div>
        <label className="mt-4 flex cursor-pointer items-center gap-2 text-[14px] text-slate-600">
          <input type="checkbox" checked={practice} onChange={(e) => setPractice(e.target.checked)} className="h-5 w-5 accent-violet-600" />
          {t.practice}
        </label>
      </div>

      {/* ---------------- answer */}
      <div aria-live="polite" className="min-h-[200px]">
        {!running && !result && !error && (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-white/60 p-8 text-center">
            <div className="text-[44px]" aria-hidden>🌊</div>
            <p className="mt-2 text-[22px] font-semibold text-slate-800">{t.appTitle}</p>
            <p className="mt-1 text-[15px] text-slate-500">{local(harbour)} · {t[WHEN.find((w) => w.id === when)?.key ?? "tmrMorning"]} · {t[BOATS.find((b) => b.id === boat)?.key ?? "small"]}</p>
          </div>
        )}

        {running && (
          <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
            <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-sky-200 border-t-sky-700" aria-hidden />
            <p className="mt-4 text-[20px] font-semibold text-slate-800">{t.checking}</p>
            {running.total > 0 && (
              <div className="mx-auto mt-4 h-3 max-w-[320px] overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-sky-600 transition-all" style={{ width: `${Math.min(100, (running.done / running.total) * 100)}%` }} />
              </div>
            )}
            {waited > 8 && running.total === 0 && <p className="mt-3 text-[15px] text-slate-500">{t.waking}</p>}
          </div>
        )}

        {error && (
          <div className="rounded-2xl border-2 border-rose-200 bg-rose-50 p-6 text-center">
            <p className="text-[18px] font-semibold text-rose-900">{t.error}</p>
            <button type="button" onClick={() => run(result?.kind ?? "safety")} className="mt-3 min-h-[48px] rounded-xl bg-rose-700 px-5 text-[16px] font-semibold text-white">{t.tryAgain}</button>
          </div>
        )}

        {result && (
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            {result.practice && <div className="bg-[repeating-linear-gradient(135deg,#ede9fe_0_10px,#f5f3ff_10px_20px)] px-5 py-2 text-center text-[14px] font-semibold text-violet-800">{t.practiceOn}</div>}
            <div className="px-5 py-6 sm:px-6" style={{ background: look.bg, color: look.fg }}>
              <div className="flex items-center gap-4">
                <span className="text-[44px] leading-none" aria-hidden>{look.glyph}</span>
                <div>
                  <div className="text-[30px] font-bold leading-tight sm:text-[34px]">{t[look.key]}</div>
                  {result.kind === "safety" && result.bb.response?.headline && <p className="mt-1 text-[17px] leading-snug">{result.bb.response.headline}</p>}
                </div>
              </div>
              <p className="mt-3 text-[15px] opacity-90">
                ⚓ {local(result.harbour)}{result.kind === "safety" ? ` · 🕒 ${result.when}` : ""}
                {result.bb.final_assessment && decision !== "INSUFFICIENT_DATA" ? ` · ${t.confidence} ${Math.round(result.bb.final_assessment.confidence * 100)}%` : ""}
              </p>
            </div>

            <div className="space-y-5 px-5 py-5 sm:px-6">
              {decision === "INSUFFICIENT_DATA" && !result.practice && (
                <div className="rounded-xl bg-slate-50 p-4 text-[16px] text-slate-700">
                  {t.noDataTip}
                  <button type="button" onClick={() => { setPractice(true); run(result.kind, true); }} className="mt-3 block min-h-[44px] rounded-lg border-2 border-violet-600 px-4 text-[15px] font-semibold text-violet-700">{t.practice}</button>
                </div>
              )}

              {result.kind === "zones" && (
                <div>
                  <h3 className="text-[18px] font-bold text-slate-900">🐟 {t.zones}</h3>
                  {zones.length === 0 ? <p className="mt-1 text-[16px] text-slate-600">{t.noZones}</p> : (
                    <ul className="mt-2 space-y-2">
                      {zones.slice(0, 5).map((z, i) => (
                        <li key={z.id} className="flex items-center gap-4 rounded-xl border border-slate-200 p-3">
                          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-sky-100 text-[24px] text-sky-800" aria-hidden>
                            <span style={{ transform: `rotate(${z.bearing}deg)`, display: "inline-block" }}>↑</span>
                          </span>
                          <div className="text-[16px] text-slate-800">
                            <div className="font-semibold">{t.area} {i + 1} · <span className={z.score >= 0.7 ? "text-emerald-700" : "text-amber-700"}>{z.score >= 0.7 ? t.good : t.possible}</span></div>
                            <div className="text-slate-600">{Math.round(z.distance_km)} km {COMPASS[Math.round(z.bearing / 45) % 8]} {t.fromHarbour}{z.depth ? ` · ${t.depth} ${Math.round(Math.abs(z.depth))} m` : ""}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-2 text-[14px] text-slate-500">{t.zonesNote}</p>
                </div>
              )}

              {why.length > 0 && (
                <div>
                  <h3 className="text-[18px] font-bold text-slate-900">{t.why}</h3>
                  <ul className="mt-1 space-y-1.5 text-[16px] leading-snug text-slate-700">{why.map((x, i) => <li key={i} className="flex gap-2"><span aria-hidden>•</span><span>{x}</span></li>)}</ul>
                </div>
              )}
              {advice.length > 0 && (
                <div>
                  <h3 className="text-[18px] font-bold text-slate-900">{t.advice}</h3>
                  <ul className="mt-1 space-y-1.5 text-[16px] leading-snug text-slate-700">{advice.map((x, i) => <li key={i} className="flex gap-2"><span aria-hidden>✓</span><span>{x}</span></li>)}</ul>
                </div>
              )}

              <p className="rounded-xl bg-amber-50 px-4 py-3 text-[15px] font-medium text-amber-900">⚠ {t.official}</p>

              {variant === "community" && (
                <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
                  <button type="button" onClick={share} className="min-h-[44px] rounded-lg bg-emerald-600 px-4 text-[15px] font-semibold text-white">📤 {t.share}</button>
                  <button type="button" onClick={copy} className="min-h-[44px] rounded-lg border-2 border-slate-300 px-4 text-[15px] font-semibold text-slate-700">{copied ? `✓ ${t.copied}` : `📋 ${t.copy}`}</button>
                  <span className="ml-auto text-[13px] text-slate-500">{t.ref}: <Link href={`/evidence?trace=${result.bb.trace_id}`} className="font-mono text-sky-700 underline">{result.bb.trace_id}</Link></span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
