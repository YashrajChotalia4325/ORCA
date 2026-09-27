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

/** Reads a query-string parameter (client only; null during SSR). */
export function useQueryParam(name: string): string | null {
  const search = useSyncExternalStore(subscribeLocation, () => window.location.search, () => "");
  return new URLSearchParams(search).get(name);
}
