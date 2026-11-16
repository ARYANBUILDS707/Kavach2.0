import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Real model, no mocks: the pinned ONNX files come from Hugging Face and run in this browser.
// Messages are invented; `intended` is the writer's intent and is recorded, not asserted.
const MESSAGES = [
  { intended: "legitimate", text: "FICTIONAL TEST: Running ten minutes late for dinner, order without me." },
  { intended: "spam", text: "FICTIONAL TEST: Mega Sale at ShopFictional! Flat 50% off this weekend, reply STOP to opt out." },
  { intended: "fraud", text: "FICTIONAL TEST: Your Northpay account is frozen. Confirm your PIN at the link now to avoid closure." },
];

test("real pinned model runs on the device and the message never leaves it", async ({ page, baseURL }, info) => {
  const siteHost = new URL(baseURL ?? "http://127.0.0.1").hostname;
  const requests: { url: string; body: string | null }[] = [];
  page.on("request", (request) => { requests.push({ url: request.url(), body: request.postData() }); });
  // Direct navigation to the route must be a real page (status 200), not a 404 fallback.
  const landing = await page.goto("analyze");
  expect(landing?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Analyze an SMS" })).toBeVisible();
  await expect(page.getByText(/not validated on KAVACH data/)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const started = Date.now();
  await page.getByRole("button", { name: /^Load model/ }).click();
  await expect(page.getByText(/^Model ready on this device/)).toBeVisible({ timeout: 540_000 });
  const loadSeconds = (Date.now() - started) / 1000;

  const input = page.getByLabel("SMS to analyze");
  const analyze = page.getByRole("button", { name: "Analyze", exact: true });
  await input.fill(MESSAGES[0]?.text ?? "");
  await expect(analyze).toBeDisabled(); // consent is required first
  await page.getByRole("checkbox", { name: /experimental, unvalidated prediction/ }).check();
  const observed: { intended: string; prediction: string; model_ms: string }[] = [];
  for (const message of MESSAGES) {
    await input.fill(message.text);
    await analyze.click();
    const heading = page.getByRole("heading", { name: /^Prediction: (Fraud|Spam|Legitimate)$/ });
    await expect(heading).toBeVisible({ timeout: 60_000 });
    const time = await page.getByText(/^Model time: \d+ ms$/).textContent();
    observed.push({ intended: message.intended, prediction: (await heading.textContent()) ?? "",
      model_ms: (time ?? "").replace(/\D/g, "") });
    await expect(input).toHaveValue("");
  }
  info.annotations.push({ type: "observed", description: JSON.stringify({ loadSeconds, observed }) });
  console.log(`[${info.project.name}] load ${loadSeconds.toFixed(1)} s`, JSON.stringify(observed));

  // Nothing but the site itself and the pinned model revision was contacted, and no request
  // carried message text.
  const origins = new Set(requests.map((request) => new URL(request.url).hostname));
  for (const host of origins) expect(host === siteHost || host === "huggingface.co" || host.endsWith(".hf.co")).toBe(true);
  for (const request of requests) {
    if (new URL(request.url).hostname === "huggingface.co") {
      // /resolve/<revision>/ or the hub's redirect to /api/resolve-cache/…/<revision>/: always the pinned commit.
      expect(new URL(request.url).pathname).toContain("/fa686fc0d6a3634092ada93a7c6b89ab0746b8f8/");
    }
    for (const message of MESSAGES) {
      expect(request.url).not.toContain(encodeURIComponent(message.text.slice(15, 40)));
      expect(request.body ?? "").not.toContain(message.text.slice(15, 40));
    }
  }
  // No KAVACH analysis API exists in this build: nothing same-origin under /api/.
  expect(requests.some((request) => new URL(request.url).hostname === siteHost && request.url.includes("/api/"))).toBe(false);
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // A refresh keeps the route working.
  expect((await page.reload())?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Analyze an SMS" })).toBeVisible();
  await page.screenshot({ path: `test-results/browser-analyzer-${info.project.name}.png`, fullPage: true });
});
