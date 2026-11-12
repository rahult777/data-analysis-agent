// The synthetic snapshot the public e2e builds the site from
// (e2e/fixtures/snapshot/, marked "fixture": true), and the values the tests
// expect from it.

import { readFileSync } from "node:fs";
import path from "node:path";

import type { SnapshotAnalysis } from "../lib/types";

export const FIXTURE_DIR = "e2e/fixtures/snapshot";
// NEXT_PUBLIC_API_URL for the public build: no request may reach it, and no
// built file may contain it.
export const CANARY_API_URL = "http://api-canary.invalid";
// The two site settings the public build requires (next.config.mjs): an RFC
// 2606 address and a fictional repository, never fetched.
export const TEST_SITE_URL = "https://omnalynt.example";
export const TEST_GITHUB_URL = "https://github.com/e2e-owner/e2e-repo";
// The owner's profile the footer links to, which the site derives from the
// repository (lib/site-settings.mjs githubProfileUrl): an independent literal.
export const TEST_GITHUB_PROFILE_URL = "https://github.com/e2e-owner";

export const FIXTURE_ID = "00000000-0000-4000-a000-000000000001";
// The "About this example" note every fixture manifest carries: an independent
// literal, never read from the manifest. No "upload": the public analysis page
// carries no upload wording (analysis.spec.ts).
export const FIXTURE_NOTE = "Synthetic note for the public e2e fixture. It describes no real data.";
// A canonical id that is not in the fixture's manifest.
export const UNLISTED_ID = "00000000-0000-4000-a000-000000000002";
export const PNG_CHART = `${FIXTURE_ID}_histogram_fixture_value.png`;
export const HTML_CHART = `${FIXTURE_ID}_scatter_fixture_x_fixture_y.html`;
// The fixture's stand-in for plotly's bundle: the snapshot rules require
// plotly.min.js beside an HTML chart (M2b.3a).
export const PLOTLY = "plotly.min.js";

export const FIXTURE_ABS = path.join(__dirname, "..", FIXTURE_DIR);
export const FIXTURE = JSON.parse(
  readFileSync(path.join(FIXTURE_ABS, "analyses", `${FIXTURE_ID}.json`), "utf8"),
) as SnapshotAnalysis;
