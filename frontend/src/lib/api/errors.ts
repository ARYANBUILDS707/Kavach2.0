// One error type for every failed API call. `message` is the server's safe message; the UI
// decides what to show from `code` (FRONTEND_MVP1_PLAN.md section 9).

/** Codes produced on the client when the server gave no documented envelope. */
export type ClientErrorCode = "NETWORK_ERROR" | "TIMEOUT" | "UNEXPECTED_RESPONSE";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryAfterSeconds: number | null;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    requestId?: string | null;
    retryAfterSeconds?: number | null;
  }) {
    super(options.message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function clientError(code: ClientErrorCode, message: string): ApiError {
  return new ApiError({ status: 0, code, message });
}
