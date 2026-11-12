// The login-free public pages, the folding console menu, the in-memory theme toggle and the
// overview's per-day activity, through the real app.
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

describe("public pages", () => {
  it("open without a login, make no API request at all, and offer no sign-in or sign-up", async () => {
    for (const path of ["/", "/examples"]) {
      const { requests, unmount } = renderApp(path, signedOut);
      expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(screen.queryByText(/sign up|register|create an account/i)).toBeNull();
      expect(screen.queryByRole("link", { name: /sign.?in|log.?in/i })).toBeNull();
      expect(screen.queryByRole("button", { name: /sign.?in|log.?in/i })).toBeNull();
      for (const link of screen.getAllByRole("link")) {
        expect(link.getAttribute("href") ?? "").not.toMatch(/login|admin/);
      }
      expect(requests).toHaveLength(0);
      unmount();
    }
  });

  it("keeps the old addresses working: /welcome is the public home, /login is the console sign-in", async () => {
    const first = renderApp("/welcome", signedOut);
    expect(await screen.findByRole("heading", { level: 1, name: /Read the signal/ })).toBeInTheDocument();
    expect(first.requests).toHaveLength(0);
    first.unmount();
    renderApp("/login", signedOut);
    expect(await screen.findByRole("heading", { name: "Sign in to KAVACH" })).toBeInTheDocument();
  });

  it("states the model's limits instead of claiming a live state", async () => {
    renderApp("/", signedOut);
    const status = await screen.findByRole("region", { name: "Release status" });
    expect(within(status).getByText(/disabled by default and is not validated on KAVACH data/)).toBeInTheDocument();
    expect(within(status).getByText("Unknown until calibrated")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("has one keyboard control that pauses and resumes all decorative motion", async () => {
    const user = userEvent.setup();
    renderApp("/", signedOut);
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

  it("leaves the console behind its own sign-in, which links back to the public site", async () => {
    renderApp("/admin/incidents", signedOut);
    expect(await screen.findByRole("heading", { name: "Sign in to KAVACH" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See what KAVACH does" })).toHaveAttribute("href", "/");
  });
});

describe("app menu", () => {
  it("opens and closes with the button and Escape, and closes on navigation", async () => {
    const user = userEvent.setup();
    renderApp("/admin/system", signedIn);
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
    renderApp("/admin/system", signedIn);
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
    const { callsTo } = renderApp("/admin", signedIn, undefined, {
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
