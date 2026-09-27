"use client";
import ResultCard from "./result/ResultCard";
import { PipelineStrip } from "./shell/AgentDock";
import type { Turn } from "@/lib/store";

/** Shows the latest turn matching a predicate: live pipeline while running, full result when done. */
export default function TurnView({ turn, empty }: { turn?: Turn; empty: React.ReactNode }) {
  if (!turn) return <>{empty}</>;
  if (turn.status === "running") return <div className="px-4 py-3"><div className="mb-2 text-[12px] text-ink-2">“{turn.text}”</div><PipelineStrip events={turn.events} compact /><p className="mt-2 truncate text-[11px] text-ink-3">{turn.events.at(-1)?.message}</p></div>;
  if (turn.status === "error") return <p className="px-4 py-3 text-[12px] text-danger">{turn.error}</p>;
  return turn.bb ? <ResultCard bb={turn.bb} /> : null;
}
