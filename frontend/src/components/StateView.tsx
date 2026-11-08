// One component for every non-content state (FRONTEND_MVP1_PLAN.md section 9, DESIGN.md
// "State system"): loading, empty, error, unavailable, forbidden, not found, rate limited.
import type { ReactNode } from "react";

import { ApiError } from "../lib/api/errors";
import { CopyableId } from "./CopyableId";

export type StateKind =
  | "loading"
  | "empty"
  | "error"
  | "unavailable"
  | "forbidden"
  | "notFound"
  | "rateLimited"
  | "offline";

export interface StateDescription {
  kind: StateKind;
  title: string;
  message: string;
  requestId?: string | null;
}

/** The documented presentation for an API failure; server text is never shown verbatim. */
export function describeError(error: unknown): StateDescription {
  if (!(error instanceof ApiError)) {
    return {
      kind: "error",
      title: "Something went wrong",
      message: "An unexpected error occurred. Reload the page to try again.",
    };
  }
  const requestId = error.requestId;
  switch (true) {
    case error.code === "NETWORK_ERROR" || error.code === "TIMEOUT":
      return {
        kind: "offline",
        title: "Can't reach the server",
        message: "Check the connection and try again.",
      };
    case error.status === 429:
      return {
        kind: "rateLimited",
        title: "Too many requests",
        message:
          error.retryAfterSeconds !== null
            ? `Resuming in ${String(error.retryAfterSeconds)} seconds.`
            : "Wait a moment before trying again.",
        requestId,
      };
    case error.status === 503:
      return {
        kind: "unavailable",
        title: "Service temporarily unavailable",
        message: "A required service is not responding. Try again shortly.",
        requestId,
      };
    case error.code === "CSRF_REJECTED":
      return {
        kind: "forbidden",
        title: "Request blocked for safety",
        message: "Reload the page from the configured address and try again.",
        requestId,
      };
    case error.status === 403:
      return {
        kind: "forbidden",
        title: "You don't have access",
        message: "Your role does not allow this page.",
        requestId,
      };
    case error.status === 404:
      return {
        kind: "notFound",
        title: "Not available",
        message: "It does not exist or has expired.",
        requestId,
      };
    default:
      return {
        kind: "error",
        title: "Something went wrong",
        message: "The request could not be completed.",
        requestId,
      };
  }
}

export function StateView({
  state,
  action,
}: {
  state: StateDescription;
  action?: ReactNode;
}) {
  const isProblem = state.kind !== "loading" && state.kind !== "empty";
  return (
    <section
      className={`state-view${isProblem ? " state-view-error" : ""}`}
      role={state.kind === "loading" ? "status" : isProblem ? "alert" : undefined}
      aria-busy={state.kind === "loading" || undefined}
      data-state={state.kind}
    >
      <h2>{state.title}</h2>
      <p>{state.message}</p>
      {state.requestId ? <CopyableId label="Request ID" value={state.requestId} /> : null}
      {action ? <div>{action}</div> : null}
    </section>
  );
}

export const LOADING: StateDescription = {
  kind: "loading",
  title: "Loading…",
  message: "Fetching the latest information.",
};
