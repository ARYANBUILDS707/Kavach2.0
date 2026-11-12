import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// No API mocking: start the isolated real public backend on 8184 first.
for (const width of [390, 1280]) {
  test(`real anonymous inference at ${String(width)}px`, async ({ page }) => {
    test.skip(process.env.KAVACH_PUBLIC_E2E_MODE === "disabled", "live model not configured");
    await page.setViewportSize({ width, height: 900 });
    const paths: string[] = [];
    page.on("request", (request) => { paths.push(new URL(request.url()).pathname); });
    await page.goto("/analyze");
    const input = page.getByLabel("Fictional SMS");
    await expect(input).toBeEnabled();
    await input.fill("FICTIONAL TEST: Running ten minutes late for dinner.");
    await page.getByRole("button", { name: "Analyze", exact: true }).click();
    await expect(page.getByRole("heading", { name: /^Prediction: (Fraud|Spam|Legitimate)$/ })).toBeVisible();
    await expect(input).toHaveValue("");
    // React StrictMode may repeat the idempotent availability GET in development.
    expect(new Set(paths.filter((path) => path.startsWith("/api/")))).toEqual(new Set([
      "/api/v1/public/analyzer", "/api/v1/public/analyze",
    ]));
    expect(paths.filter((path) => path === "/api/v1/public/analyze")).toHaveLength(1);
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
    expect(await page.context().cookies()).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.evaluate(() => { window.scrollTo(0, 0); });
    await page.screenshot({ path: `test-results/public-analyzer-${String(width)}.png`, fullPage: true });
    await page.getByRole("button", { name: "Clear" }).click();
    await expect(page.getByRole("heading", { name: /^Prediction:/ })).toHaveCount(0);
  });
}


test("disabled public analyzer and admin isolation", async ({ page, request }) => {
  test.skip(process.env.KAVACH_PUBLIC_E2E_MODE !== "disabled", "disabled mode only");
  await page.goto("/analyze");
  await expect(page.getByText(/Public analysis is disabled/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Analyze", exact: true })).toBeDisabled();
  const response = await request.post("/api/v1/public/analyze", { data: { text: "FICTIONAL TEST" } });
  expect(response.status()).toBe(503);
  expect((await request.get("/api/v1/incidents")).status()).toBe(404);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
