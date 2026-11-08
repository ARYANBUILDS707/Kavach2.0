// One read at a time per resource: loads on mount and whenever `key` or `loader` changes, aborts
// on unmount, and on a failed refresh keeps the last good data marked stale (DESIGN.md
// "Background refresh" and "API failure"). No polling here: callers refresh on demand.
// `loader` must be memoised (useCallback) so it changes only when its inputs do.
import { useCallback, useEffect, useState } from "react";

import { isApiError, type ApiError } from "./api/errors";

export interface Resource<T> {
  data: T | null;
  error: ApiError | Error | null;
  loading: boolean;
  /** True when `data` is from an earlier load and the latest attempt failed. */
  stale: boolean;
  updatedAt: number | null;
  reload: () => void;
}

interface Settled<T> {
  /** Which request (key + attempt) this result belongs to. */
  token: string;
  key: string;
  data: T | null;
  error: ApiError | Error | null;
  updatedAt: number | null;
}

export function useResource<T>(
  key: string,
  loader: (signal: AbortSignal) => Promise<T>,
  now: () => number = Date.now,
): Resource<T> {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const token = `${key}#${String(attempt)}`;

  useEffect(() => {
    const controller = new AbortController();
    loader(controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        setSettled({ token, key, data: value, error: null, updatedAt: now() });
      },
      (failure: unknown) => {
        if (controller.signal.aborted) return;
        const error =
          isApiError(failure) || failure instanceof Error ? failure : new Error("failed");
        // Keep the last good data for the same key, so a failed refresh shows as stale.
        setSettled((previous) => ({
          token,
          key,
          data: previous?.key === key ? previous.data : null,
          error,
          updatedAt: previous?.key === key ? previous.updatedAt : null,
        }));
      },
    );
    return () => {
      controller.abort();
    };
  }, [token, key, loader, now]);

  const reload = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  // Results for another key are never shown (no flash of the previous incident).
  const current = settled?.key === key ? settled : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;
  return {
    data,
    error,
    loading: settled?.token !== token,
    stale: data !== null && error !== null,
    updatedAt: current?.updatedAt ?? null,
    reload,
  };
}
