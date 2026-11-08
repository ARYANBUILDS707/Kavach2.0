// Incident history and detail through the real router, providers and API client.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { SESSION, apiError, json } from "../../test/fakeFetch";
import {
  CALL_EVENT,
  INCIDENT_ID,
  UNAVAILABLE_SMS_EVENT,
  detail,
  page,
  summary,
} from "../../test/fixtures";
import { renderApp } from "../../test/renderApp";

const signedIn = [() => json(200, SESSION)];

function queryOf(url: string): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(url.split("?")[1] ?? ""));
}

describe("incident history", () => {
  it("loads SMS incidents newest first with the documented query", async () => {
    const { callsTo } = renderApp("/incidents", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(2), summary(1)])),
    });
    const table = await screen.findByRole("table", { name: "Incident records" });
    expect(within(table).getAllByRole("link", { name: /Open incident/ })).toHaveLength(2);
    expect(within(table).getAllByText("Risk tier: Unknown (no calibrated signal)")).toHaveLength(2);
    expect(within(table).getAllByText("Not available")).toHaveLength(2);
    const [first] = callsTo("/api/v1/incidents");
    expect(queryOf(first?.url ?? "")).toEqual({ limit: "25", channel: "sms" });
  });

  it("applies kind, tier, channel and date filters through the URL and the API query", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/incidents", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(1)])),
    });
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Kind"), "standalone");
    await user.selectOptions(screen.getByLabelText("Risk tier"), "unknown");
    await user.selectOptions(screen.getByLabelText("Channel"), "all");
    await user.type(screen.getByLabelText("Event time from"), "2031-01-01T00:00");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => {
      expect(callsTo("/api/v1/incidents")).toHaveLength(2);
    });
    const query = queryOf(callsTo("/api/v1/incidents")[1]?.url ?? "");
    expect(query.kind).toBe("standalone");
    expect(query.tier).toBe("unknown");
    expect(query.channel).toBeUndefined();
    expect(query.from).toMatch(/Z$/);
    expect(query.review_status).toBeUndefined();
  });

  it("refuses a start after the end without calling the API", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/incidents", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(1)])),
    });
    await screen.findByRole("table");
    await user.type(screen.getByLabelText("Event time from"), "2031-01-02T00:00");
    await user.type(screen.getByLabelText("Event time before"), "2031-01-01T00:00");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(await screen.findByText("The start must be before the end.")).toBeInTheDocument();
    expect(callsTo("/api/v1/incidents")).toHaveLength(1);
  });

  it("drops malformed filter values from the URL instead of sending them", async () => {
    const { callsTo } = renderApp("/incidents?tier=severe&from=yesterday&review_status=x", signedIn);
    await screen.findByText("No SMS incidents in the last 7 days");
    expect(queryOf(callsTo("/api/v1/incidents")[0]?.url ?? "")).toEqual({ limit: "25", channel: "sms" });
  });

  it("pages with the server cursor and appends the next page", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/incidents", signedIn, undefined, {
      "/api/v1/incidents": [
        () => json(200, page([summary(3), summary(2)], "cursor-1")),
        () => json(200, page([summary(1)])),
      ],
    });
    await screen.findByRole("table");
    expect(screen.getByText(/2 incident records loaded; more are available/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText(/3 incident records loaded\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(queryOf(callsTo("/api/v1/incidents")[1]?.url ?? "").cursor).toBe("cursor-1");
  });

  it("offers a restart when the cursor is rejected (400 INVALID_CURSOR)", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/incidents", signedIn, undefined, {
      "/api/v1/incidents": [
        () => json(200, page([summary(2)], "cursor-1")),
        () => apiError(400, "INVALID_CURSOR"),
        () => json(200, page([summary(5)])),
      ],
    });
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText(/The list changed while you were paging/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reload from the start" }));
    await waitFor(() => {
      expect(callsTo("/api/v1/incidents")).toHaveLength(3);
    });
    expect(queryOf(callsTo("/api/v1/incidents")[2]?.url ?? "").cursor).toBeUndefined();
  });

  it("explains an empty list differently with and without filters", async () => {
    renderApp("/incidents", signedIn);
    expect(await screen.findByText("No SMS incidents in the last 7 days")).toBeInTheDocument();
  });

  it("keeps filters and offers to clear them when nothing matches", async () => {
    renderApp("/incidents?tier=high", signedIn);
    expect(await screen.findByText("No incidents match these filters")).toBeInTheDocument();
    expect(screen.getByLabelText("Risk tier")).toHaveValue("high");
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("shows unavailable, rate-limited and forbidden states with the request ID", async () => {
    for (const [status, code, title] of [
      [503, "DEPENDENCY_UNAVAILABLE", "Service temporarily unavailable"],
      [429, "RATE_LIMITED", "Too many requests"],
      [403, "FORBIDDEN", "You don't have access"],
    ] as const) {
      const view = renderApp("/incidents", signedIn, undefined, {
        "/api/v1/incidents": () => apiError(status, code, { "Retry-After": "5" }),
      });
      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(screen.getByText("req-00000000")).toBeInTheDocument();
      view.unmount();
    }
  });

  it("keeps the last records marked stale when a refresh fails", async () => {
    const user = userEvent.setup();
    renderApp("/incidents", signedIn, undefined, {
      "/api/v1/incidents": [
        () => json(200, page([summary(1)])),
        () => apiError(500, "INTERNAL_ERROR"),
      ],
    });
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(/Couldn't refresh/)).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});

describe("incident detail", () => {
  const path = `/api/v1/incidents/${INCIDENT_ID}`;

  it("shows events, native uncalibrated output, the unknown tier and null scores honestly", async () => {
    const { container } = renderApp(`/incidents/${INCIDENT_ID}`, signedIn, undefined, {
      [path]: () => json(200, { data: detail(), request_id: "req-detail" }),
    });
    expect(await screen.findByRole("heading", { name: "Incident 11111111" })).toBeInTheDocument();
    expect(screen.getByText(/Message text is not retained/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Model output (uncalibrated)" })).toBeInTheDocument();
    expect(screen.getByText("0.8199")).toBeInTheDocument();
    expect(screen.getAllByText(/horizon-phishing-scam-base@test/).length).toBeGreaterThan(0);
    expect(screen.getByText("SMS model output is uncalibrated")).toBeInTheDocument();
    expect(screen.getAllByText("Risk tier: Unknown (no calibrated signal)").length).toBeGreaterThan(0);
    expect(screen.getByText(/This is not a judgement that the message is safe/)).toBeInTheDocument();
    const assessment = screen.getByRole("region", { name: /Assessment/ });
    expect(within(assessment).getAllByText("Not available")).toHaveLength(3);
    expect(screen.getByText(/Cross-channel correlation is not part of this release/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
    expect(screen.queryByText(/review/i)).toBeNull();
  });

  it("shows unavailable SMS and call stages with their reasons", async () => {
    renderApp(`/incidents/${INCIDENT_ID}`, signedIn, undefined, {
      [path]: () =>
        json(200, { data: detail({ events: [UNAVAILABLE_SMS_EVENT, CALL_EVENT] }), request_id: "r" }),
    });
    expect(await screen.findByText("Model not enabled")).toBeInTheDocument();
    expect(screen.getAllByText("No audio provided")).toHaveLength(3);
    expect(screen.queryByRole("heading", { name: "Model output (uncalibrated)" })).toBeNull();
  });

  it("treats 404 as unavailable or expired and keeps the list filters on the back link", async () => {
    renderApp(`/incidents/${INCIDENT_ID}`, signedIn, undefined, {
      [path]: () => apiError(404, "NOT_FOUND"),
    });
    expect(await screen.findByText("Incident unavailable or expired")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Back to incident history" })[0]).toHaveAttribute(
      "href",
      "/incidents",
    );
  });

  it("never sends a malformed ID to the server", async () => {
    const { callsTo, requests } = renderApp("/incidents/not-a-uuid", signedIn);
    expect(await screen.findByText("Incident unavailable or expired")).toBeInTheDocument();
    expect(requests.some((r) => r.url.startsWith("/api/v1/incidents/"))).toBe(false);
    expect(callsTo("/api/v1/incidents")).toHaveLength(0);
  });

  it("shows a retryable error for 503", async () => {
    const user = userEvent.setup();
    renderApp(`/incidents/${INCIDENT_ID}`, signedIn, undefined, {
      [path]: [
        () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
        () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
        () => apiError(503, "DEPENDENCY_UNAVAILABLE"),
        () => json(200, { data: detail(), request_id: "r" }),
      ],
    });
    expect(await screen.findByText("Service temporarily unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Incident 11111111" })).toBeInTheDocument();
  });

  it("opens from the list with a back link that restores the filters", async () => {
    const user = userEvent.setup();
    renderApp("/incidents?tier=unknown", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(1, { id: INCIDENT_ID })])),
      [path]: () => json(200, { data: detail(), request_id: "r" }),
    });
    await user.click(await screen.findByRole("link", { name: /Open incident/ }));
    await screen.findByRole("heading", { name: "Incident 11111111" });
    expect(screen.getByRole("link", { name: "Back to incident history" })).toHaveAttribute(
      "href",
      "/incidents?tier=unknown",
    );
  });
});
