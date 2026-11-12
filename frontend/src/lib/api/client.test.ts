import { describe, expect, it, vi } from "vitest";

import { SESSION, apiError, fakeFetch, json } from "../../test/fakeFetch";
import { WRITE_TIMEOUT_MS, createClient } from "./client";
import { ApiError } from "./errors";

function setup(...script: Parameters<typeof fakeFetch>) {
  const fake = fakeFetch(...script);
  const sleeps: number[] = [];
  let clock = 1_000_000;
  const client = createClient({
    fetch: fake.fetch,
    sleep: (ms) => {
      sleeps.push(ms);
      return Promise.resolve();
    },
    now: () => clock,
  });
  return {
    client,
    requests: fake.requests,
    sleeps,
    advance: (ms: number) => {
      clock += ms;
    },
  };
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected the request to fail");
}

describe("API client", () => {
  it("uses same-origin relative URLs, the cookie only, and never an Authorization header", async () => {
    const { client, requests } = setup(() => json(200, SESSION));
    await client.get("/api/v1/auth/session", { query: { limit: 25, cursor: undefined } });
    const [request] = requests;
    expect(request?.url).toBe("/api/v1/auth/session?limit=25");
    expect(request?.credentials).toBe("same-origin");
    expect(request?.headers.authorization).toBeUndefined();
    expect(request?.headers["x-csrf-token"]).toBeUndefined();
  });

  it("refuses absolute or non-API URLs", async () => {
    const { client, requests } = setup(() => json(200, {}));
    await expect(client.get("https://evil.test/api/v1/x")).rejects.toThrow(/relative/);
    await expect(client.get("//evil.test/api/v1/x")).rejects.toThrow(/relative/);
    expect(requests).toHaveLength(0);
  });

  it("sends the CSRF token on mutations only and returns null for 204", async () => {
    const { client, requests } = setup(() => new Response(null, { status: 204 }));
    await expect(client.post("/api/v1/auth/logout", {}, { csrfToken: "t" })).resolves.toBeNull();
    expect(requests[0]?.headers["x-csrf-token"]).toBe("t");
    expect(requests[0]?.headers["content-type"]).toBe("application/json");
  });

  it("parses the error envelope with code, request ID and Retry-After", async () => {
    const { client } = setup(() => apiError(409, "EVENT_ID_CONFLICT", { "Retry-After": "7" }));
    const error = await failure(client.post("/api/v1/events/sms", {}));
    expect(error.status).toBe(409);
    expect(error.code).toBe("EVENT_ID_CONFLICT");
    expect(error.requestId).toBe("req-00000000");
    expect(error.retryAfterSeconds).toBe(7);
  });

  it("reports a non-envelope error body as UNEXPECTED_RESPONSE with the header request ID", async () => {
    const { client } = setup(
      () => new Response("<html>bad gateway</html>", { status: 502, headers: { "X-Request-ID": "h-1" } }),
    );
    const error = await failure(client.get("/api/v1/auth/session"));
    expect(error.code).toBe("UNEXPECTED_RESPONSE");
    expect(error.requestId).toBe("h-1");
    expect(error.message).not.toContain("bad gateway");
  });

  it("retries a read at most twice on 503, with backoff, then fails", async () => {
    const { client, requests, sleeps } = setup(() => apiError(503, "DEPENDENCY_UNAVAILABLE"));
    const error = await failure(client.get("/api/v1/auth/session"));
    expect(error.status).toBe(503);
    expect(requests).toHaveLength(3);
    expect(sleeps).toEqual([1000, 3000]);
  });

  it("retries a read after a network failure and succeeds", async () => {
    const { client, requests } = setup(
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => json(200, SESSION),
    );
    await expect(client.get("/api/v1/auth/session")).resolves.toEqual(SESSION);
    expect(requests).toHaveLength(2);
  });

  it("never retries a mutation", async () => {
    const { client, requests } = setup(() => apiError(503, "DEPENDENCY_UNAVAILABLE"));
    await failure(client.post("/api/v1/auth/login", { username: "u", password: "p" }));
    expect(requests).toHaveLength(1);
  });

  it("after a 429 it does not retry and pauses every read until Retry-After has passed", async () => {
    const { client, requests, advance } = setup(
      () => apiError(429, "RATE_LIMITED", { "Retry-After": "5" }),
      () => json(200, SESSION),
    );
    const first = await failure(client.get("/api/v1/auth/session"));
    expect(first.code).toBe("RATE_LIMITED");
    expect(requests).toHaveLength(1);
    expect(client.pausedForMs()).toBe(5000);
    const paused = await failure(client.get("/api/v1/system/models"));
    expect(paused.status).toBe(429);
    expect(requests).toHaveLength(1); // nothing was sent while paused
    advance(5000);
    await expect(client.get("/api/v1/auth/session")).resolves.toEqual(SESSION);
  });

  it("notifies the session listener on 401 SESSION_EXPIRED only", async () => {
    const { client } = setup(
      () => apiError(401, "SESSION_EXPIRED"),
      () => apiError(401, "INVALID_CREDENTIALS"),
    );
    let expired = 0;
    const unsubscribe = client.onSessionExpired(() => {
      expired += 1;
    });
    await failure(client.get("/api/v1/auth/session"));
    await failure(client.post("/api/v1/auth/login", {}));
    expect(expired).toBe(1);
    unsubscribe();
  });

  it("aborts a hung request at the timeout and reports TIMEOUT, never success", async () => {
    vi.useFakeTimers();
    try {
      const hung: typeof fetch = (_input, init) =>
        new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        });
      const client = createClient({ fetch: hung, sleep: () => Promise.resolve() });
      const pending = failure(client.post("/api/v1/auth/login", {}));
      await vi.advanceTimersByTimeAsync(WRITE_TIMEOUT_MS);
      expect((await pending).code).toBe("TIMEOUT");
    } finally {
      vi.useRealTimers();
    }
  });
});
