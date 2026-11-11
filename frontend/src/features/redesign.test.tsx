// The public landing page, the folding app menu, the in-memory theme toggle and the overview's
// per-day activity, through the real app.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { SESSION, apiError, json } from "../test/fakeFetch";
import { page, summary } from "../test/fixtures";
import { renderApp } from "../test/renderApp";
import { countByDay } from "./overview/activity";

const signedIn = [() => json(200, SESSION)];
const signedOut = [() => apiError(401, "SESSION_EXPIRED")];

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("landing page", () => {
  it("is public, reads no data and offers sign-in but never sign-up", async () => {
    const { requests } = renderApp("/welcome", signedOut);
    expect(await screen.findByRole("heading", { level: 1, name: /Read the signal/ })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    for (const link of screen.getAllByRole("link", { name: /^Sign in/ })) {
      expect(link).toHaveAttribute("href", "/login");
    }
    expect(screen.queryByText(/sign up|register|create an account/i)).toBeNull();
    expect(requests.filter((r) => !r.url.startsWith("/api/v1/auth/"))).toHaveLength(0);
  });

  it("states the model's limits instead of claiming a live state", async () => {
    renderApp("/welcome", signedOut);
    const status = await screen.findByRole("region", { name: "Release status" });
    expect(within(status).getByText(/disabled by default and is not validated on KAVACH data/)).toBeInTheDocument();
    expect(within(status).getByText("Unknown until calibrated")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("has one keyboard control that pauses and resumes all decorative motion", async () => {
    const user = userEvent.setup();
    renderApp("/welcome", signedOut);
    const toggle = await screen.findByRole("button", { name: "Pause motion" });
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("data-motion", "running");

    // Reached in the normal tab order, operated with Enter, then Space.
    for (let i = 0; i < 30 && document.activeElement !== toggle; i++) await user.tab();
    expect(toggle).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAccessibleName("Resume motion");
    expect(main).toHaveAttribute("data-motion", "paused");
    // The changing label carries the state; aria-pressed as well would contradict it.
    expect(toggle).not.toHaveAttribute("aria-pressed");

    await user.keyboard(" ");
    expect(toggle).toHaveAccessibleName("Pause motion");
    expect(main).toHaveAttribute("data-motion", "running");
    expect(toggle).toHaveFocus();
    expect([window.localStorage.length, window.sessionStorage.length]).toEqual([0, 0]);
  });

  it("leaves protected pages going to sign-in, which links back to the landing page", async () => {
    renderApp("/incidents", signedOut);
    expect(await screen.findByRole("heading", { name: "Sign in to KAVACH" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Learn what KAVACH does" })).toHaveAttribute("href", "/welcome");
  });
});

describe("app menu", () => {
  it("opens and closes with the button and Escape, and closes on navigation", async () => {
    const user = userEvent.setup();
    renderApp("/system", signedIn);
    const toggle = await screen.findByRole("button", { name: "Menu" });
    const panel = document.getElementById("shell-panel");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "shell-panel");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toHaveAttribute("data-open", "true");
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    await user.click(toggle);
    const nav = screen.getByRole("navigation", { name: "Main" });
    await user.click(within(nav).getByRole("link", { name: "Incidents" }));
    await screen.findByRole("heading", { name: "Incident history" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});

describe("theme toggle", () => {
  it("switches the theme in memory only", async () => {
    const user = userEvent.setup();
    renderApp("/system", signedIn);
    // jsdom has no matchMedia, so the starting theme is light.
    await user.click(await screen.findByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});

describe("overview activity", () => {
  it("counts loaded records per local day, newest day first", () => {
    const items = [
      summary(1, { occurred_at: "2031-01-03T10:00:00" }),
      summary(2, { occurred_at: "2031-01-03T11:00:00" }),
      summary(3, { occurred_at: "2031-01-01T09:00:00" }),
      summary(4, { occurred_at: "not a time" }),
    ];
    expect(countByDay(items).map(({ day, count }) => [day, count])).toEqual([
      ["2031-01-03", 2],
      ["2031-01-01", 1],
    ]);
    expect(countByDay([])).toEqual([]);
  });

  it("shows the per-day counts from the same single request", async () => {
    const { callsTo } = renderApp("/", signedIn, undefined, {
      "/api/v1/incidents": () => json(200, page([summary(1), summary(2), summary(3)])),
    });
    const activity = await screen.findByRole("region", { name: "Records per day" });
    expect(within(activity).getByText(/From the same 3 loaded records/)).toBeInTheDocument();
    expect(within(activity).getAllByRole("listitem")).toHaveLength(1);
    expect(within(activity).getByText("3")).toBeInTheDocument();
    await waitFor(() => {
      expect(callsTo("/api/v1/incidents")).toHaveLength(1);
    });
  });
});
