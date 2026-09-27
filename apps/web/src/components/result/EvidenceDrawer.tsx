"use client";
import { useEffect, useState } from "react";
import { fmtVal, ist, pct, utc } from "@/lib/format";
import { useOrca } from "@/lib/store";
import type { Blackboard, Claim, EvidenceItem } from "@/lib/types";
import { FreshTag, LevelTag } from "./primitives";

const EPI_COLOR: Record<string, string> = { OBSERVATION: "var(--accent-2)", FORECAST: "var(--s3)", CORRELATION: "var(--demo)", HYPOTHESIS: "var(--caution)", CONCLUSION: "var(--accent)" };

export function ClaimCard({ c, items, onFocus }: { c: Claim; items: EvidenceItem[]; onFocus?: (c: Claim) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded border border-line-2 bg-panel-2/60">
      <button onClick={() => { setOpen(!open); onFocus?.(c); }} className="flex w-full items-start gap-2 px-3 py-2 text-left" aria-expanded={open}>
        <span className="mt-[2px] shrink-0 rounded-sm border border-line-2 px-1 font-cond text-[9px] font-semibold tracking-wider" style={{ color: EPI_COLOR[c.epistemic] ?? "var(--ink-2)" }}>{c.epistemic}</span>
        <span className="min-w-0 flex-1 text-[12px] leading-snug text-ink">{c.text}</span>
        <span className="shrink-0 text-right">
          {c.confidence && <span className="num block text-[12px] text-accent">{pct(c.confidence.value)}</span>}
          <span className="block text-[10px] text-ink-3">{c.n_supporting}/{c.n_supporting + c.n_contradicting} agree · {c.n_sources} lineage{c.n_sources === 1 ? "" : "s"}</span>
        </span>
      </button>
      {open && (
        <div className="rise border-t border-line px-3 py-2">
          {c.level && <div className="mb-1"><LevelTag level={c.level} /></div>}
          {c.confidence && <p className="mb-2 text-[11px] text-ink-3">{c.confidence.formula} · Q {c.confidence.evidence_quality.toFixed(2)} · G {c.confidence.agreement.toFixed(2)} · weakest: {c.confidence.weakest_link}</p>}
          {items.length === 0 && <p className="text-[11px] text-ink-3">Derived claim (no direct evidence item).</p>}
          {items.map((e) => (
            <div key={e.id} className="mb-2 rounded border border-line bg-abyss/40 p-2 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-ink">{e.source} <span className="text-ink-3">· {e.kind.toLowerCase()}</span></span>
                <span className="num text-ink">{e.value !== null && e.value !== undefined ? fmtVal(e.value, e.units, 2) : e.value_text}</span>
              </div>
              <div className="mt-1 grid grid-cols-2 gap-x-3 text-ink-2">
                <span>valid <span className="num">{ist(e.valid_time)}</span></span>
                <span>retrieved <span className="num">{utc(e.provenance.retrieval_timestamp)}</span></span>
                <span>dataset <span className="num text-ink-3">{e.provenance.dataset}</span></span>
                <span>res. {e.provenance.spatial_resolution || "—"} · {e.provenance.temporal_resolution || "—"}</span>
                {e.provenance.issued_at && <span>model run <span className="num">{utc(e.provenance.issued_at)}</span></span>}
                <span>lineage <span className="num">{e.lineage}</span></span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <FreshTag status={e.provenance.freshness.status} label={e.provenance.freshness.label} />
                <span className={e.supports === false ? "text-serious" : "text-go"}>{e.supports === false ? "contradicts" : "supports"}</span>
              </div>
              <div className="num mt-1 text-[10px] text-ink-3">A {e.authority.toFixed(2)} × F {e.freshness.toFixed(2)} × S {e.spatial.toFixed(2)} × T {e.temporal.toFixed(2)} = w {e.weight.toFixed(3)}</div>
              {e.provenance.source_url && <div className="mt-1 truncate text-[10px] text-ink-3" title={e.provenance.source_url}>{e.provenance.source_url}</div>}
              {e.provenance.notes?.length > 0 && <div className="mt-0.5 text-[10px] text-ink-3">{e.provenance.notes.join(" · ")}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EvidenceDrawer({ bb, onClose }: { bb: Blackboard; onClose: () => void }) {
  const { setHighlight, flyTo } = useOrca();
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const byClaim = (id: string) => bb.evidence.filter((e) => e.claim_id === id);
  const focus = (c: Claim) => {
    if (c.map_focus) { setHighlight({ claimId: c.id, lat: c.map_focus.lat, lon: c.map_focus.lon }); flyTo(c.map_focus.lat, c.map_focus.lon); }
  };
  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-[560px] max-w-full flex-col border-l border-line-2 bg-panel shadow-2xl" role="dialog" aria-label="evidence">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div>
          <div className="lbl">Evidence & provenance · {bb.trace_id}</div>
          <div className="text-[14px] text-ink">{bb.claims.length} claims · {bb.evidence.length} evidence items · {bb.conflicts.length} conflicts</div>
        </div>
        <button onClick={onClose} className="rounded border border-line-2 px-2 py-1 text-[12px] text-ink-2 hover:text-ink">Close ✕</button>
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-2">{bb.claims.map((c) => <ClaimCard key={c.id} c={c} items={byClaim(c.id)} onFocus={focus} />)}</div>
        {bb.failures.length > 0 && (
          <div className="mt-4">
            <div className="lbl mb-1">Sources excluded from this answer</div>
            {bb.failures.map((f, i) => <p key={i} className="text-[11.5px] text-ink-2"><span className="text-danger">✕</span> {f.source} — <span className="num">{f.status}</span>: {f.reason}{f.impact ? ` → ${f.impact}` : ""}</p>)}
          </div>
        )}
      </div>
    </div>
  );
}
