// Overview, System page, navigation and the read budget, through the real app.
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MODEL_POLL_MS } from "../app/ModelStatusProvider";
import { SESSION, apiError, json } from "../test/fakeFetch";
import { models, page, summary } from "../test/fixtures";
import { renderApp } from "../test/renderApp";

const signedIn = [() => json(200, SESSION)];

afterEach(() => {
  vi.useRealTimers();
});

describe("system status", () => {
  it.each([
    ["ready", "Ready", /says nothing about accuracy/],
    ["starting", "Starting", /refused until it is ready/],
    ["disabled", "Disabled", /not enabled on this deployment/],
    ["unavailable", "Unavailable", /cannot serve requests/],
  ] as const)("explains the %s state", async (state, label, explanation) => {
    renderApp("/admin/system", signedIn, undefined, {
      "/api/v1/system/models": () => json(200, models(state)),
    });
    const card = await screen.findByRole("region", { name: "SMS model" });
    expect(await within(card).findByText(label)).toBeInTheDocument();
    expect(within(card).getByText(explanation)).toBeInTheDocument();
    expect(within(card).getByText("No: not validated on KAVACH data")).toBeInTheDocument();
    expect(within(card).getByText(/not probabilities/)).toBeInTheDocument();
  });

  it("shows the failure reason of an unavailable worker", async () => {
    renderApp("/admin/system", signedIn, undefined, {
      "/api/v1/system/models": () => json(200, models("unavailable")),
    });
    expect(await screen.findByText("Model worker stopped")).toBeInTheDocument();
    expect(screen.getByText("circuit_open")).toBeInTheDocument();
  });

  it("shows a retryable error when the status cannot be read", async () => {
    const user = userEvent.setup();
    renderApp("/admin/system", signedIn, undefined, {
      "/api/v1/system/models": [
        () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
        () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
        () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
        () => json(200, models("ready")),
      ],
    });
    const card = await screen.findByRole("region", { name: "SMS model" });
    expect(await within(card).findByText("Service temporarily unavailable")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Check again" }));
    expect(await within(card).findByText("Ready")).toBeInTheDocument();
  });
});

describe("overview", () => {
  it("summarises only the loaded records, labelled as such, from one request", async () => {
    const items = [
      summary(1, { analysis_status: "complete" }),
      summary(2, { analysis_status: "partial" }),
      summary(3),
    ];
    const { callsTo } = renderApp("/admin", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page(items, "more")),
      "/api/v1/system/models": () => json(200, models("ready")),
    });
    const summaryRegion = await screen.findByRole("region", { name: "Recent SMS records at a glance" });
    expect(within(summaryRegion).getByText(/3 most recent SMS incident records \(more exist\)/)).toBeInTheDocument();
    expect(within(summaryRegion).getByText(/record counts, not unique attacks/)).toBeInTheDocument();
    const values = within(summaryRegion)
      .getAllByRole("listitem")
      .map((card) => card.textContent);
    expect(values).toEqual([
      "3records in this window",
      "1with completed model analysis",
      "1with partial analysis",
      "1with analysis unavailable",
      "3with risk tier unknown (no calibrated signal)",
    ]);
    expect(await screen.findByRole("table", { name: "Most recent SMS incidents" })).toBeInTheDocument();
    expect(callsTo("/api/v1/incidents")).toHaveLength(1);
    expect(callsTo("/api/v1/incidents")[0]?.url).toBe("/api/v1/incidents?channel=sms&limit=25");
  });

  it("shows at most ten recent rows", async () => {
    renderApp("/admin", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page(Array.from({ length: 25 }, (_, i) => summary(i + 1)))),
    });
    const table = await screen.findByRole("table", { name: "Most recent SMS incidents" });
    expect(within(table).getAllByRole("link", { name: /Open incident/ })).toHaveLength(10);
  });

  it("shows the empty state and the model card when nothing is retained", async () => {
    renderApp("/admin", signedIn);
    expect(await screen.findByText("No SMS incidents in the last 7 days")).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "SMS model readiness" });
    expect(await within(card).findByText("Disabled")).toBeInTheDocument();
    expect(within(card).getByText(/Outputs are uncalibrated/)).toBeInTheDocument();
  });

  it("shows an unavailable state when incidents cannot be read", async () => {
    renderApp("/admin", signedIn, undefined, {
      "/api/v1/incidents": () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
    });
    expect(await screen.findByText("Service temporarily unavailable")).toBeInTheDocument();
  });
});

describe("navigation and read budget", () => {
  it("lists only the pages the user may open and marks the current one", async () => {
    // SESSION is an admin, so the admin-only "Analyze SMS" page is listed (MVP-F3).
    renderApp("/admin/system", signedIn);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link").map((link) => link.textContent);
    expect(links).toEqual(["Overview", "Incidents", "System", "Analyze SMS"]);
    expect(within(nav).getByRole("link", { name: "System" })).toHaveAttribute("aria-current", "page");
  });

  it("shares one model-status request between the header and the page", async () => {
    const { callsTo } = renderApp("/admin/system", signedIn, undefined, {
      "/api/v1/system/models": () => json(200, models("ready")),
    });
    await screen.findByText(/SMS model: Ready/);
    expect(callsTo("/api/v1/system/models")).toHaveLength(1);
  });

  it("polls model status every 30 s only while visible, and never during a 429 pause", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    const { callsTo } = renderApp("/admin", signedIn, undefined, {
      "/api/v1/system/models": [
        () => json(200, models("ready")),
        () => json(200, models("ready")),
        () => apiError(429, "RATE_LIMITED", { "Retry-After": "120" }),
        () => json(200, models("ready")),
      ],
    });
    await screen.findByText(/SMS model: Ready/);
    expect(callsTo("/api/v1/system/models")).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MODEL_POLL_MS);
    });
    expect(callsTo("/api/v1/system/models")).toHaveLength(2);
    visibility = "hidden";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MODEL_POLL_MS * 3);
    });
    expect(callsTo("/api/v1/system/models")).toHaveLength(2);
    visibility = "visible";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MODEL_POLL_MS);
    });
    expect(callsTo("/api/v1/system/models")).toHaveLength(3); // this one is the 429
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MODEL_POLL_MS * 2);
    });
    // Still inside the 120 s Retry-After: nothing more was sent.
    expect(callsTo("/api/v1/system/models")).toHaveLength(3);
  });

  it("reads each incident list only once per visit, with no background polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { callsTo } = renderApp("/admin/incidents", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(1)])),
    });
    await screen.findByRole("table");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    });
    expect(callsTo("/api/v1/incidents")).toHaveLength(1);
  });

  it("keeps browser storage empty and puts only filter values in the URL", async () => {
    const user = userEvent.setup();
    renderApp("/admin/incidents", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(1)])),
    });
    await screen.findByRole("table");
    await user.click(screen.getByRole("link", { name: "Overview" }));
    await screen.findByRole("heading", { name: "Overview" });
    await waitFor(() => {
      expect(window.localStorage.length).toBe(0);
    });
    expect(window.sessionStorage.length).toBe(0);
  });
});
