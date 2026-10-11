// e2e for the public snapshot build (M2b.1). No backend and no API: the web
// server builds the site from the synthetic fixture with `npm run
// build:public` (SNAPSHOT_DIR=e2e/fixtures/snapshot and
// SNAPSHOT_ALLOW_FIXTURE=1, which nothing else sets) and serves out/ the way
// Vercel serves a static export (e2e-public/serve-static.mjs).
// NEXT_PUBLIC_API_URL is a canary: no request may reach it, and no built file
// may contain it. Run with `npm run test:e2e:public`. It shares .next and
// out/ with every build and with `npm run test:e2e`: run them one after the
// other.

import { defineConfig, devices } from "@playwright/test";

import { CANARY_API_URL, FIXTURE_DIR } from "./e2e-public/fixture";

// Its own port (override with E2E_PUBLIC_PORT).
const PORT = Number.parseInt(process.env.E2E_PUBLIC_PORT ?? "", 10) || 3200;
const BUILD_OUTPUT = /build-output\.spec\.ts$/;

export default defineConfig({
  testDir: "./e2e-public",
  outputDir: "./test-results/public",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    // Checks on the exported files in out/: once, no browser.
    { name: "build-output", testMatch: BUILD_OUTPUT },
    {
      name: "mobile-320",
      testIgnore: BUILD_OUTPUT,
      use: { ...devices["Desktop Chrome"], viewport: { width: 320, height: 800 } },
    },
    {
      name: "desktop-1280",
      testIgnore: BUILD_OUTPUT,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
    },
  ],
  webServer: {
    command: `npm run build:public && node e2e-public/serve-static.mjs out ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    // A full static build runs first.
    timeout: 600_000,
    // Playwright merges these over the shell environment.
    env: {
      SNAPSHOT_DIR: FIXTURE_DIR,
      SNAPSHOT_ALLOW_FIXTURE: "1",
      NEXT_PUBLIC_API_URL: CANARY_API_URL,
    },
  },
});
