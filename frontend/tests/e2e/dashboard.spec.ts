import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { axeViolations } from "./axe";

// MVP-F2 journeys against the REAL local backend (no mocks). The test creates one synthetic SMS
// through the admin browser-session API (MVP-B4) so the detail page has a known record; the
// message is fictional and must never appear on any page. Credentials come from the environment.
const admin = {
  username: process.env.KAVACH_E2E_USERNAME ?? "",
  password: process.env.KAVACH_E2E_PASSWORD ?? "",
};
const CANARY = "FICTIONAL E2E CANARY 4471: parcel held, pay the release fee at the link";

test.skip(process.env.KAVACH_E2E_SHORT_SESSION === "1", "runs against a normal-length session");
test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

test("overview, history, detail and system show real data honestly", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(admin.username);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // One synthetic SMS through the documented admin path (session + Origin + CSRF).
  const sessionResponse = await page.request.get("/api/v1/auth/session");
  expect(sessionResponse.status(), "session read (a 429 means the shared read budget is spent)").toBe(200);
  const session = (await sessionResponse.json()) as { data: { csrf_token: string } };
  const submitted = await page.request.post("/api/v1/events/sms", {
    headers: { Origin: "http://127.0.0.1:5173", "X-CSRF-Token": session.data.csrf_token },
    data: {
      event_id: `ui-${randomUUID()}`,
      subscriber_token: `ui-sub-${randomUUID()}`,
      timestamp: new Date().toISOString(),
      source: "simulator",
      text: CANARY,
    },
  });
  expect(submitted.status()).toBe(201);
  const receipt = (await submitted.json()) as { data: { incident_ids: string[] } };
  const incidentId = receipt.data.incident_ids[0] ?? "";
  expect(incidentId).toMatch(/^[0-9a-f-]{36}$/);

  // Overview: the new record is counted and listed; the model card is real.
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("table", { name: "Most recent SMS incidents" })).toBeVisible();
  await expect(page.getByRole("region", { name: "SMS model readiness" })).toBeVisible();
  expect(await axeViolations(page)).toEqual([]);

  // History with a filter in the URL, then the detail page through the list link.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Incidents" }).click();
  await page.getByLabel("Risk tier").selectOption("unknown");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/\/incidents\?tier=unknown$/);
  await expect(page.getByRole("table", { name: "Incident records" })).toBeVisible();
  expect(await axeViolations(page)).toEqual([]);

  await page.goto(`/incidents/${incidentId}`);
  await expect(page.getByRole("heading", { name: `Incident ${incidentId.slice(0, 8)}` })).toBeVisible();
  await expect(page.getByText(/Message text is not retained/)).toBeVisible();
  await expect(page.getByText("Model not enabled")).toBeVisible();
  await expect(page.getByText("Risk tier: Unknown (no calibrated signal)").first()).toBeVisible();
  expect(await axeViolations(page)).toEqual([]);

  // System: the worker is disabled until the M4-Q decision.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "System" }).click();
  const card = page.getByRole("region", { name: "SMS model" });
  await expect(card.getByText("Disabled", { exact: true })).toBeVisible();
  await expect(card.getByText("No: not validated on KAVACH data")).toBeVisible();

  // Privacy: the fictional message never reaches any page, URL or browser storage.
  expect(await page.content()).not.toContain("CANARY 4471");
  expect(page.url()).not.toContain("CANARY");
  const storage = await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length]);
  expect(storage).toEqual([0, 0]);
});

test("a malformed or unknown incident ID is the same unavailable page", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(admin.username);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  for (const id of ["not-a-uuid", randomUUID()]) {
    await page.goto(`/incidents/${id}`);
    await expect(page.getByText("Incident unavailable or expired")).toBeVisible();
  }
});
