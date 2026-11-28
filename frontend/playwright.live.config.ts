// The snapshot suite's browser specs against a running site, with no web
// server of its own (M3b.1): the deployed site, or a local stand-in
// (e2e-public/serve-static.mjs serving a build made with the real settings).
// E2E_LIVE_URL is the site to test; E2E_SITE_URL and E2E_GITHUB_URL are the
// two settings its build was made with, which the specs then expect (while
// E2E_LIVE_URL is set, e2e-public/fixture.ts takes them from there, and the
// other three configs refuse to start). It refuses to start unless all three
// are set, each in its form (below). Left out: build-output.spec.ts, which
// reads out/, and live.spec.ts, which needs the snapshot suite's own server.
// In frontend/:
//   E2E_LIVE_URL=https://<host> E2E_SITE_URL=https://<host> \
//   E2E_GITHUB_URL=https://github.com/<owner>/<repo> \
//   npx playwright test -c playwright.live.config.ts

import { defineConfig, devices } from "@playwright/test";

const REQUIRED = ["E2E_LIVE_URL", "E2E_SITE_URL", "E2E_GITHUB_URL"];
const missing = REQUIRED.filter((name): boolean => !process.env[name]);
if (missing.length > 0) {
  throw new Error(
    `playwright.live.config.ts: set ${missing.join(", ")}: E2E_LIVE_URL is the site to test, E2E_SITE_URL and E2E_GITHUB_URL the two settings its build was made with.`,
  );
}
// Each variable's form, by patterns of this file's own (not
// lib/site-settings.mjs's checks, which the public build runs): a malformed
// value would make the specs fail without naming it. E2E_LIVE_URL may be a
// local stand-in over http; the two settings must have the shape of the values
// a public build takes.
const FORMS: Array<[string, RegExp, string]> = [
  ["E2E_LIVE_URL", /^https?:\/\/[a-z0-9.-]+(?::\d+)?$/, "an http or https origin: http(s)://<host>, with or without a port, and no path or trailing slash"],
  ["E2E_SITE_URL", /^https:\/\/[a-z0-9-]+(?:\.[a-z0-9-]+)+$/, "an https origin: https://<host>, with no port, path or trailing slash"],
  ["E2E_GITHUB_URL", /^(?!.*\.git$)https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/, "https://github.com/<owner>/<repo>, with nothing after it and no .git"],
];
const malformed = FORMS.filter(([name, pattern]): boolean => !pattern.test(process.env[name] ?? "")).map(
  ([name, , form]): string => `playwright.live.config.ts: ${name} must be ${form}; got ${JSON.stringify(process.env[name])}`,
);
if (malformed.length > 0) throw new Error(malformed.join("\n"));

export default defineConfig({
  testDir: "./e2e-snapshot",
  testIgnore: [/\/build-output\.spec\.ts$/, /\/live\.spec\.ts$/],
  outputDir: "./test-results/live",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_LIVE_URL,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "mobile-320", use: { ...devices["Desktop Chrome"], viewport: { width: 320, height: 800 } } },
    { name: "desktop-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
  ],
});
