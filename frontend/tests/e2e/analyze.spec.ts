import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { axeViolations } from "./axe";

// MVP-F3 against the REAL local backend (MVP-B4 admin path, worker disabled). The message is
// fictional and must never appear in a URL, browser storage, the console or the page after the
// receipt. Credentials come only from the environment.
const admin = {
  username: process.env.KAVACH_E2E_USERNAME ?? "",
  password: process.env.KAVACH_E2E_PASSWORD ?? "",
};
const viewer = {
  username: process.env.KAVACH_E2E_VIEWER_USERNAME ?? "",
  password: process.env.KAVACH_E2E_VIEWER_PASSWORD ?? "",
};
const CANARY = "FICTIONAL E2E CANARY 7316: your account is locked, verify at the link";

test.skip(process.env.KAVACH_E2E_SHORT_SESSION === "1", "runs against a normal-length session");
test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

async function signIn(page: Page, account: { username: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(account.username);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("an admin submits once, sees the receipt and stored evidence, and the text leaves no trace", async ({
  page,
}) => {
  const consoleLines: string[] = [];
  page.on("console", (message) => consoleLines.push(message.text()));
  const submissions: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/v1/events/sms")) {
      submissions.push(request.url());
    }
  });

  await signIn(page, admin);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Analyze SMS" }).click();
  await expect(page.getByRole("heading", { name: "Analyze a synthetic SMS" })).toBeVisible();
  // The worker is disabled until the M4-Q decision; the page says so instead of predicting.
  await expect(page.getByText(/disabled on this deployment.*no prediction is made/)).toBeVisible();
  expect(await axeViolations(page)).toEqual([]);

  await page.getByLabel("Synthetic message text").fill(CANARY);
  await page.getByRole("button", { name: "Submit" }).dblclick();
  await expect(page.getByRole("heading", { name: "Message stored" })).toBeVisible();
  expect(submissions).toHaveLength(1);
  await expect(page.getByText("Event ID", { exact: true })).toHaveCount(1);

  await expect(page.getByLabel("Synthetic message text")).toHaveValue("");
  await expect(page.getByText("SMS model unavailable: stored without a model result")).toBeVisible();
  await expect(page.getByText("Model not enabled")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Model output (uncalibrated)" })).toHaveCount(0);
  expect(await axeViolations(page)).toEqual([]);

  expect(await page.content()).not.toContain("CANARY 7316");
  expect(page.url()).toMatch(/\/analyze$/);
  const storage = await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length]);
  expect(storage).toEqual([0, 0]);

  // The receipt's incident link opens the real detail page; the URL holds only the ID.
  await page.getByRole("link", { name: /Open incident/ }).click();
  await expect(page).toHaveURL(/\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByText(/Message text is not retained/)).toBeVisible();
  expect(await page.content()).not.toContain("CANARY 7316");
  expect(consoleLines.filter((line) => line.includes("CANARY"))).toEqual([]);
});

test("a viewer has no submission page and the server refuses viewer, CSRF and Origin failures", async ({
  page,
}) => {
  test.skip(viewer.username === "", "KAVACH_E2E_VIEWER_USERNAME/PASSWORD not set");
  await signIn(page, viewer);
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Analyze SMS" }),
  ).toHaveCount(0);
  await page.goto("/analyze");
  await expect(page.getByRole("heading", { level: 1, name: "You don't have access" })).toBeVisible();
  await expect(page.getByLabel("Synthetic message text")).toHaveCount(0);
  expect(await axeViolations(page)).toEqual([]);

  const body = {
    event_id: `ui-${randomUUID()}`,
    subscriber_token: `ui-sub-${randomUUID()}`,
    timestamp: new Date().toISOString(),
    source: "simulator",
    text: CANARY,
  };
  const csrf = ((await (await page.request.get("/api/v1/auth/session")).json()) as {
    data: { csrf_token: string };
  }).data.csrf_token;
  const origin = "http://127.0.0.1:5173";
  const asViewer = await page.request.post("/api/v1/events/sms", {
    headers: { Origin: origin, "X-CSRF-Token": csrf },
    data: body,
  });
  expect([asViewer.status(), ((await asViewer.json()) as { error: { code: string } }).error.code]).toEqual([
    403,
    "FORBIDDEN",
  ]);

  // Back as admin: a missing CSRF token and a foreign Origin are refused before anything is stored.
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, admin);
  const adminCsrf = ((await (await page.request.get("/api/v1/auth/session")).json()) as {
    data: { csrf_token: string };
  }).data.csrf_token;
  for (const headers of [{ Origin: origin }, { Origin: "https://evil.test", "X-CSRF-Token": adminCsrf }]) {
    const refused = await page.request.post("/api/v1/events/sms", { headers, data: body });
    expect(refused.status()).toBe(403);
    expect(((await refused.json()) as { error: { code: string } }).error.code).toBe("CSRF_REJECTED");
  }
});
