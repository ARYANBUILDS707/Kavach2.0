import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/public-e2e", fullyParallel: false, retries: 0,
  use: { baseURL: "http://127.0.0.1:5184", trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "KAVACH_API_TARGET=http://127.0.0.1:8184 npm run dev -- --port 5184",
    url: "http://127.0.0.1:5184", reuseExistingServer: false,
  },
});
