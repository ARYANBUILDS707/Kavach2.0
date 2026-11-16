import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Real model, no mocks: the pinned ONNX files come from Hugging Face and run in this browser.
// The sample shortcuts fill invented messages; the predictions are recorded, not asserted.
const SAMPLES = ["Fraud", "Spam", "Legitimate"] as const;
const REVISION = "fa686fc0d6a3634092ada93a7c6b89ab0746b8f8";
const CONSENT = /experimental, unvalidated prediction/;

test("real pinned model runs on the device and the message never leaves it", async ({ page, baseURL }, info) => {
  const siteHost = new URL(baseURL ?? "http://127.0.0.1").hostname;
  const requests: { url: string; body: string | null }[] = [];
  page.on("request", (request) => { requests.push({ url: request.url(), body: request.postData() }); });
  // Direct navigation to the route must be a real page (status 200), not a 404 fallback.
  const landing = await page.goto("analyze");
  expect(landing?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Is this SMS a scam?" })).toBeVisible();
  await expect(page.getByText(/First use downloads the AI model once/)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const input = page.getByLabel("SMS to analyze");
  const analyze = page.getByRole("button", { name: "Analyze SMS" });
  await page.getByRole("button", { name: "Try Fraud Example" }).click();
  await expect(analyze).toBeDisabled(); // consent first
  await page.getByRole("checkbox", { name: CONSENT }).check();

  const texts: string[] = [];
  const observed: { sample: string; prediction: string; model_ms: string }[] = [];
  let loadSeconds = 0;
  for (const sample of SAMPLES) {
    await page.getByRole("button", { name: `Try ${sample} Example` }).click();
    texts.push(await input.inputValue());
    const started = Date.now();
    await analyze.click();
    const heading = page.getByRole("heading", { name: /^Prediction: (Fraud|Spam|Legitimate)$/ });
    await expect(heading).toBeVisible({ timeout: 540_000 });
    if (sample === "Fraud") loadSeconds = (Date.now() - started) / 1000;
    await expect(page.getByText("AI prediction · experimental · unvalidated")).toBeVisible();
    await expect(page.getByText(/never guarantees a message is safe/)).toBeVisible();
    const time = await page.getByText(/^Model time: \d+ ms$/).textContent();
    observed.push({ sample, prediction: (await heading.textContent()) ?? "", model_ms: (time ?? "").replace(/\D/g, "") });
    if (sample === "Fraud") {
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({ path: `test-results/browser-analyzer-result-${info.project.name}.png`, fullPage: true });
    }
    await page.getByRole("button", { name: "Analyze another SMS" }).click();
    await expect(input).toHaveValue("");
    await expect(input).toBeFocused();
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
      expect(new URL(request.url).pathname).toContain(`/${REVISION}/`);
    }
    for (const text of texts) {
      const fragment = text.slice(5, 30);
      expect(decodeURIComponent(request.url)).not.toContain(fragment);
      expect(request.body ?? "").not.toContain(fragment);
    }
  }
  // No KAVACH analysis API exists in this build: nothing same-origin under /api/.
  expect(requests.some((request) => new URL(request.url).hostname === siteHost && request.url.includes("/api/"))).toBe(false);
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // A refresh keeps the route working.
  expect((await page.reload())?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Is this SMS a scam?" })).toBeVisible();
  await page.screenshot({ path: `test-results/browser-analyzer-${info.project.name}.png`, fullPage: true });
});

test("a failed model download shows an honest error and no prediction", async ({ page }) => {
  await page.route(/huggingface\.co|\.hf\.co/, (route) => route.abort());
  await page.goto("analyze");
  await page.getByRole("button", { name: "Try Spam Example" }).click();
  await page.getByRole("checkbox", { name: CONSENT }).check();
  await page.getByRole("button", { name: "Analyze SMS" }).click();
  await expect(page.getByRole("alert")).toContainText("No prediction was produced.");
  await expect(page.getByRole("button", { name: "Retry download and analyze" })).toBeEnabled();
  await expect(page.getByRole("heading", { name: /^Prediction:/ })).toHaveCount(0);
});
