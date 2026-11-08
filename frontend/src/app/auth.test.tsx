// Sign-in, session restore, expiry and sign-out through the real router and providers.
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createClient } from "../lib/api/client";
import { SESSION, apiError, fakeFetch, json } from "../test/fakeFetch";
import { renderApp } from "../test/renderApp";
import { ApiProvider } from "./ApiContext";
import { RequireRole } from "./guards";
import { SessionProvider } from "./SessionProvider";

const unauthenticated = () => apiError(401, "SESSION_EXPIRED");

async function signIn(username = "analyst.one", password = "correct horse") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(/Username/), username);
  await user.type(screen.getByLabelText(/Password/), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return user;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("session restore on load", () => {
  it("restores an existing session from GET /auth/session", async () => {
    const { requests } = renderApp("/", [() => json(200, SESSION)]);
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
    expect(screen.getByText(/Test Admin · Admin/)).toBeInTheDocument();
    expect(screen.getByText("Controlled demonstration")).toBeInTheDocument();
    expect(requests.map((r) => r.url)).toEqual(["/api/v1/auth/session"]);
  });

  it("sends a signed-out visitor to the login page", async () => {
    renderApp("/", [unauthenticated]);
    expect(await screen.findByRole("heading", { name: "Sign in to KAVACH" })).toBeInTheDocument();
  });

  it("never schedules an expiry beyond the browser timer limit (the server still enforces it)", async () => {
    renderApp("/", [() => json(200, SESSION)], () => Date.parse("2026-01-01T00:00:00Z"));
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.getByRole("heading", { name: "Signed in" })).toBeInTheDocument();
  });

  it("shows an unavailable state with a retry when the session check fails (503)", async () => {
    const user = userEvent.setup();
    renderApp("/", [
      () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
      () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
      () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
      () => json(200, SESSION),
    ]);
    expect(await screen.findByText("Service temporarily unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
  });
});

describe("sign in", () => {
  it("signs in, sends only the credentials, and clears the password", async () => {
    const { requests } = renderApp("/", [unauthenticated, () => json(200, SESSION)]);
    await signIn();
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
    const loginRequest = requests[1];
    expect(loginRequest?.method).toBe("POST");
    expect(JSON.parse(loginRequest?.body ?? "{}")).toEqual({
      username: "analyst.one",
      password: "correct horse",
    });
    expect(loginRequest?.headers.authorization).toBeUndefined();
  });

  it("returns to the requested page after sign-in", async () => {
    renderApp("/login?next=%2F", [unauthenticated, () => json(200, SESSION)]);
    await signIn();
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
  });

  it("shows one generic message for wrong credentials and clears the password", async () => {
    renderApp("/login", [unauthenticated, () => apiError(401, "INVALID_CREDENTIALS")]);
    await signIn();
    expect(await screen.findByText(/Username or password is incorrect\./)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/)).toHaveValue("");
    expect(screen.getByLabelText(/Username/)).toHaveValue("analyst.one");
  });

  it("disables sign-in for the Retry-After period after 429", async () => {
    renderApp("/login", [
      unauthenticated,
      () => apiError(429, "RATE_LIMITED", { "Retry-After": "30" }),
    ]);
    await signIn();
    expect(await screen.findByText(/Too many sign-in attempts\./)).toBeInTheDocument();
    expect(screen.getByText(/try again in 30 seconds/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });

  it.each([
    [503, "DEPENDENCY_UNAVAILABLE", /Sign-in is temporarily unavailable/],
    [403, "CSRF_REJECTED", /must be opened from the configured address/],
  ])("explains a %s %s without exposing server text", async (status, code, text) => {
    renderApp("/login", [unauthenticated, () => apiError(status, code)]);
    await signIn();
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByText(/safe server message/)).toBeNull();
    expect(screen.getByText("req-00000000")).toBeInTheDocument();
  });
});

describe("expiry and sign-out", () => {
  it("ends the session on any 401 SESSION_EXPIRED and returns to login with a notice", async () => {
    const { client } = renderApp("/", [() => json(200, SESSION), unauthenticated]);
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
    await act(async () => {
      await client.get("/api/v1/system/models").catch(() => undefined);
    });
    expect(await screen.findByText(/Your session ended/)).toBeInTheDocument();
    expect(screen.queryByText(/Test Admin/)).toBeNull();
  });

  it("warns five minutes before the deadline and signs out at it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const deadline = Date.parse(SESSION.data.expires_at);
    renderApp("/", [() => json(200, SESSION)], () => deadline - 6 * 60 * 1000);
    expect(await screen.findByRole("heading", { name: "Signed in" })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61 * 1000);
    });
    expect(screen.getByText(/less than five minutes/)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    });
    expect(await screen.findByText(/Your session ended/)).toBeInTheDocument();
  });

  it("signs out with the CSRF token and clears the session", async () => {
    const user = userEvent.setup();
    const { requests } = renderApp("/", [
      () => json(200, SESSION),
      () => new Response(null, { status: 204 }),
    ]);
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("You have signed out.")).toBeInTheDocument();
    const logout = requests[1];
    expect(logout?.url).toBe("/api/v1/auth/logout");
    expect(logout?.headers["x-csrf-token"]).toBe("csrf-test-token");
  });

  it("keeps the session and warns when sign-out cannot be confirmed (503)", async () => {
    const user = userEvent.setup();
    renderApp("/", [() => json(200, SESSION), () => apiError(503, "DEPENDENCY_UNAVAILABLE")]);
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByText(/session may still be active/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Signed in" })).toBeInTheDocument();
  });
});

describe("guards and privacy", () => {
  it("RequireRole shows the forbidden state for a role that is not allowed", async () => {
    const viewer = { ...SESSION, data: { ...SESSION.data, user: { ...SESSION.data.user, role: "viewer" } } };
    const fake = fakeFetch(() => json(200, viewer));
    render(
      <ApiProvider client={createClient({ fetch: fake.fetch })}>
        <SessionProvider>
          <RequireRole roles={["admin"]}>
            <p>admin content</p>
          </RequireRole>
        </SessionProvider>
      </ApiProvider>,
    );
    await waitFor(() => {
      expect(fake.requests).toHaveLength(1);
    });
    expect(await screen.findByText("You don't have access")).toBeInTheDocument();
    expect(screen.queryByText("admin content")).toBeNull();
  });

  it("stores nothing in browser storage or cookies through a full sign-in and sign-out", async () => {
    const user = userEvent.setup();
    renderApp("/", [unauthenticated, () => json(200, SESSION), () => new Response(null, { status: 204 })]);
    await signIn();
    await screen.findByRole("heading", { name: "Signed in" });
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await screen.findByText("You have signed out.");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("renders the not-found page for unknown routes without calling more than the session", async () => {
    const { requests } = renderApp("/does-not-exist", [unauthenticated]);
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(requests.length).toBeLessThanOrEqual(1);
  });
});
