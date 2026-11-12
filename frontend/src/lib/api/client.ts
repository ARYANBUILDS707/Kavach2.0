// The only HTTP layer (FRONTEND_MVP1_PLAN.md section 6.1). Same-origin relative URLs, the
// HttpOnly session cookie as the only credential, CSRF only on mutations, bounded timeouts,
// and a shared pause after any 429 so polling cannot burn the 120-per-minute read budget.
import { ApiError, clientError } from "./errors";

export const READ_TIMEOUT_MS = 15_000;
export const WRITE_TIMEOUT_MS = 35_000;
const READ_RETRY_DELAYS_MS = [1_000, 3_000];

type Query = Record<string, string | number | undefined>;

export interface ClientOptions {
  fetch: typeof fetch;
  /** Injected so tests do not wait; defaults to a real timer. */
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

export interface RequestOptions {
  query?: Query;
  signal?: AbortSignal;
}

export interface MutationOptions {
  csrfToken?: string;
  signal?: AbortSignal;
}

export interface ApiClient {
  get<T>(path: string, options?: RequestOptions): Promise<T>;
  post<T>(path: string, body: unknown, options?: MutationOptions): Promise<T | null>;
  /** Called for every 401 SESSION_EXPIRED, so the session can be cleared in one place. */
  onSessionExpired(listener: () => void): () => void;
  /** Milliseconds until reads may resume after a 429, or 0. */
  pausedForMs(): number;
}

function url(path: string, query: Query | undefined): string {
  if (!path.startsWith("/api/") || path.startsWith("//")) {
    throw new Error("API paths must be relative and under /api/");
  }
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(name, String(value));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

function retryAfter(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  if (value === null || !/^\d+$/.test(value)) return null;
  return Number(value);
}

function isErrorEnvelope(value: unknown): value is {
  error: { code: string; message: string };
  request_id: string;
} {
  if (typeof value !== "object" || value === null) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

async function errorFrom(response: Response): Promise<ApiError> {
  const headerId = response.headers.get("X-Request-ID");
  const body: unknown = await response.json().catch(() => null);
  if (isErrorEnvelope(body)) {
    return new ApiError({
      status: response.status,
      code: body.error.code,
      message: body.error.message,
      requestId: body.request_id,
      retryAfterSeconds: retryAfter(response),
    });
  }
  return new ApiError({
    status: response.status,
    code: "UNEXPECTED_RESPONSE",
    message: "The server returned an unexpected response",
    requestId: headerId,
    retryAfterSeconds: retryAfter(response),
  });
}

export function createClient(options: ClientOptions): ApiClient {
  const fetchImpl = options.fetch;
  const sleep =
    options.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const now = options.now ?? (() => Date.now());
  const expiredListeners = new Set<() => void>();
  let pausedUntil = 0;

  async function send(
    method: "GET" | "POST",
    target: string,
    init: { body?: string; headers: Record<string, string>; signal?: AbortSignal | undefined },
    timeoutMs: number,
  ): Promise<Response> {
    const timeout = new AbortController();
    const timer = setTimeout(() => {
      timeout.abort();
    }, timeoutMs);
    const signal = init.signal ? AbortSignal.any([init.signal, timeout.signal]) : timeout.signal;
    try {
      return await fetchImpl(target, {
        method,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: init.headers,
        signal,
        ...(init.body === undefined ? {} : { body: init.body }),
      });
    } catch (error) {
      if (timeout.signal.aborted) throw clientError("TIMEOUT", "The request timed out");
      if (init.signal?.aborted) throw error;
      throw clientError("NETWORK_ERROR", "Cannot reach the server");
    } finally {
      clearTimeout(timer);
    }
  }

  function noteFailure(error: ApiError): ApiError {
    if (error.status === 429) {
      const seconds = error.retryAfterSeconds ?? 1;
      pausedUntil = Math.max(pausedUntil, now() + seconds * 1000);
    }
    if (error.status === 401 && error.code === "SESSION_EXPIRED") {
      for (const listener of expiredListeners) listener();
    }
    return error;
  }

  function rateLimitedLocally(): ApiError {
    return new ApiError({
      status: 429,
      code: "RATE_LIMITED",
      message: "Too many requests; waiting before trying again",
      retryAfterSeconds: Math.ceil((pausedUntil - now()) / 1000),
    });
  }

  return {
    async get<T>(path: string, requestOptions: RequestOptions = {}): Promise<T> {
      const target = url(path, requestOptions.query);
      for (let attempt = 0; ; attempt += 1) {
        if (pausedUntil > now()) throw rateLimitedLocally();
        let failure: ApiError;
        try {
          const response = await send(
            "GET",
            target,
            { headers: { Accept: "application/json" }, signal: requestOptions.signal },
            READ_TIMEOUT_MS,
          );
          if (response.ok) {
            try {
              return (await response.json()) as T;
            } catch {
              throw clientError("UNEXPECTED_RESPONSE", "The server returned an unexpected response");
            }
          }
          failure = noteFailure(await errorFrom(response));
        } catch (error) {
          if (!(error instanceof ApiError)) throw error;
          failure = error;
        }
        // Reads retry only on a network failure or 503, never after a 429 (section 6.1).
        const retryable = failure.code === "NETWORK_ERROR" || failure.status === 503;
        const delay = READ_RETRY_DELAYS_MS[attempt];
        if (!retryable || delay === undefined) throw failure;
        await sleep(delay);
      }
    },

    async post<T>(
      path: string,
      body: unknown,
      mutationOptions: MutationOptions = {},
    ): Promise<T | null> {
      const headers: Record<string, string> = {
        Accept: "application/json",
        "Content-Type": "application/json",
      };
      if (mutationOptions.csrfToken !== undefined) {
        headers["X-CSRF-Token"] = mutationOptions.csrfToken;
      }
      // Mutations are never retried automatically.
      const response = await send(
        "POST",
        url(path, undefined),
        { headers, body: JSON.stringify(body), signal: mutationOptions.signal },
        WRITE_TIMEOUT_MS,
      );
      if (!response.ok) throw noteFailure(await errorFrom(response));
      if (response.status === 204) return null;
      try {
        return (await response.json()) as T;
      } catch {
        throw clientError("UNEXPECTED_RESPONSE", "The server returned an unexpected response");
      }
    },

    onSessionExpired(listener: () => void): () => void {
      expiredListeners.add(listener);
      return () => {
        expiredListeners.delete(listener);
      };
    },

    pausedForMs(): number {
      return Math.max(0, pausedUntil - now());
    },
  };
}
