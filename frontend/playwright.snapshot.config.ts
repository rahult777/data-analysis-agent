// e2e for the public build of the committed snapshot (M2b.3a): the real
// exported analysis in frontend/snapshot/, built and served the way the public
// e2e builds the synthetic fixture (playwright.public.config.ts). No backend
// and no API. SNAPSHOT_DIR is "" (the default folder; a set value, even an
// empty one, also beats a .env file) and SNAPSHOT_ALLOW_FIXTURE is "" (so a
// fixture manifest would fail the build: proof the committed snapshot is not
// one). NEXT_PUBLIC_API_URL is the same canary: no request may reach it, and no
// built file may contain it. Run with `npm run test:e2e:snapshot`. It shares
// .next and out/ with every build and with the other e2e suites: run them one
// after the other.

import { defineConfig, devices } from "@playwright/test";

import { CANARY_API_URL, TEST_GITHUB_URL, TEST_SITE_URL } from "./e2e-public/fixture";

// Its own port (override with E2E_SNAPSHOT_PORT).
const PORT = Number.parseInt(process.env.E2E_SNAPSHOT_PORT ?? "", 10) || 3201;
const BUILD_OUTPUT = /build-output\.spec\.ts$/;

export default defineConfig({
  testDir: "./e2e-snapshot",
  outputDir: "./test-results/snapshot",
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
      SNAPSHOT_DIR: "",
      SNAPSHOT_ALLOW_FIXTURE: "",
      NEXT_PUBLIC_API_URL: CANARY_API_URL,
      // The public build requires both site settings (next.config.mjs).
      NEXT_PUBLIC_SITE_URL: TEST_SITE_URL,
      NEXT_PUBLIC_GITHUB_URL: TEST_GITHUB_URL,
    },
  },
});
