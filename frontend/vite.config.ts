import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Same-origin development: the browser talks only to Vite, which forwards /api to the local
// backend. `changeOrigin: false` keeps the browser's Origin header, so the backend's exact
// APP_ORIGIN check (http://127.0.0.1:5173 in development) behaves as in deployment.
const api = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } };

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: api },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy: api },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
  },
});
