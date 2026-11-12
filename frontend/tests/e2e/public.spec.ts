import { expect, test, type Page } from "@playwright/test";

import { axeViolations } from "./axe";

// The login-free public pages (home and recorded examples) make no API request at all, so these
// run with no backend and no accounts. The operator sign-in lives at /admin/login and is not
// linked from them. Checks the responsive contract at every reviewed width, in both themes.
const WIDTHS = [1440, 1280, 1024, 768, 390, 360];

for (const colorScheme of ["light", "dark"] as const) {
  test(`public pages and the operator sign-in fit every width without overflow or axe violations (${colorScheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      for (const [path, heading] of [
        ["/", /Read the signal/],
        ["/examples", /What the model said about fictional messages/],
        ["/admin/login", /Sign in to KAVACH/],
      ] as const) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, `${path} at ${String(width)}px: horizontal overflow`).toBeLessThanOrEqual(0);
        expect(await axeViolations(page), `${path} at ${String(width)}px`).toEqual([]);
      }
    }
  });
}

test("every scroll-revealed section ends fully visible after scrolling to the end", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y <= height; y += 300) {
      await page.mouse.wheel(0, 300);
    }
    await expect
      .poll(() =>
        page.evaluate(() =>
          Array.from(document.querySelectorAll(".reveal")).filter((el) => Number(getComputedStyle(el).opacity) < 0.99)
            .length,
        ),
      )
      .toBe(0);
  }
});

// The three continuous decorative animations the motion control governs.
const MOVING = [".ticker-track", ".ill-hero", ".status-dot"];

function playStates(page: Page) {
  return page.evaluate(
    (selectors) =>
      selectors.map((selector) => {
        const animations = document.querySelector(selector)?.getAnimations() ?? [];
        return animations.length === 0 ? "none" : animations.map((animation) => animation.playState).join(",");
      }),
    MOVING,
  );
}

test("one keyboard control pauses and resumes every decorative animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect.poll(() => playStates(page)).toEqual(["running", "running", "running"]);

  // Reached with Tab and operated with Enter: everything pauses together.
  const toggle = page.getByRole("button", { name: "Pause motion" });
  for (let i = 0; i < 30 && !(await toggle.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(toggle).toBeFocused();
  await page.keyboard.press("Enter");
  const resume = page.getByRole("button", { name: "Resume motion" });
  await expect(resume).toBeFocused();
  await expect(resume).not.toHaveAttribute("aria-pressed");
  await expect.poll(() => playStates(page)).toEqual(["paused", "paused", "paused"]);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(await axeViolations(page), `paused, ${colorScheme}`).toEqual([]);
  }

  // Paused motion leaves scrolling and in-page navigation alone.
  await page.mouse.wheel(0, 600);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await page.evaluate(() => {
    window.scrollTo(0, 0);
  });

  // Space resumes all three, and the label returns.
  await resume.focus();
  await page.keyboard.press(" ");
  await expect(page.getByRole("button", { name: "Pause motion" })).toBeFocused();
  await expect.poll(() => playStates(page)).toEqual(["running", "running", "running"]);
  expect(await axeViolations(page), "running").toEqual([]);

  // The ticker still pauses on its own while the pointer rests on it.
  await page.locator(".ticker").hover();
  await expect.poll(() => playStates(page)).toEqual(["paused", "running", "running"]);
  await page.mouse.move(0, 0);
  await expect.poll(() => playStates(page)).toEqual(["running", "running", "running"]);

  // A mouse click works the same way, and nothing is remembered in browser storage.
  await page.getByRole("button", { name: "Pause motion" }).click();
  await expect.poll(() => playStates(page)).toEqual(["paused", "paused", "paused"]);
  expect(await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length])).toEqual([0, 0]);
});

test("with reduced motion requested, nothing moves and there is no motion to pause", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /Read the signal/ })).toBeVisible();
  expect(await playStates(page)).toEqual(["none", "none", "none"]);
  await expect(page.getByRole("button", { name: /motion/ })).toHaveCount(0);
});

test("visitors never meet a login: no sign-in or sign-up, no account, no API traffic, no cookies", async ({
  page,
  context,
}) => {
  const requests: string[] = [];
  const consoleErrors: string[] = [];
  page.on("request", (request) => {
    requests.push(new URL(request.url()).pathname);
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  for (const path of ["/", "/examples"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/sign up|register|create an account/i)).toHaveCount(0);
    await expect(page.getByRole("link", { name: /sign.?in|log.?in|admin/i })).toHaveCount(0);
    for (const link of await page.getByRole("link").all()) {
      expect((await link.getAttribute("href")) ?? "").not.toMatch(/login|admin/i);
    }
    // Nothing on a public page can take typed input.
    await expect(page.locator("input, textarea, select, form, [contenteditable]")).toHaveCount(0);
  }
  expect(requests.filter((path) => path.startsWith("/api/"))).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(await context.cookies()).toEqual([]);
  expect(await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length])).toEqual([0, 0]);
});

test("the home page's section links work and its calls to action lead to the recorded examples", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Capabilities" }).click();
  await expect(page).toHaveURL(/\/#capabilities$/);
  await expect(page.getByRole("heading", { name: "Four tools. One workspace." })).toBeInViewport();
  await page.getByRole("link", { name: "See recorded examples" }).click();
  await expect(page).toHaveURL(/\/examples$/);
  await expect(page.getByRole("heading", { level: 1, name: "What the model said about fictional messages" })).toBeVisible();
  // From the examples page the section links return to the home page's sections.
  await page.getByRole("navigation", { name: "Site" }).getByRole("link", { name: "Status" }).click();
  await expect(page).toHaveURL(/\/#status$/);
  await expect(page.getByRole("region", { name: "Release status" })).toBeVisible();
});

test("the examples are labelled as recorded, not live, and offer no way to submit a message", async ({ page }) => {
  await page.goto("/examples");
  await expect(page.getByText("These are recorded examples, not live analysis.")).toBeVisible();
  await expect(page.getByText(/no box to type a message into/)).toBeVisible();
  await expect(page.getByText(/not validated on KAVACH data/).first()).toBeVisible();
  const cards = page.getByRole("list", { name: "Recorded examples" }).getByRole("article");
  expect(await cards.count()).toBeGreaterThanOrEqual(6);
  for (const text of await cards.locator(".example-text").allTextContents()) {
    expect(text.startsWith("FICTIONAL TEST:")).toBe(true);
  }
});

test("robots.txt keeps crawlers away from the operator console and the API", async ({ request }) => {
  const response = await request.get("/robots.txt");
  expect(response.status()).toBe(200);
  const body = await response.text();
  expect(body).toContain("Disallow: /admin");
  expect(body).toContain("Disallow: /api/");
});
