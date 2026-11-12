import { expect, test, type APIRequestContext } from "@playwright/test";

import { ORIGIN } from "./origin";

// Anonymous visitors against the REAL backend, through the Vite proxy: the API refuses them and
// the operator console sends them to its own sign-in. No credentials are involved, nothing is
// written, and nothing is mocked. Skipped when no backend answers the health check.
const FICTIONAL = "FICTIONAL ANONYMOUS PROBE: this text must never be stored or echoed.";

async function requireBackend(request: APIRequestContext) {
  const health = await request.get("/api/v1/health").catch(() => null);
  test.skip(health?.status() !== 200, "no backend is answering on the proxy target");
}

test("every private API route refuses an anonymous caller and sets no cookie", async ({ request }) => {
  await requireBackend(request);
  const id = "00000000-0000-4000-8000-000000000001";
  for (const path of [
    "/api/v1/auth/session",
    "/api/v1/incidents?channel=sms&limit=1",
    `/api/v1/incidents/${id}`,
    "/api/v1/system/models",
    "/api/v1/simulator/scenarios",
    `/api/v1/events/${id}`,
  ]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(401);
    expect(response.headers()["set-cookie"], path).toBeUndefined();
    expect(response.headers()["x-request-id"], path).toBeTruthy();
  }
});

test("an anonymous message submission is refused with or without an Origin or CSRF token", async ({ request }) => {
  await requireBackend(request);
  const body = {
    event_id: "anonymous-probe-1",
    subscriber_token: "sub_anonymous_probe",
    timestamp: new Date().toISOString(),
    source: "simulator",
    text: FICTIONAL,
  };
  for (const headers of [{}, { Origin: ORIGIN }, { Origin: ORIGIN, "X-CSRF-Token": "guessed" }]) {
    const response = await request.post("/api/v1/events/sms", { headers, data: body });
    expect([401, 403], JSON.stringify(headers)).toContain(response.status());
    expect(await response.text()).not.toContain("ANONYMOUS PROBE");
  }
});

test("the private console sends an anonymous visitor to its own sign-in and shows nothing private", async ({
  page,
}) => {
  await requireBackend(page.request);
  for (const [path, next] of [
    ["/admin", null],
    ["/admin/incidents", "%2Fadmin%2Fincidents"],
    ["/admin/system", "%2Fadmin%2Fsystem"],
    ["/admin/analyze", "%2Fadmin%2Fanalyze"],
  ] as const) {
    await page.goto(path);
    await expect(page).toHaveURL(next === null ? /\/admin\/login$/ : new RegExp(`/admin/login\\?next=${next}$`));
    await expect(page.getByRole("heading", { level: 1, name: "Sign in to KAVACH" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Incident history|System status|Analyze a synthetic SMS|Overview/ })).toHaveCount(0);
  }
});

test("the old unprefixed console addresses no longer exist for a visitor", async ({ page }) => {
  for (const path of ["/incidents", "/system", "/analyze"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  }
});
