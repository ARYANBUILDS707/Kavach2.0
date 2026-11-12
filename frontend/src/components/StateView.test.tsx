import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError, clientError } from "../lib/api/errors";
import { LOADING, StateView, describeError, type StateKind } from "./StateView";

function error(status: number, code: string, retryAfterSeconds: number | null = null) {
  return new ApiError({
    status,
    code,
    message: "server text that must not be shown",
    requestId: "req-1",
    retryAfterSeconds,
  });
}

describe("describeError", () => {
  it.each<[ApiError, StateKind, string]>([
    [clientError("NETWORK_ERROR", "x"), "offline", "Can't reach the server"],
    [clientError("TIMEOUT", "x"), "offline", "Can't reach the server"],
    [error(429, "RATE_LIMITED", 12), "rateLimited", "Too many requests"],
    [error(503, "DEPENDENCY_UNAVAILABLE"), "unavailable", "Service temporarily unavailable"],
    [error(403, "CSRF_REJECTED"), "forbidden", "Request blocked for safety"],
    [error(403, "FORBIDDEN"), "forbidden", "You don't have access"],
    [error(404, "NOT_FOUND"), "notFound", "Not available"],
    [error(500, "INTERNAL_ERROR"), "error", "Something went wrong"],
  ])("maps %o to the %s state", (failure, kind, title) => {
    const state = describeError(failure);
    expect(state.kind).toBe(kind);
    expect(state.title).toBe(title);
    expect(state.message).not.toContain("server text");
  });

  it("shows the Retry-After countdown for 429", () => {
    expect(describeError(error(429, "RATE_LIMITED", 12)).message).toBe("Resuming in 12 seconds.");
  });

  it("treats a non-API error as a generic failure", () => {
    expect(describeError(new Error("boom")).kind).toBe("error");
  });
});

describe("StateView", () => {
  it("announces loading politely and marks the region busy", () => {
    render(<StateView state={LOADING} />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(region).toHaveTextContent("Loading…");
  });

  it("renders a failure as an alert with the copyable request ID and an action", () => {
    render(
      <StateView
        state={describeError(error(503, "DEPENDENCY_UNAVAILABLE"))}
        action={<button type="button">Try again</button>}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Service temporarily unavailable");
    expect(alert).toHaveTextContent("req-1");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
