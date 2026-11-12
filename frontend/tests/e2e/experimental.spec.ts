import { expect, test, type Page } from "@playwright/test";

import { axeViolations } from "./axe";

// Experimental SMS analysis against the REAL backend and the REAL pinned model (docs/EXPERIMENTAL_SMS_ANALYSIS.md).
// KAVACH_E2E_MODEL_MODE selects what the running backend was started as:
//   experimental: worker on and healthy; every prediction is read from the real model
//   offline:      worker authorized but its model directory is missing (unavailable)
//   timeout:      worker on with SMS_INFERENCE_TIMEOUT_MS=100 (a long message times out)
// The expected class is never hardcoded: the test checks that what the page shows is exactly what
// the backend stored from the model, and records the prediction beside the author's intent.
const mode = process.env.KAVACH_E2E_MODEL_MODE ?? "";
const admin = {
  username: process.env.KAVACH_E2E_USERNAME ?? "",
  password: process.env.KAVACH_E2E_PASSWORD ?? "",
};
const NAMES: Record<string, string> = { fraud: "Fraud", spam: "Spam", legitimate: "Legitimate" };

test.skip(mode === "", "set KAVACH_E2E_MODEL_MODE to run against a model-enabled backend");
test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

const MESSAGES = [
  {
    intent: "fraud-like",
    text: "FICTIONAL E2E: Your Northpay account is frozen. Confirm your card PIN at http://northpay-unlock.example within 1 hour.",
  },
  {
    intent: "spam-like",
    text: "FICTIONAL E2E: Diwali Dhamaka at Fabrikart! Flat 60% off on electronics this weekend only. Reply STOP to opt out.",
  },
  {
    intent: "normal",
    text: "FICTIONAL E2E: Running 15 minutes late for the meeting, please start without me. Will join soon.",
  },
];

interface Stage {
  status: string;
  reason: string | null;
  model_output: { top_label: string; labels: Record<string, number> } | null;
}
interface Detail {
  tier: string;
  final_score: number | null;
  events: { sms_score: number | null; stages: Record<string, Stage> }[];
}

async function signIn(page: Page) {
  await page.goto("/admin/login");
  await page.getByLabel("Username").fill(admin.username);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
}

/** Submits one message on the Analyze page and returns the stored incident as the API reports it. */
async function submit(page: Page, text: string): Promise<{ id: string; detail: Detail }> {
  // A previous receipt stays on screen, so wait for the incident link to change, not just appear.
  const link = page.getByRole("link", { name: /Open incident/ }).first();
  const previous = (await link.count()) > 0 ? await link.getAttribute("href") : null;
  await page.getByLabel("Synthetic message text").fill(text);
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByRole("heading", { name: /Message stored/ })).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => link.getAttribute("href"), { timeout: 30_000 }).not.toBe(previous);
  const href = await link.getAttribute("href");
  const id = (href ?? "").split("/").pop() ?? "";
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  const response = await page.request.get(`/api/v1/incidents/${id}`);
  expect(response.status()).toBe(200);
  return { id, detail: ((await response.json()) as { data: Detail }).data };
}

test.describe("experimental mode: real predictions", () => {
  test.skip(mode !== "experimental", "needs a healthy model-enabled backend");

  test("each fictional SMS gets the real model's prediction, shown as a prediction", async ({ page }) => {
    test.setTimeout(120_000);
    await signIn(page);
    await expect(page.getByRole("link", { name: "SMS model: Ready" })).toBeVisible();
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Analyze SMS" }).click();
    await expect(page.getByText(/Experimental analysis is on/)).toBeVisible();

    const results: { intent: string; prediction: string; labels: Record<string, number> }[] = [];
    for (const message of MESSAGES) {
      const { detail } = await submit(page, message.text);
      const stage = detail.events[0]?.stages.sms_classifier;
      expect(stage?.status, `${message.intent}: model stage`).toBe("complete");
      const output = stage?.model_output;
      expect(output).not.toBeNull();
      const top = output?.top_label ?? "";
      expect(Object.keys(NAMES)).toContain(top);
      // Still uncalibrated evidence: no score, no tier.
      expect(detail.events[0]?.sms_score ?? null).toBeNull();
      expect(detail.final_score).toBeNull();
      expect(detail.tier).toBe("unknown");

      const panel = page.getByRole("region", { name: "Model prediction (experimental)" });
      await expect(panel).toBeVisible();
      await expect(panel.getByText(/The model predicts:/)).toHaveText(`The model predicts: ${NAMES[top] ?? top}`);
      await expect(panel.getByText(/not an established fact/)).toBeVisible();
      await expect(panel.getByText(/horizon-phishing-scam-base@/)).toBeVisible();
      // The text leaves no trace in the page, URL or storage.
      await expect(page.getByLabel("Synthetic message text")).toHaveValue("");
      expect(page.url()).not.toContain("FICTIONAL");
      results.push({ intent: message.intent, prediction: top, labels: output?.labels ?? {} });
    }
    expect(await axeViolations(page)).toEqual([]);
    expect(await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length])).toEqual([0, 0]);
    test.info().annotations.push({ type: "model predictions", description: JSON.stringify(results) });
    console.log("REAL_MODEL_PREDICTIONS", JSON.stringify(results));
  });
});

test.describe("experimental mode: honest failure states", () => {
  test.skip(mode !== "offline" && mode !== "timeout", "needs a worker fault configuration");

  test("a failed analysis is stored and shown as unavailable, never as a prediction", async ({ page }) => {
    test.setTimeout(120_000);
    await signIn(page);
    await page.goto("/admin/analyze");
    // A long message makes the 100 ms inference budget run out; offline fails before inference.
    const text = mode === "timeout" ? `FICTIONAL E2E TIMEOUT: ${"please verify your account details today. ".repeat(90)}`.slice(0, 4000) : MESSAGES[0]?.text ?? "";
    const { detail } = await submit(page, text);
    const stage = detail.events[0]?.stages.sms_classifier;
    expect(stage?.status).toBe("unavailable");
    expect(stage?.model_output ?? null).toBeNull();
    expect(stage?.reason).toBe(mode === "timeout" ? "inference_timeout" : "model_unverified");
    await expect(page.getByText(/Analysis: Unavailable/).first()).toBeVisible();
    await expect(page.getByRole("region", { name: "Model prediction (experimental)" })).toHaveCount(0);
    await expect(page.getByText(/The model predicts:/)).toHaveCount(0);
    test.info().annotations.push({ type: "failure reason", description: stage?.reason ?? "" });
  });
});
