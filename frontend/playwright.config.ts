// Route-mocked e2e tests for the pause-state UI (Build L). No backend and no
// API spend: `next dev` runs on its own port with NEXT_PUBLIC_API_URL pointed
// at an unreachable address, and every API call is answered by page.route
// (e2e/mockApi.ts). One-time setup: `npx playwright install chromium`.
// Run with `npm run test:e2e` — not part of `npm run build` or `npm run lint`.

import { defineConfig, devices } from "@playwright/test";

import { MOCK_API_URL } from "./e2e/mockApi";

// Its own port (override with E2E_PORT). It still shares `.next` with any
// `next dev` or `next build` in frontend/, so do not run them at the same time.
const PORT = Number.parseInt(process.env.E2E_PORT ?? "", 10) || 3100;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "mobile-320", use: { ...devices["Desktop Chrome"], viewport: { width: 320, height: 800 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
  ],
  webServer: {
    command: `npx next dev -H 127.0.0.1 -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 180_000,
    // A process env value takes precedence over frontend/.env.local.
    env: { NEXT_PUBLIC_API_URL: MOCK_API_URL },
  },
});
