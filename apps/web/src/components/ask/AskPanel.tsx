"use client";
import { useEffect, useRef, useState } from "react";
import { get } from "@/lib/api";
import { AGENT_LABEL } from "@/lib/format";
import { useOrca, type Turn } from "@/lib/store";
import type { Scenario } from "@/lib/types";
import { PipelineStrip } from "../shell/AgentDock";
import { useMapClick } from "../shell/ConsoleShell";
import ResultCard from "../result/ResultCard";

const LIVE_SUGGEST = [
  "Is it safe for a fishing boat to leave Kochi tomorrow at 5 AM?",
  "Is it safe to fish 30 km off the coast of Kochi tomorrow morning?",
  "Calculate a lower-risk route from Mumbai to Goa tomorrow morning",
  "Show potential fishing zones near Mangaluru",
  "Show cyclone risk across the Odisha coast for the next 24 hours",
  "Why did chlorophyll concentration decline off Kochi over the past 14 days?",
  "क्या कल सुबह मुंबई से मछली पकड़ने जाना सुरक्षित है?",
  "நாளை காலை ராமேஸ்வரத்தில் இருந்து மீன்பிடிக்க போகலாமா?",
];
const LANGS = [["", "auto"], ["en", "English"], ["hi", "हिन्दी"], ["mr", "मराठी"], ["ta", "தமிழ்"], ["te", "తెలుగు"], ["ml", "മലയാളം"], ["kn", "ಕನ್ನಡ"], ["bn", "বাংলা"]];
const ROLES = [["", "auto"], ["fisherman", "Fisherman"], ["authority", "Authority"], ["researcher", "Researcher"], ["operator", "Maritime operator"]];
const VESSELS = [["", "auto"], ["small_craft", "Small craft"], ["mechanized", "Mechanised"], ["large_vessel", "Large vessel"]];

function Running({ t }: { t: Turn }) {
  const started = new Map<string, "run" | "ok" | "fail" | "part">();
  for (const e of t.events) {
    if (!e.agent) continue;
    if (e.type === "agent_start") started.set(e.agent, "run");
    if (e.type === "agent_end") started.set(e.agent, e.data?.status === "FAILED" ? "fail" : e.data?.status === "PARTIAL" ? "part" : "ok");
  }
  const last = [...t.events].reverse().find((e) => e.type === "tool" || e.type === "replan" || e.type === "conflict");
  return (
    <div className="px-4 py-3">
      <PipelineStrip events={t.events} compact />
      <div className="mt-3 grid grid-cols-2 gap-1">
        {[...started.entries()].map(([a, s]) => (
          <div key={a} className="flex items-center gap-2 text-[12px]">
            <span className={s === "run" ? "pulse text-accent" : s === "fail" ? "text-danger" : s === "part" ? "text-caution" : "text-go"}>{s === "run" ? "◌" : s === "fail" ? "✕" : s === "part" ? "◐" : "✓"}</span>
            <span className={s === "run" ? "text-ink" : "text-ink-2"}>{AGENT_LABEL[a] ?? a}</span>
          </div>
        ))}
      </div>
      {last && <p className="mt-2 truncate text-[11px] text-ink-3">{last.message}</p>}
    </div>
  );
}

export default function AskPanel({ presetQuery, compact = false }: { presetQuery?: string | null; compact?: boolean }) {
  const { turns, runQuery, mode, scenario, role, language, vessel, setPrefs, clearConversation } = useOrca();
  const [text, setText] = useState(presetQuery ?? "");
  const [scen, setScen] = useState<Scenario[]>([]);
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { get<Scenario[]>("/api/demo/scenarios").then(setScen).catch(() => undefined); }, []);
  const registerClick = useMapClick();
  useEffect(() => {
    registerClick((lat, lon) => setPoint({ lat, lon }));
    return () => registerClick(undefined);
  }, [registerClick]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns.length]);
  const running = turns.some((t) => t.status === "running");
  const suggestions = mode === "DEMO" ? scen.find((s) => s.id === scenario)?.queries ?? [] : LIVE_SUGGEST;

  const submit = async (q?: string) => {
    const v = (q ?? text).trim();
    if (!v || running) return;
    setText("");
    await runQuery(v, { location: point });
    setPoint(null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {!compact && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2 text-[11.5px]">
          {[["Language", LANGS, language, "language"], ["Role", ROLES, role, "role"], ["Vessel", VESSELS, vessel, "vessel"]].map(([lbl, opts, val, key]) => (
            <label key={lbl as string} className="flex items-center gap-1 text-ink-3">{lbl as string}
              <select value={(val as string) ?? ""} onChange={(e) => setPrefs({ [key as string]: e.target.value || null })}
                className="rounded border border-line-2 bg-panel-2 px-1.5 py-0.5 text-ink focus:outline-none">
                {(opts as string[][]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          ))}
          {turns.length > 0 && <button onClick={clearConversation} className="ml-auto text-ink-3 hover:text-ink-2">New conversation</button>}
        </div>
      )}
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {turns.length === 0 && (
          <div className="px-4 py-5">
            <p className="text-[13px] leading-relaxed text-ink-2">Ask in any of 8 Indian languages or English. ORCA plans the work, sends specialised agents to live official and scientific sources, checks them against each other and answers only as far as the evidence allows.</p>
            <div className="lbl mb-2 mt-4">{mode === "DEMO" ? "Scenario questions" : "Try"}</div>
            <div className="flex flex-col gap-1.5">
              {suggestions.map((s) => (
                <button key={s} onClick={() => submit(s)} className="rounded border border-line-2 px-3 py-2 text-left text-[12.5px] text-ink-2 hover:border-accent/60 hover:text-ink">{s}</button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t) => (
          <div key={t.id} className="border-b border-line">
            <div className="flex items-start gap-2 bg-panel-2/60 px-4 py-2.5">
              <span className="lbl mt-[3px]">You</span>
              <p className="text-[13px] text-ink">{t.text}</p>
              <span className={`ml-auto shrink-0 font-cond text-[9.5px] tracking-widest ${t.mode === "LIVE" ? "text-live" : t.mode === "DEMO" ? "text-demo" : "text-replay"}`}>{t.mode}</span>
            </div>
            {t.status === "running" && <Running t={t} />}
            {t.status === "error" && <p className="px-4 py-3 text-[12px] text-danger">{t.error}</p>}
            {t.status === "done" && t.bb && <ResultCard bb={t.bb} />}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <div className="border-t border-line p-3">
        {point && <div className="mb-1.5 text-[11px] text-accent">Using map point {point.lat.toFixed(3)}°N {point.lon.toFixed(3)}°E · <button className="underline" onClick={() => setPoint(null)}>clear</button></div>}
        <div className="flex items-end gap-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="Is it safe to fish 20 km off Kochi tomorrow morning?"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
            className="min-h-[44px] flex-1 resize-none rounded-md border border-line-2 bg-panel-2 px-3 py-2 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent/70 focus:outline-none" />
          <button onClick={() => submit()} disabled={running || !text.trim()}
            className="h-[44px] rounded-md bg-accent px-4 text-[13px] font-medium text-abyss disabled:opacity-40">{running ? "…" : "Ask"}</button>
        </div>
      </div>
    </div>
  );
}
