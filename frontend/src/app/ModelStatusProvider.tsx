// The single source of SMS model status for the header, Overview and System page: one request
// per 30 s while the tab is visible, none while hidden or during a 429 pause, so the shared
// 120-per-minute read budget is never spent twice for the same information.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { getModels } from "../lib/api/endpoints";
import { isApiError, type ApiError } from "../lib/api/errors";
import type { SmsModelStatus } from "../lib/api/types";
import { useApi } from "./ApiContext";

export const MODEL_POLL_MS = 30_000;

export interface ModelStatusValue {
  status: SmsModelStatus | null;
  error: ApiError | Error | null;
  loading: boolean;
  checkedAt: number | null;
  refresh: () => void;
}

const ModelStatusContext = createContext<ModelStatusValue | null>(null);

export function ModelStatusProvider({
  children,
  now = Date.now,
}: {
  children: ReactNode;
  now?: () => number;
}) {
  const client = useApi();
  const [status, setStatus] = useState<SmsModelStatus | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const inFlight = useRef<AbortController | null>(null);
  const lastCheck = useRef(0);

  const check = useCallback(() => {
    // Never two requests at once, and nothing while the client is paused after a 429.
    if (inFlight.current !== null || client.pausedForMs() > 0) return;
    const controller = new AbortController();
    inFlight.current = controller;
    lastCheck.current = now();
    getModels(client, controller.signal).then(
      (response) => {
        if (controller.signal.aborted) return;
        setStatus(response.data.sms_classifier);
        setError(null);
        setCheckedAt(now());
      },
      (failure: unknown) => {
        if (controller.signal.aborted) return;
        setError(isApiError(failure) || failure instanceof Error ? failure : new Error("failed"));
      },
    ).finally(() => {
      if (inFlight.current === controller) inFlight.current = null;
      setLoading(false);
    });
  }, [client, now]);

  useEffect(() => {
    check();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") check();
    }, MODEL_POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible" && now() - lastCheck.current >= MODEL_POLL_MS) {
        check();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      inFlight.current?.abort();
      inFlight.current = null;
    };
  }, [check, now]);

  const value = useMemo(
    () => ({ status, error, loading, checkedAt, refresh: check }),
    [status, error, loading, checkedAt, check],
  );
  return <ModelStatusContext.Provider value={value}>{children}</ModelStatusContext.Provider>;
}

export function useModelStatus(): ModelStatusValue {
  const value = useContext(ModelStatusContext);
  if (value === null) throw new Error("useModelStatus must be used inside ModelStatusProvider");
  return value;
}
