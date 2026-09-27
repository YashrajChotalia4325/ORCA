"use client";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { get } from "./api";

/** GET a JSON endpoint, optionally polling. Errors are surfaced, never replaced by placeholder data. */
export function useApi<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback((): Promise<void> => {
    if (!path) return Promise.resolve();
    return get<T>(path)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [path]);
  useEffect(() => {
    const first = setTimeout(() => { setLoading(true); load(); }, 0);
    const i = pollMs ? setInterval(load, pollMs) : undefined;
    return () => { clearTimeout(first); if (i) clearInterval(i); };
  }, [load, pollMs]);
  return { data, error, loading, reload: load };
}

const subscribeLocation = (cb: () => void) => { window.addEventListener("popstate", cb); return () => window.removeEventListener("popstate", cb); };

const STORE_EVT = "orca-stored";
const subscribeStored = (cb: () => void) => {
  window.addEventListener("storage", cb); window.addEventListener(STORE_EVT, cb);
  return () => { window.removeEventListener("storage", cb); window.removeEventListener(STORE_EVT, cb); };
};
const memStore = new Map<string, string>();   // used when localStorage is blocked
function readStored(key: string): string | null {
  try { return window.localStorage.getItem(key) ?? memStore.get(key) ?? null; } catch { return memStore.get(key) ?? null; }
}

/** A string preference remembered in localStorage (falls back silently when storage is unavailable). */
export function useStoredState<T extends string>(key: string, fallback: T): [T, (v: T) => void] {
  const v = useSyncExternalStore(subscribeStored, () => readStored(key), () => null);
  const set = useCallback((next: T) => {
    memStore.set(key, next);
    try { window.localStorage.setItem(key, next); } catch { /* storage blocked — memory only */ }
    window.dispatchEvent(new Event(STORE_EVT));
  }, [key]);
  return [(v as T | null) ?? fallback, set];
}

/** Current URL hash without '#' (client only; empty during SSR). */
export function useHash(): string {
  return useSyncExternalStore(
    (cb) => { window.addEventListener("hashchange", cb); return () => window.removeEventListener("hashchange", cb); },
    () => window.location.hash.slice(1), () => "");
}

/** Reads a query-string parameter (client only; null during SSR). */
export function useQueryParam(name: string): string | null {
  const search = useSyncExternalStore(subscribeLocation, () => window.location.search, () => "");
  return new URLSearchParams(search).get(name);
}
