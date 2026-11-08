import { defineConfig, devices } from "@playwright/test";

// Browser journeys run against the REAL local backend (started separately; see
// FRONTEND_MVP1_PLAN.md section 14.5). Playwright never mocks the API.
export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "off",
    // Saved under test-results/ (ignored by Git) only when a test fails.
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
