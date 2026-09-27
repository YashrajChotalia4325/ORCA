import type { Blackboard, DataMode, TraceEvent } from "./types";

export const API = process.env.NEXT_PUBLIC_ORCA_API ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* keep status text */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const get = <T,>(path: string) => req<T>(path);
export const post = <T,>(path: string, body?: unknown) => req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const del = <T,>(path: string) => req<T>(path, { method: "DELETE" });

export interface QueryAccepted { query_id: string; trace_id: string; conversation_id: string; mode: DataMode; scenario?: string | null; events_url: string; result_url: string }

export interface AskOptions {
  text: string; mode: DataMode; scenario?: string | null; conversationId?: string | null;
  role?: string | null; language?: string | null; vesselClass?: string | null; location?: { lat: number; lon: number } | null; speedKn?: number | null;
}

export function modeQuery(mode: DataMode, scenario?: string | null) {
  const p = new URLSearchParams({ mode });
  if (mode === "DEMO" && scenario) p.set("scenario", scenario);
  return p.toString();
}

export async function ask(o: AskOptions): Promise<QueryAccepted> {
  const body: Record<string, unknown> = { text: o.text };
  if (o.conversationId) body.conversation_id = o.conversationId;
  if (o.role) body.role = o.role;
  if (o.language) body.language = o.language;
  if (o.vesselClass) body.vessel_class = o.vesselClass;
  if (o.location) body.location = o.location;
  if (o.speedKn) body.speed_kn = o.speedKn;
  return post<QueryAccepted>(`/api/query?${modeQuery(o.mode, o.scenario)}`, body);
}

/** Subscribe to the live trace; resolves with the final blackboard. */
export function follow(queryId: string, onEvent: (e: TraceEvent) => void): Promise<Blackboard> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${API}/api/query/${queryId}/events`);
    let finished = false;
    es.onmessage = async (m) => {
      try {
        const ev = JSON.parse(m.data) as TraceEvent;
        onEvent(ev);
        if (ev.type === "done") {
          finished = true;
          es.close();
          resolve(await get<Blackboard>(`/api/query/${queryId}`));
        }
      } catch (err) { es.close(); reject(err); }
    };
    es.onerror = async () => {
      es.close();
      if (finished) return;
      // stream closed early (e.g. replayed from store) — fetch the result directly
      try { resolve(await get<Blackboard>(`/api/query/${queryId}`)); } catch (err) { reject(err); }
    };
  });
}
