"use client";
import { useEffect, useState } from "react";
import AgentGraph from "@/components/agents/AgentGraph";
import { StagePanel } from "@/components/shell/ConsoleShell";
import { get } from "@/lib/api";
import { AGENT_LABEL } from "@/lib/format";
import { useApi, useQueryParam } from "@/lib/hooks";
import { useActiveTurn } from "@/lib/store";
import type { AgentInfo, Blackboard } from "@/lib/types";

export default function Agents() {
  const trace = useQueryParam("trace");
  const turn = useActiveTurn();
  const catalog = useApi<AgentInfo[]>("/api/agents");
  const [bb, setBb] = useState<Blackboard | null>(null);
  const [sel, setSel] = useState<string>("planner");
  // explicit ?trace=… wins; otherwise the live turn; otherwise the most recent stored trace
  const fallback = !trace && !turn;
  useEffect(() => {
    if (trace) { get<Blackboard>(`/api/query/${trace}`).then(setBb).catch(() => setBb(null)); return; }
    if (fallback) get<{ trace_id: string }[]>("/api/traces?limit=1").then((t) => t[0] && get<Blackboard>(`/api/query/${t[0].trace_id}`).then(setBb)).catch(() => setBb(null));
  }, [trace, fallback]);
  const useStored = !!trace || fallback;
  const events = useStored ? bb?.events ?? [] : turn?.events ?? [];
  const board = useStored ? bb : turn?.bb;
  const info = catalog.data?.find((a) => a.name === sel);
  const runs = board ? Object.values(board.agents).filter((r) => r.agent === sel) : [];
  return (
    <StagePanel>
      <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-6 px-6 py-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div>
          <div className="lbl">Agent network</div>
          <h1 className="mt-1 text-[22px] font-light text-ink">{catalog.data?.length ?? 13} specialised agents on a shared blackboard</h1>
          <p className="mt-1 text-[12.5px] text-ink-2">
            {board ? <>Showing <span className="num text-ink">{board.trace_id}</span> — “{board.request.text}”. Nodes light up as agents run; edges carry typed outputs, not free text. Re-planned runs are counted per node.</>
              : "Run a query in Ask ORCA (or open a trace) to watch agents activate in real time."}
          </p>
          <div className="mt-4 rounded-lg border border-line-2 bg-panel p-3">
            <AgentGraph events={events} bb={board} height={620} onSelect={(a) => a !== "orca" && setSel(a)} />
          </div>
          {board?.supersteps && board.supersteps.length > 0 && (
            <div className="mt-3 rounded border border-line-2 bg-panel p-3 text-[12px]">
              <div className="lbl mb-1">LangGraph supersteps · {board.supersteps.length}</div>
              <p className="mb-2 text-[11px] text-ink-3">Each superstep fans out every ready task with <span className="num">Send</span>; tasks in one superstep run in parallel and join before the next.</p>
              <ol className="flex flex-col gap-1">
                {board.supersteps.map((s) => (
                  <li key={s.wave} className="flex items-baseline gap-2">
                    <span className="num w-7 shrink-0 text-right text-ink-3">{s.wave}</span>
                    {s.round > 0 && <span className="num shrink-0 text-[10.5px] text-replay">R{s.round}</span>}
                    <span className="flex flex-wrap gap-1">{s.tasks.map((t) => <span key={t} className="num rounded-sm border border-line-2 px-1.5 py-[1px] text-[10.5px] text-ink-2">{t}</span>)}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {board && board.plan.replans.length > 0 && (
            <div className="mt-3 rounded border border-replay/40 bg-panel p-3 text-[12px]">
              <div className="lbl mb-1 text-replay">Re-planning</div>
              {board.plan.replans.map((r, i) => <p key={i} className="text-ink-2"><span className="num text-replay">{r.rule}</span> round {r.round}: {r.detail}</p>)}
            </div>
          )}
        </div>
        <aside className="flex flex-col gap-3">
          <div className="rounded-lg border border-line-2 bg-panel p-4">
            <div className="flex flex-wrap gap-1">
              {catalog.data?.map((a) => <button key={a.name} onClick={() => setSel(a.name)} className={`rounded px-2 py-0.5 text-[11px] ${sel === a.name ? "bg-accent text-abyss" : "border border-line-2 text-ink-2"}`}>{AGENT_LABEL[a.name] ?? a.name}</button>)}
            </div>
            {info && (
              <div className="mt-3 text-[12px]">
                <div className="text-[15px] text-ink">{info.title}</div>
                <p className="mt-1 text-ink-2">{info.responsibility}</p>
                <div className="lbl mb-1 mt-3">Tools</div>
                <div className="flex flex-wrap gap-1">{info.tools.map((t) => <span key={t} className="num rounded-sm border border-line-2 px-1.5 py-[1px] text-[10.5px] text-ink-2">{t}</span>)}</div>
                <div className="lbl mb-1 mt-3">Consumes</div>
                <div className="text-ink-2">{info.consumes.join(", ") || "—"}</div>
                <div className="mt-2 text-[11px] text-ink-3">{info.deterministic ? "Deterministic — no LLM involved." : "May use the optional LLM (validated / grounding-checked)."}</div>
                {info.output_schema ? <details className="mt-2"><summary className="cursor-pointer text-[11px] text-accent">typed output schema</summary><pre className="scroll-thin mt-1 max-h-[220px] overflow-auto rounded bg-abyss p-2 text-[10px] text-ink-3">{JSON.stringify(info.output_schema, null, 1).slice(0, 4000)}</pre></details> : null}
              </div>
            )}
          </div>
          {runs.map((r) => (
            <div key={r.task_id} className="rounded-lg border border-line-2 bg-panel p-3 text-[12px]">
              <div className="flex justify-between"><span className="num text-ink">{r.task_id}</span><span style={{ color: r.status === "FAILED" ? "var(--danger)" : r.status === "PARTIAL" ? "var(--caution)" : "var(--go)" }}>{r.status}</span></div>
              <p className="mt-1 text-ink-2">{r.summary}</p>
              <div className="num mt-1 text-[10.5px] text-ink-3">{r.duration_ms !== null && r.duration_ms !== undefined ? `${Math.round(r.duration_ms)} ms` : ""} · tools {r.tools_used.join(", ") || "—"} · sources {r.sources_used.join(", ") || "—"}</div>
              {r.failures.map((f, i) => <p key={i} className="mt-1 text-[11px] text-danger">✕ {f.source}: {f.status}</p>)}
              {r.output && <details className="mt-1.5"><summary className="cursor-pointer text-[11px] text-accent">output (blackboard)</summary><pre className="scroll-thin mt-1 max-h-[260px] overflow-auto rounded bg-abyss p-2 text-[10px] text-ink-3">{JSON.stringify(r.output, null, 1).slice(0, 6000)}</pre></details>}
            </div>
          ))}
        </aside>
      </div>
    </StagePanel>
  );
}
