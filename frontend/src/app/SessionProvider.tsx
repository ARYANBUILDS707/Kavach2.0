// Session state in memory only (FRONTEND_MVP1_PLAN.md section 5). The cookie is HttpOnly and
// set by the server; the CSRF token lives in React state and is restored by GET /auth/session.
// Nothing here touches browser storage.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getSession, login, logout } from "../lib/api/endpoints";
import { ApiError, isApiError } from "../lib/api/errors";
import type { SessionData } from "../lib/api/types";
import { useApi } from "./ApiContext";

/** Warn this long before the session's absolute or idle deadline. */
export const EXPIRY_WARNING_MS = 5 * 60 * 1000;
// Browsers fire any setTimeout above 2^31-1 ms (about 24.8 days) immediately, so a deadline
// that far away is not scheduled. The server enforces expiry regardless (8 h maximum, D03).
const MAX_TIMER_MS = 2 ** 31 - 1;

export type SessionState =
  | { status: "checking" }
  | { status: "signedOut"; reason: "none" | "expired" | "signedOut" }
  | { status: "signedIn"; session: SessionData }
  | { status: "unavailable"; error: ApiError };

interface SessionContextValue {
  state: SessionState;
  expiringSoon: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  /** Resolves with the error when the server could not confirm the sign-out. */
  signOut: () => Promise<ApiError | null>;
  retry: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  now = () => Date.now(),
}: {
  children: ReactNode;
  now?: () => number;
}) {
  const client = useApi();
  const [state, setState] = useState<SessionState>({ status: "checking" });
  const [expiringSoon, setExpiringSoon] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const expire = useCallback(() => {
    setExpiringSoon(false);
    setState({ status: "signedOut", reason: "expired" });
  }, []);

  // Restore the session on load (and on an explicit retry).
  useEffect(() => {
    const controller = new AbortController();
    getSession(client, controller.signal).then(
      (response) => {
        setState({ status: "signedIn", session: response.data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (isApiError(error) && error.status === 401) {
          setState({ status: "signedOut", reason: "none" });
        } else {
          setState({
            status: "unavailable",
            error: isApiError(error)
              ? error
              : new ApiError({ status: 0, code: "UNEXPECTED_RESPONSE", message: "" }),
          });
        }
      },
    );
    return () => {
      controller.abort();
    };
  }, [client, attempt]);

  // Any 401 SESSION_EXPIRED from any request ends the session in one place.
  useEffect(() => client.onSessionExpired(expire), [client, expire]);

  // Warn before the deadline and end the session at it.
  const expiresAt = state.status === "signedIn" ? Date.parse(state.session.expires_at) : null;
  useEffect(() => {
    if (expiresAt === null || Number.isNaN(expiresAt)) return;
    const remaining = Math.max(0, expiresAt - now());
    if (remaining > MAX_TIMER_MS) return;
    const warn = setTimeout(
      () => {
        setExpiringSoon(true);
      },
      Math.max(0, remaining - EXPIRY_WARNING_MS),
    );
    const end = setTimeout(expire, remaining);
    return () => {
      clearTimeout(warn);
      clearTimeout(end);
    };
  }, [expiresAt, expire, now]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      const response = await login(client, { username, password });
      setExpiringSoon(false);
      setState({ status: "signedIn", session: response.data });
    },
    [client],
  );

  const signOut = useCallback(async (): Promise<ApiError | null> => {
    if (state.status !== "signedIn") return null;
    try {
      await logout(client, state.session.csrf_token);
    } catch (error) {
      // A 401 means the session is already gone; anything else may leave it active.
      if (!(isApiError(error) && error.status === 401)) {
        return isApiError(error)
          ? error
          : new ApiError({ status: 0, code: "UNEXPECTED_RESPONSE", message: "" });
      }
    }
    setExpiringSoon(false);
    setState({ status: "signedOut", reason: "signedOut" });
    return null;
  }, [client, state]);

  const retry = useCallback(() => {
    setState({ status: "checking" });
    setAttempt((value) => value + 1);
  }, []);

  const value = useMemo(
    () => ({ state, expiringSoon, signIn, signOut, retry }),
    [state, expiringSoon, signIn, signOut, retry],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
