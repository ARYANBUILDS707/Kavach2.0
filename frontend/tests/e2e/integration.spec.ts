import { expect, test, type Page, type Response } from "@playwright/test";

import { axeViolations } from "./axe";
import { ORIGIN } from "./origin";

// READ-ONLY journey against the REAL local backend through the Vite proxy: it never submits an
// event, never uses page.route(), and compares what the UI shows with the API's own answers, so
// no number on screen can be invented. Credentials come only from the environment.
const admin = {
  username: process.env.KAVACH_E2E_USERNAME ?? "",
  password: process.env.KAVACH_E2E_PASSWORD ?? "",
};

test.skip(process.env.KAVACH_E2E_SHORT_SESSION === "1", "runs against a normal-length session");
test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

interface Page_<T> {
  data: T[];
  page: { next_cursor: string | null; has_more: boolean };
}
interface Summary {
  id: string;
  analysis_status: string;
  tier: string;
}

/** Records every API response the browser itself makes, and every console error. */
function observe(page: Page) {
  const responses: { method: string; path: string; status: number; requestId: string | null }[] = [];
  const consoleErrors: { text: string; url: string }[] = [];
  page.on("response", (response: Response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/")) return;
    responses.push({
      method: response.request().method(),
      path: url.pathname,
      status: response.status(),
      requestId: response.headers()["x-request-id"] ?? null,
    });
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push({ text: message.text(), url: message.location().url });
  });
  page.on("pageerror", (error) => consoleErrors.push({ text: `pageerror: ${error.message}`, url: "" }));
  return { responses, consoleErrors };
}

async function noOverflow(page: Page, label: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label}: horizontal overflow`).toBeLessThanOrEqual(0);
}

test("an admin works through every screen on real data without writing anything", async ({ page }) => {
  test.setTimeout(120_000);
  const seen = observe(page);

  // Signed out, a protected page goes to sign-in.
  await page.goto("/admin/incidents");
  await expect(page).toHaveURL(/\/admin\/login\?next=%2Fadmin%2Fincidents$/);

  await page.getByLabel("Username").fill(admin.username);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Incident history" })).toBeVisible();
  await expect(page.getByText(/· Admin$/)).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  expect(await nav.getByRole("link").allTextContents()).toEqual(["Overview", "Incidents", "System", "Analyze SMS"]);

  // The API's own answers, read with the same session cookie.
  const models = (await (await page.request.get("/api/v1/system/models")).json()) as {
    data: { sms_classifier: { state: string; validated_on_kavach_data: boolean } };
  };
  const smsModel = models.data.sms_classifier;
  const labels: Record<string, string> = { ready: "Ready", starting: "Starting", disabled: "Disabled", unavailable: "Unavailable" };
  const recent = (await (await page.request.get("/api/v1/incidents?channel=sms&limit=25")).json()) as Page_<Summary>;
  expect(smsModel.validated_on_kavach_data).toBe(false);

  // Overview: model state and every count come from those answers.
  await nav.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page.getByRole("link", { name: `SMS model: ${labels[smsModel.state] ?? ""}` })).toBeVisible();
  const readiness = page.getByRole("region", { name: "SMS model readiness" });
  await expect(readiness.getByText(labels[smsModel.state] ?? "", { exact: true })).toBeVisible();
  if (recent.data.length === 0) {
    await expect(page.getByText("No SMS incidents in the last 7 days")).toBeVisible();
    await expect(page.getByRole("region", { name: "Recent SMS records at a glance" })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Records per day" })).toHaveCount(0);
  } else {
    const tiles = page.getByRole("region", { name: "Recent SMS records at a glance" }).getByRole("listitem");
    const count = (status: string) => recent.data.filter((item) => item.analysis_status === status).length;
    // toHaveText retries until the tiles render from the same answers.
    await expect(tiles).toHaveText([
      `${String(recent.data.length)}records in this window`,
      `${String(count("complete"))}with completed model analysis`,
      `${String(count("partial"))}with partial analysis`,
      `${String(count("unavailable"))}with analysis unavailable`,
      `${String(recent.data.filter((item) => item.tier === "unknown").length)}with risk tier unknown (no calibrated signal)`,
    ]);
  }
  expect(await axeViolations(page), "overview axe").toEqual([]);

  // Incident history: the real list, a filter round trip through the URL, and paging only if real.
  await nav.getByRole("link", { name: "Incidents" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Incident history" })).toBeVisible();
  if (recent.data.length === 0) {
    await expect(page.getByText("No SMS incidents in the last 7 days")).toBeVisible();
  } else {
    await expect(page.locator(".incident-table tbody tr")).toHaveCount(recent.data.length);
  }
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(recent.page.has_more ? 1 : 0);
  await page.getByLabel("Risk tier").selectOption("critical");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/\/admin\/incidents\?.*tier=critical/);
  const critical = (await (await page.request.get("/api/v1/incidents?channel=sms&tier=critical&limit=25")).json()) as Page_<Summary>;
  if (critical.data.length === 0) {
    await expect(page.getByText("No incidents match these filters")).toBeVisible();
  } else {
    await expect(page.locator(".incident-table tbody tr")).toHaveCount(critical.data.length);
  }
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL(/\/admin\/incidents$/);
  expect(await axeViolations(page), "incidents axe").toEqual([]);

  // Incident detail: a real incident only if one exists; otherwise recorded as not exercised.
  const first = recent.data[0];
  if (first === undefined) {
    test.info().annotations.push({ type: "not exercised", description: "no incident exists, so no real detail page" });
  } else {
    await page.goto(`/admin/incidents/${first.id}`);
    await expect(page.getByRole("heading", { level: 1, name: `Incident ${first.id.slice(0, 8)}` })).toBeVisible();
    await expect(page.getByText(/Message text is not retained/)).toBeVisible();
    expect(await axeViolations(page), "detail axe").toEqual([]);
  }

  // System: the real state with its honest wording.
  await nav.getByRole("link", { name: "System" }).click();
  const card = page.getByRole("region", { name: "SMS model" });
  await expect(card.getByText(labels[smsModel.state] ?? "", { exact: true })).toBeVisible();
  await expect(card.getByText("No: not validated on KAVACH data")).toBeVisible();
  expect(await axeViolations(page), "system axe").toEqual([]);

  // Analyze SMS: admin access and validation only. Nothing is submitted.
  await nav.getByRole("link", { name: "Analyze SMS" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Analyze a synthetic SMS" })).toBeVisible();
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByRole("alert")).toHaveText("Enter the synthetic message text.");
  expect(await axeViolations(page), "analyze axe").toEqual([]);

  // Phone width: the menu opens and the pages fit.
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/admin", "/admin/incidents", "/admin/system", "/admin/analyze"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await noOverflow(page, `${path} at 390px`);
  }
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(nav.getByRole("link", { name: "Overview" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1280, height: 800 });

  // CSRF: a mutation without the token is refused and the session survives.
  const noToken = await page.request.post("/api/v1/auth/logout", { headers: { Origin: ORIGIN } });
  expect(noToken.status()).toBe(403);
  expect(((await noToken.json()) as { error: { code: string } }).error.code).toBe("CSRF_REJECTED");
  expect((await page.request.get("/api/v1/auth/session")).status()).toBe(200);

  // Nothing in browser storage, and the session cookie is invisible to scripts.
  expect(await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length])).toEqual([0, 0]);
  expect(await page.evaluate(() => document.cookie)).toBe("");

  // Sign out: the server ends the session and protected pages and reads are refused.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByText("You have signed out.")).toBeVisible();
  await page.goto("/admin/system");
  await expect(page).toHaveURL(/\/admin\/login\?next=%2Fadmin%2Fsystem$/);
  expect((await page.request.get("/api/v1/incidents?channel=sms&limit=1")).status()).toBe(401);

  // Every browser API call reached the real backend (request ID present), none was a write to
  // the events API, and the only failures are the expected signed-out session checks.
  expect(seen.responses.length).toBeGreaterThan(0);
  expect(seen.responses.filter((r) => r.requestId === null)).toEqual([]);
  expect(seen.responses.filter((r) => r.path.startsWith("/api/v1/events/"))).toEqual([]);
  const unexpected = seen.responses.filter(
    (r) => r.status >= 400 && !(r.method === "GET" && r.path === "/api/v1/auth/session" && r.status === 401),
  );
  expect(unexpected).toEqual([]);
  const consoleUnexpected = seen.consoleErrors.filter(
    (e) => !(e.text.includes("status of 401") && e.url.endsWith("/api/v1/auth/session")),
  );
  expect(consoleUnexpected).toEqual([]);
});
