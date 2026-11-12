import { expect, test, type Page } from "@playwright/test";

import { axeViolations } from "./axe";

// The public pages (landing and sign-in) make no data requests, so they run without accounts.
// Checks the redesign's responsive contract at every reviewed width, in both themes.
const WIDTHS = [1440, 1280, 1024, 768, 390, 360];

for (const colorScheme of ["light", "dark"] as const) {
  test(`landing and sign-in fit every width without overflow or axe violations (${colorScheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      for (const [path, heading] of [
        ["/welcome", /Read the signal/],
        ["/login", /Sign in to KAVACH/],
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
    await page.goto("/welcome");
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
  await page.goto("/welcome");
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
  await page.goto("/welcome");
  await expect(page.getByRole("heading", { level: 1, name: /Read the signal/ })).toBeVisible();
  expect(await playStates(page)).toEqual(["none", "none", "none"]);
  await expect(page.getByRole("button", { name: /motion/ })).toHaveCount(0);
});

test("the landing page offers sign-in only and its section links work", async ({ page }) => {
  await page.goto("/welcome");
  await expect(page.getByText(/sign up|register|create an account/i)).toHaveCount(0);
  for (const link of await page.getByRole("link", { name: /^Sign in/ }).all()) {
    await expect(link).toHaveAttribute("href", "/login");
  }
  await page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name: "Capabilities" }).click();
  await expect(page).toHaveURL(/\/welcome#capabilities$/);
  await expect(page.getByRole("heading", { name: "Four tools. One workspace." })).toBeInViewport();
  const storage = await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length]);
  expect(storage).toEqual([0, 0]);
});
