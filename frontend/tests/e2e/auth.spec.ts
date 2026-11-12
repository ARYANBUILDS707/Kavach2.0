import { expect, test, type Page } from "@playwright/test";

import { axeViolations } from "./axe";

// Runs against the REAL local backend on 127.0.0.1:8000 (APP_ORIGIN=http://127.0.0.1:5173)
// through the Vite proxy, with synthetic accounts. Credentials come only from the environment
// and are never written to this file, the report or the console.
const admin = {
  username: process.env.KAVACH_E2E_USERNAME ?? "",
  password: process.env.KAVACH_E2E_PASSWORD ?? "",
};
const viewer = {
  username: process.env.KAVACH_E2E_VIEWER_USERNAME ?? "",
  password: process.env.KAVACH_E2E_VIEWER_PASSWORD ?? "",
};
// The expiry journey needs a backend started with SESSION_IDLE_MINUTES=1.
const shortSession = process.env.KAVACH_E2E_SHORT_SESSION === "1";

async function signIn(page: Page, account: { username: string; password: string }) {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/admin\/login$/);
  await page.getByLabel("Username").fill(account.username);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test.describe("authentication against the real backend", () => {
  test.skip(shortSession, "the main journeys run against a normal-length session");
  test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

  test("sign in, restore the session on reload, and sign out without browser storage", async ({
    page,
  }) => {
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/admin\/login$/);
    expect(await axeViolations(page)).toEqual([]);

    await signIn(page, admin);
    await expect(page.getByText(/· Admin$/)).toBeVisible();
    expect(await axeViolations(page)).toEqual([]);

    await page.reload();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

    const storage = await page.evaluate(() => [
      window.localStorage.length,
      window.sessionStorage.length,
    ]);
    expect(storage).toEqual([0, 0]);
    // The session cookie is HttpOnly: invisible to page scripts.
    expect(await page.evaluate(() => document.cookie)).toBe("");

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByText("You have signed out.")).toBeVisible();
    // The server revoked the session: a reload stays signed out.
    await page.reload();
    await expect(page).toHaveURL(/\/admin\/login$/);
  });

  test("a wrong password gets one generic message and no session", async ({ page }) => {
    await page.goto("/admin/login");
    await page.getByLabel("Username").fill(admin.username);
    await page.getByLabel("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Username or password is incorrect.")).toBeVisible();
    await expect(page.getByLabel("Password")).toHaveValue("");
    const session = await page.request.get("/api/v1/auth/session");
    expect(session.status()).toBe(401);
  });

  test("the server enforces roles: a viewer is shown as a viewer and refused admin reads", async ({
    page,
  }) => {
    test.skip(viewer.username === "", "KAVACH_E2E_VIEWER_USERNAME/PASSWORD not set");
    await signIn(page, viewer);
    await expect(page.getByText(/· Viewer$/)).toBeVisible();
    // Same-origin request with the viewer's cookie: the admin-only route is 403, not hidden.
    const scenarios = await page.request.get("/api/v1/simulator/scenarios");
    expect(scenarios.status()).toBe(403);
    expect(((await scenarios.json()) as { error: { code: string } }).error.code).toBe("FORBIDDEN");
  });
});

test.describe("session expiry against the real backend", () => {
  test.skip(!shortSession, "needs a backend with SESSION_IDLE_MINUTES=1");
  test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

  test("an idle session warns, ends at its deadline, and the server agrees", async ({ page }) => {
    test.setTimeout(150_000);
    await signIn(page, admin);
    await expect(page.getByText(/less than five minutes/)).toBeVisible();
    await expect(page.getByText(/Your session ended/)).toBeVisible({ timeout: 100_000 });
    await expect(page).toHaveURL(/\/admin\/login$/);
    const session = await page.request.get("/api/v1/auth/session");
    expect(session.status()).toBe(401);
  });
});
