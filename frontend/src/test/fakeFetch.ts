// TEST ONLY: a scripted fetch that records every request. Responses use the documented
// envelopes; nothing here is reachable from runtime code (lint rule and bundle scan).
export interface RecordedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | null;
  credentials: RequestCredentials | undefined;
}

export type Scripted = (request: RecordedRequest) => Response | Promise<Response>;

export function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function apiError(
  status: number,
  code: string,
  headers: Record<string, string> = {},
): Response {
  return json(
    status,
    { error: { code, message: "safe server message" }, request_id: "req-00000000" },
    headers,
  );
}

export const SESSION = {
  data: {
    user: { id: "00000000-0000-4000-8000-000000000001", display_name: "Test Admin", role: "admin" },
    expires_at: "2031-01-01T20:00:00Z",
    csrf_token: "csrf-test-token",
  },
  request_id: "req-session",
} as const;

/** Dispatches by path (without query). Each path takes its scripted responses in order and
 * repeats the last one; an unscripted path fails the test loudly. */
export function router(routes: Record<string, Scripted | Scripted[]>): Scripted {
  const calls = new Map<string, number>();
  return (request) => {
    const path = request.url.split("?")[0] ?? request.url;
    const route = routes[path];
    if (route === undefined) throw new Error(`fakeFetch: unscripted path ${path}`);
    const steps = Array.isArray(route) ? route : [route];
    const index = calls.get(path) ?? 0;
    calls.set(path, index + 1);
    const step = steps[Math.min(index, steps.length - 1)];
    if (step === undefined) throw new Error(`fakeFetch: no response for ${path}`);
    return step(request);
  };
}

export const MODELS_DISABLED = {
  data: {
    sms_classifier: {
      state: "disabled",
      detail: "disabled",
      reason: null,
      model_version: null,
      score_semantics: "uncalibrated_softmax",
      validated_on_kavach_data: false,
    },
  },
  request_id: "req-models",
} as const;

export const EMPTY_PAGE = {
  data: [],
  page: { next_cursor: null, has_more: false },
  request_id: "req-list",
} as const;

export function fakeFetch(...script: Scripted[]) {
  const requests: RecordedRequest[] = [];
  let index = 0;
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, name) => {
      headers[name] = value;
    });
    const request: RecordedRequest = {
      url: typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
      method: init?.method ?? "GET",
      headers,
      body: typeof init?.body === "string" ? init.body : null,
      credentials: init?.credentials,
    };
    requests.push(request);
    const step = script[Math.min(index, script.length - 1)];
    index += 1;
    if (step === undefined) throw new Error("fakeFetch: no scripted response");
    if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
    return step(request);
  };
  return { fetch: fetchImpl, requests };
}
