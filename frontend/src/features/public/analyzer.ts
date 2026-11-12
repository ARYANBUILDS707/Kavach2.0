/** Public transport never sends session cookies, persists text or retries a submission. */
export interface AnalyzerStatus { enabled: boolean; max_chars: number }
export interface Prediction {
  prediction: "fraud" | "spam" | "legitimate";
  experimental: true;
  truncated: boolean;
  model_ms: number;
  total_ms: number;
}
export class AnalyzerLimitError extends Error {
  constructor(readonly retryAfterSeconds: number) {
    super(`Analyzer is busy or its limit was reached. Try again after ${String(retryAfterSeconds)} seconds.`);
  }
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
export async function analyzerRequest(body?: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/v1/public/${body === undefined ? "analyzer" : "analyze"}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "omit", cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json", "X-Kavach-Analyzer": "1" },
    ...(body === undefined ? {} : { body }),
    ...(signal === undefined ? {} : { signal }),
  });
  if (!response.ok) {
    if (response.status === 429) {
      const seconds = Number(response.headers.get("Retry-After"));
      throw new AnalyzerLimitError(Number.isFinite(seconds) && seconds > 0 && seconds <= 60
        ? Math.ceil(seconds) : 60);
    }
    if (response.status === 403) throw new Error("Analysis is forbidden from this origin.");
    if (response.status === 422 || response.status === 413) throw new Error("Check the message length and try again.");
    throw new Error("Analysis is unavailable or timed out. No prediction was returned.");
  }
  const value: unknown = await response.json();
  if (!record(value) || !record(value.data)) throw new Error("Invalid analyzer response.");
  return value.data;
}
export function parseStatus(value: unknown): AnalyzerStatus {
  if (!record(value) || typeof value.enabled !== "boolean" || typeof value.max_chars !== "number"
      || !Number.isInteger(value.max_chars) || value.max_chars < 1 || value.max_chars > 4096) {
    throw new Error("Analyzer status unavailable.");
  }
  return { enabled: value.enabled, max_chars: value.max_chars };
}
export function parsePrediction(value: unknown): Prediction {
  if (!record(value)
      || value.experimental !== true || typeof value.truncated !== "boolean"
      || typeof value.model_ms !== "number" || !Number.isFinite(value.model_ms) || value.model_ms < 0
      || typeof value.total_ms !== "number" || !Number.isFinite(value.total_ms) || value.total_ms < 0) {
    throw new Error("Invalid analyzer result. No prediction available.");
  }
  // Explicit narrowing keeps untrusted JSON out of the rendered result.
  if (value.prediction !== "fraud" && value.prediction !== "spam" && value.prediction !== "legitimate") {
    throw new Error("Unknown prediction.");
  }
  return { prediction: value.prediction, experimental: true, truncated: value.truncated,
    model_ms: value.model_ms, total_ms: value.total_ms };
}
