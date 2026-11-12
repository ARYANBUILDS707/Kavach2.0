import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { axeViolations } from "./axe";
import { ORIGIN } from "./origin";

// Responsive layout of the incident tables against the REAL local backend. jsdom does no layout,
// so overlap can only be caught here, from actual DOM boxes. Credentials come from the environment.
const admin = {
  username: process.env.KAVACH_E2E_USERNAME ?? "",
  password: process.env.KAVACH_E2E_PASSWORD ?? "",
};

test.skip(process.env.KAVACH_E2E_SHORT_SESSION === "1", "runs against a normal-length session");
test.skip(admin.username === "" || admin.password === "", "KAVACH_E2E_USERNAME/PASSWORD not set");

interface RowBox {
  top: number;
  bottom: number;
  left: number;
  right: number;
  contentBottom: number;
  contentRight: number;
}

async function signIn(page: Page) {
  await page.goto("/admin/login");
  await page.getByLabel("Username").fill(admin.username);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

/** Two fictional events through the admin API, so the tables always have at least two rows. */
async function ensureRows(page: Page) {
  const session = await page.request.get("/api/v1/auth/session");
  expect(session.status(), "session read").toBe(200);
  const csrf = ((await session.json()) as { data: { csrf_token: string } }).data.csrf_token;
  for (let i = 0; i < 2; i += 1) {
    const response = await page.request.post("/api/v1/events/sms", {
      headers: { Origin: ORIGIN, "X-CSRF-Token": csrf },
      data: {
        event_id: `ui-${randomUUID()}`,
        subscriber_token: `ui-sub-${randomUUID()}`,
        timestamp: new Date().toISOString(),
        source: "simulator",
        text: "FICTIONAL LAYOUT TEST MESSAGE",
      },
    });
    expect([200, 201]).toContain(response.status());
  }
}

async function rowBoxes(page: Page): Promise<RowBox[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>(".incident-table tbody tr")).map((row) => {
      const box = row.getBoundingClientRect();
      const cells = Array.from(row.children).map((cell) => cell.getBoundingClientRect());
      return {
        top: box.top + window.scrollY,
        bottom: box.bottom + window.scrollY,
        left: box.left,
        right: box.right,
        contentBottom: Math.max(...cells.map((cell) => cell.bottom)) + window.scrollY,
        contentRight: Math.max(...cells.map((cell) => cell.right)),
      };
    }),
  );
}

async function expectSeparatedRows(page: Page, label: string) {
  const rows = await rowBoxes(page);
  expect(rows.length, `${label}: rows rendered`).toBeGreaterThanOrEqual(2);
  const width = await page.evaluate(() => window.innerWidth);
  rows.forEach((row, index) => {
    expect(row.bottom - row.top, `${label}: row ${String(index)} has height`).toBeGreaterThan(0);
    // The row must contain all of its own cells: nothing spills into the next row.
    expect(row.contentBottom, `${label}: row ${String(index)} contains its content`).toBeLessThanOrEqual(
      row.bottom + 1,
    );
    expect(row.contentRight, `${label}: row ${String(index)} stays in the viewport`).toBeLessThanOrEqual(width + 1);
    expect(row.left, `${label}: row ${String(index)} starts in the viewport`).toBeGreaterThanOrEqual(-1);
    const previous = rows[index - 1];
    if (previous !== undefined) {
      expect(row.top, `${label}: row ${String(index)} starts below row ${String(index - 1)}`).toBeGreaterThanOrEqual(
        previous.bottom - 0.5,
      );
    }
  });
  // Content is actually visible, not clipped away.
  const links = page.locator(".incident-table tbody tr").locator("a", { hasText: "Open incident" });
  await expect(links.first()).toBeVisible();
  await expect(links.last()).toBeVisible();
  const firstRow = page.locator(".incident-table tbody tr").first();
  for (const label of ["Event time", "Incident", "Kind", "Analysis", "Risk tier"]) {
    await expect(firstRow.locator(`td[data-label="${label}"]`)).toBeVisible();
  }
}

async function expectNoHorizontalOverflow(page: Page, label: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label}: horizontal overflow in px`).toBeLessThanOrEqual(0);
}

for (const width of [390, 768]) {
  test(`incident tables are separate, readable rows without overflow at ${String(width)}px`, async ({
    page,
  }) => {
    await signIn(page);
    await ensureRows(page);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1024 });

    for (const [path, heading] of [
      ["/admin", "Overview"],
      ["/admin/incidents", "Incident history"],
    ] as const) {
      const label = `${heading} at ${String(width)}px`;
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expect(page.locator(".incident-table tbody tr").first()).toBeVisible();
      await expectSeparatedRows(page, label);
      await expectNoHorizontalOverflow(page, label);
      expect(await axeViolations(page), `${label}: axe`).toEqual([]);
    }
  });
}
