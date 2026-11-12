import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

/**
 * Runs the full axe audit on the page as the user finally sees it. Page entrances fade in and
 * the active navigation pill eases its background, so an audit started the instant content
 * appears measures half-transparent colours (contrast failures that never exist at rest). This
 * waits for every finite, time-based animation or transition to finish first; infinite
 * decorative loops and scroll-driven reveals never "finish" and are left out of the wait.
 */
export async function axeViolations(page: Page) {
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every(
        (animation) =>
          animation.playState !== "running" ||
          !(animation.timeline instanceof DocumentTimeline) ||
          animation.effect?.getComputedTiming().iterations === Infinity,
      ),
  );
  return (await new AxeBuilder({ page }).analyze()).violations;
}
