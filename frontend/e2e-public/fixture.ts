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

export const FIXTURE_ID = "00000000-0000-4000-a000-000000000001";
// A canonical id that is not in the fixture's manifest.
export const UNLISTED_ID = "00000000-0000-4000-a000-000000000002";
export const PNG_CHART = `${FIXTURE_ID}_histogram_fixture_value.png`;
export const HTML_CHART = `${FIXTURE_ID}_scatter_fixture_x_fixture_y.html`;

export const FIXTURE_ABS = path.join(__dirname, "..", FIXTURE_DIR);
export const FIXTURE = JSON.parse(
  readFileSync(path.join(FIXTURE_ABS, "analyses", `${FIXTURE_ID}.json`), "utf8"),
) as SnapshotAnalysis;
