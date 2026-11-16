import { defineConfig, devices } from "@playwright/test";

// Static build with in-browser inference (`npm run build:static` first). Downloads the real pinned
// model from Hugging Face once per test, so it is slow and needs network: run it on purpose.
const base = process.env.KAVACH_BASE ?? "/Kavach2.0/";
export default defineConfig({
  testDir: "tests/browser-e2e", fullyParallel: false, retries: 0, timeout: 600_000,
  use: { baseURL: `http://127.0.0.1:4174${base}`, trace: "off", screenshot: "off", video: "off" },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `KAVACH_BASE=${base} npx vite preview --port 4174 --strictPort`,
    url: `http://127.0.0.1:4174${base}`, reuseExistingServer: false,
  },
});
