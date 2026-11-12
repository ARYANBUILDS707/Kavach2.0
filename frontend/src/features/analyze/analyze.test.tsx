// Admin SMS analysis through the real router, providers and API client.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BROWSER_EVENT_ID, BROWSER_SUBSCRIBER_TOKEN } from "../../lib/ids";
import { SESSION, apiError, json, type RecordedRequest } from "../../test/fakeFetch";
import { UNAVAILABLE_SMS_EVENT, detail, models } from "../../test/fixtures";
import { renderApp } from "../../test/renderApp";
import { MAX_TEXT_CHARACTERS, characterCount, classifyFailure, validateText } from "./submission";

const TEXT = "FICTIONAL UNIT CANARY 9182: your parcel is held, pay the fee at the link";
const INCIDENT = "55555555-5555-4555-8555-555555555555";

function sessionAs(role: "viewer" | "analyst" | "admin") {
  return () =>
    json(200, { ...SESSION, data: { ...SESSION.data, user: { ...SESSION.data.user, role } } });
}

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      event_id: "66666666-6666-4666-8666-666666666666",
      external_event_id: "ui-00000000-0000-4000-8000-000000000000",
      source: "simulator",
      kind: "sms",
      analysis_status: "unavailable",
      received_at: "2031-01-01T12:00:00Z",
      processing_ms: 12,
      replayed: false,
      warnings: ["SMS_CLASSIFIER_UNAVAILABLE"],
      incident_ids: [INCIDENT],
      ...overrides,
    },
    request_id: "req-receipt",
  };
}

const unavailableDetail = () =>
  json(200, { data: detail({ id: INCIDENT, events: [UNAVAILABLE_SMS_EVENT] }), request_id: "r" });

function bodyOf(request: RecordedRequest | undefined): Record<string, unknown> {
  return JSON.parse(request?.body ?? "{}") as Record<string, unknown>;
}

async function typeAndSubmit(text = TEXT) {
  const user = userEvent.setup();
  const field = await screen.findByLabelText("Synthetic message text");
  await user.type(field, text);
  await user.click(screen.getByRole("button", { name: "Submit" }));
  return user;
}

let logged: string[] = [];
beforeEach(() => {
  logged = [];
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
      logged.push(args.map(String).join(" "));
    });
  }
});
afterEach(() => {
  expect(logged.filter((line) => line.includes("CANARY"))).toEqual([]);
});

describe("access", () => {
  it.each(["viewer", "analyst"] as const)("a %s gets the forbidden state and no form", async (role) => {
    const { callsTo } = renderApp("/analyze", [sessionAs(role)]);
    // The forbidden state replaces the whole page, so its title is the page's only h1.
    expect(await screen.findByRole("heading", { level: 1, name: "You don't have access" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByLabelText("Synthetic message text")).toBeNull();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Analyze SMS" })).toBeNull();
    expect(callsTo("/api/v1/events/sms")).toHaveLength(0);
  });

  it("an admin gets the form and the navigation item", async () => {
    renderApp("/analyze", [sessionAs("admin")]);
    expect(await screen.findByLabelText("Synthetic message text")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Analyze SMS" })).toHaveAttribute("aria-current", "page");
  });
});

describe("validation", () => {
  it("refuses blank text with an associated message and sends nothing", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")]);
    const field = await screen.findByLabelText("Synthetic message text");
    await user.type(field, "   ");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the synthetic message text.");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(callsTo("/api/v1/events/sms")).toHaveLength(0);
  });

  it("counts characters as code points and caps them at 4,096", () => {
    expect(characterCount("😀a")).toBe(2);
    expect(validateText("x".repeat(MAX_TEXT_CHARACTERS))).toBeNull();
    expect(validateText("x".repeat(MAX_TEXT_CHARACTERS + 1))).toMatch(/at most 4,096/);
    expect(validateText("😀".repeat(MAX_TEXT_CHARACTERS))).toBeNull();
  });
});

describe("submission", () => {
  it("sends exactly the contract body with the CSRF token, shows the receipt and clears the text", async () => {
    const { callsTo, container } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => json(201, receipt()),
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    expect(await screen.findByRole("heading", { name: "Message stored" })).toBeInTheDocument();
    // One label for the identifier, not "Submission ID" plus "Event ID:" for the same value.
    expect(screen.getAllByText("Event ID", { exact: true })).toHaveLength(1);
    expect(screen.queryByText(/Submission ID/)).toBeNull();
    const [request] = callsTo("/api/v1/events/sms");
    expect(request?.method).toBe("POST");
    expect(request?.headers["x-csrf-token"]).toBe("csrf-test-token");
    expect(request?.headers.authorization).toBeUndefined();
    const body = bodyOf(request);
    expect(Object.keys(body).sort()).toEqual(["event_id", "source", "subscriber_token", "text", "timestamp"]);
    expect(body.source).toBe("simulator");
    expect(body.text).toBe(TEXT);
    expect(String(body.event_id)).toMatch(BROWSER_EVENT_ID);
    expect(String(body.subscriber_token)).toMatch(BROWSER_SUBSCRIBER_TOKEN);
    expect(Number.isNaN(Date.parse(String(body.timestamp)))).toBe(false);
    // Text cleared from state; the receipt never shows it.
    expect(screen.getByLabelText("Synthetic message text")).toHaveValue("");
    expect(container.textContent).not.toContain("CANARY");
    // Incident navigation and the stored evidence read back from the server.
    expect(screen.getByRole("link", { name: /Open incident 55555555/ })).toHaveAttribute(
      "href",
      `/incidents/${INCIDENT}`,
    );
    expect(screen.getByText("SMS model unavailable: stored without a model result")).toBeInTheDocument();
    expect(await screen.findByText("Model not enabled")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Model prediction (experimental)" })).toBeNull();
  });

  it("shows native outputs only from stored evidence, labelled uncalibrated", async () => {
    renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/system/models": () => json(200, models("ready")),
      "/api/v1/events/sms": () =>
        json(201, receipt({ analysis_status: "complete", warnings: ["SMS_SCORE_UNCALIBRATED"] })),
      [`/api/v1/incidents/${INCIDENT}`]: () =>
        json(200, { data: detail({ id: INCIDENT }), request_id: "r" }),
    });
    await typeAndSubmit();
    expect(await screen.findByRole("heading", { name: "Model prediction (experimental)" })).toBeInTheDocument();
    // The stored top label, stated as the model's prediction rather than a fact.
    expect(screen.getByText(/The model predicts:/)).toHaveTextContent("The model predicts: Fraud");
    const panel = screen.getByRole("region", { name: "Model prediction (experimental)" });
    expect(within(panel).getByText(/not an established fact/)).toBeInTheDocument();
    expect(screen.getByText("0.8199")).toBeInTheDocument();
    expect(screen.getByText("Model output is uncalibrated")).toBeInTheDocument();
  });

  it("reports a replay as the original receipt", async () => {
    renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => json(200, receipt({ replayed: true })),
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    expect(
      await screen.findByRole("heading", { name: "Already stored: showing the original receipt" }),
    ).toBeInTheDocument();
  });

  it("prevents a second submission while one is in flight", async () => {
    let release: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => pending,
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    const user = await typeAndSubmit();
    const button = screen.getByRole("button", { name: "Submitting…" });
    expect(button).toBeDisabled();
    expect(screen.getByLabelText("Synthetic message text")).toHaveAttribute("readonly");
    await user.click(button);
    await user.click(button);
    expect(callsTo("/api/v1/events/sms")).toHaveLength(1);
    release(json(201, receipt()));
    expect(await screen.findByRole("heading", { name: "Message stored" })).toBeInTheDocument();
    expect(callsTo("/api/v1/events/sms")).toHaveLength(1);
  });
});

describe("same-frame double submit", () => {
  it("sends one request when two submits fire before React re-renders", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => json(201, receipt()),
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await user.type(await screen.findByLabelText("Synthetic message text"), TEXT);
    const form = screen.getByRole("form", { name: "Submit a synthetic SMS" });
    // Two submit events in the same tick: the button is not yet disabled for the second.
    fireEvent.submit(form);
    fireEvent.submit(form);
    await screen.findByRole("heading", { name: "Message stored" });
    expect(callsTo("/api/v1/events/sms")).toHaveLength(1);
  });
});

describe("failures", () => {
  it("after an uncertain outcome it locks the text and retries only the identical submission", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": [
        () => Promise.reject(new TypeError("Failed to fetch")),
        () => json(200, receipt({ replayed: true })),
      ],
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    expect(await screen.findByRole("heading", { name: "Outcome unknown" })).toBeInTheDocument();
    expect(screen.getByLabelText("Synthetic message text")).toHaveAttribute("readonly");
    // Never retried automatically.
    expect(callsTo("/api/v1/events/sms")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Retry the same submission" }));
    expect(await screen.findByRole("heading", { name: /Already stored/ })).toBeInTheDocument();
    const [first, second] = callsTo("/api/v1/events/sms");
    expect(second?.body).toBe(first?.body); // same event ID, token, timestamp and text
  });

  it("starts a new submission only when the admin explicitly discards the uncertain one", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": [() => apiError(500, "INTERNAL_ERROR"), () => json(201, receipt())],
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    await screen.findByRole("heading", { name: "Outcome unknown" });
    await user.click(screen.getByRole("button", { name: "Discard and start a new submission" }));
    expect(screen.getByLabelText("Synthetic message text")).not.toHaveAttribute("readonly");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("heading", { name: "Message stored" });
    const [first, second] = callsTo("/api/v1/events/sms");
    expect(bodyOf(second).event_id).not.toBe(bodyOf(first).event_id);
  });

  it.each([
    [403, "CSRF_REJECTED", "Request blocked for safety"],
    [403, "FORBIDDEN", "Not allowed"],
    [413, "PAYLOAD_TOO_LARGE", "Message too large"],
    [422, "VALIDATION_ERROR", "The server rejected the message"],
    [429, "RATE_LIMITED", "Too many submissions"],
    [429, "CAPACITY_EXCEEDED", "Analysis capacity is full"],
  ] as const)("a %s %s says nothing was stored and keeps the text editable", async (status, code, title) => {
    renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => apiError(status, code, { "Retry-After": "7" }),
    });
    await typeAndSubmit();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { name: title })).toBeInTheDocument();
    expect(alert).toHaveTextContent("Nothing was stored.");
    expect(alert).toHaveTextContent("req-00000000");
    expect(alert).not.toHaveTextContent("safe server message");
    expect(screen.getByLabelText("Synthetic message text")).toHaveValue(TEXT);
    expect(screen.getByLabelText("Synthetic message text")).not.toHaveAttribute("readonly");
  });

  it("reuses the same submission after a rate limit when the text is unchanged", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": [
        () => apiError(429, "CAPACITY_EXCEEDED", { "Retry-After": "1" }),
        () => json(201, receipt()),
      ],
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    await screen.findByRole("heading", { name: "Analysis capacity is full" });
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("heading", { name: "Message stored" });
    const [first, second] = callsTo("/api/v1/events/sms");
    expect(bodyOf(second).event_id).toBe(bodyOf(first).event_id);
  });

  it("treats a 503 (worker starting or database) as uncertain and never auto-retries", async () => {
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => apiError(503, "DEPENDENCY_UNAVAILABLE", { "Retry-After": "10" }),
    });
    await typeAndSubmit();
    expect(await screen.findByText(/Try again in 10 seconds/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry the same submission" })).toBeInTheDocument();
    expect(callsTo("/api/v1/events/sms")).toHaveLength(1);
  });

  it("a 409 conflict discards the submission so the next one gets new identifiers", async () => {
    const user = userEvent.setup();
    const { callsTo } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": [() => apiError(409, "EVENT_ID_CONFLICT"), () => json(201, receipt())],
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    expect(
      await screen.findByRole("heading", { name: "Already used with different content" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("heading", { name: "Message stored" });
    const [first, second] = callsTo("/api/v1/events/sms");
    expect(bodyOf(second).event_id).not.toBe(bodyOf(first).event_id);
  });

  it("never treats an unrecognised error as safe", () => {
    expect(classifyFailure(new Error("boom")).kind).toBe("uncertain");
  });

  it("a 401 ends the session and returns to sign-in", async () => {
    renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => apiError(401, "SESSION_EXPIRED"),
    });
    await typeAndSubmit();
    expect(await screen.findByRole("heading", { name: "Sign in to KAVACH" })).toBeInTheDocument();
    expect(screen.getByText(/Your session ended/)).toBeInTheDocument();
  });
});

describe("model status notices", () => {
  it.each([
    ["disabled", /disabled on this deployment.*no prediction is made/],
    ["starting", /starting\. Submissions are refused/],
    ["unavailable", /unavailable\. Your message will be stored with the analysis unavailable/],
    ["ready", /Experimental analysis is on\..*not an established fact/],
  ] as const)("explains the %s worker state honestly", async (state, text) => {
    renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/system/models": () => json(200, models(state)),
    });
    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});

describe("privacy", () => {
  it("keeps the text out of URLs, links and browser storage through a full submission", async () => {
    const { container } = renderApp("/analyze", [sessionAs("admin")], undefined, {
      "/api/v1/events/sms": () => json(201, receipt()),
      [`/api/v1/incidents/${INCIDENT}`]: unavailableDetail,
    });
    await typeAndSubmit();
    await screen.findByRole("heading", { name: "Message stored" });
    await waitFor(() => {
      expect(window.localStorage.length).toBe(0);
    });
    expect(window.sessionStorage.length).toBe(0);
    for (const link of container.querySelectorAll("a")) {
      expect(link.getAttribute("href") ?? "").not.toContain("CANARY");
      expect(link.getAttribute("href") ?? "").not.toContain("parcel");
    }
    expect(window.location.href).not.toContain("CANARY");
  });
});
