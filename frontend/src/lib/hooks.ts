import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Meta } from "./types";

export const LIVE_EVENT = "bft:update";

export interface LiveUpdate {
  deals: boolean;
  watches: boolean;
  notifications: import("./types").Notice[];
}

/** Busca dados e recarrega quando o servidor avisa de novidades. */
export function useData<T>(path: string, live?: (update: LiveUpdate) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const current = useRef(path);
  current.current = path;

  const reload = useCallback(async () => {
    try {
      const result = await api.get<T>(path);
      if (current.current !== path) return;
      setData(result);
      setError("");
    } catch (e) {
      if (current.current === path) setError((e as Error).message);
    } finally {
      if (current.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(true);
    void reload();
  }, [reload]);

  const liveRef = useRef(live);
  liveRef.current = live;
  useEffect(() => {
    const listener = (event: Event) => {
      if (liveRef.current?.((event as CustomEvent<LiveUpdate>).detail)) void reload();
    };
    window.addEventListener(LIVE_EVENT, listener);
    return () => window.removeEventListener(LIVE_EVENT, listener);
  }, [reload]);

  return { data, error, loading, reload, setData };
}

let metaCache: Promise<Meta> | null = null;

export function useMeta() {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    metaCache ??= api.get<Meta>("/meta").catch((e) => {
      metaCache = null;
      throw e;
    });
    metaCache.then(setMeta).catch(() => {});
  }, []);
  return meta;
}
