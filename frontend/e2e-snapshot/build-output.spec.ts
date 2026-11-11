// Checks on the exported files (out/) after `npm run build:public` from the
// committed snapshot (frontend/snapshot/). Project "build-output": runs once,
// with no browser. out/analysis/<id>.txt is the page's RSC payload; the .html
// carries the same payload inline.

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { CANARY_API_URL, FIXTURE_ID, TEST_SITE_URL } from "../e2e-public/fixture";
import { BRAND_FILES, OLD_NAME, icoSizes, pngSize, robotsTxt, sitemapXml } from "../e2e-public/site";
import { findForeignUuids } from "../lib/snapshot-rules.mjs";
import { ANALYSIS, HIDDEN_STEMS, KEPT_CHARTS, MANIFEST, NOTE, PLOTLY, REAL_ID, SNAPSHOT_ABS } from "./snapshot";

const NOTICE = "third-party-notices.txt";

const OUT = path.join(__dirname, "..", "out");
const APP = path.join(__dirname, "..", "app");
const PAGE_FILES = [`analysis/${REAL_ID}.html`, `analysis/${REAL_ID}.txt`, "index.html", "index.txt"];

// Keys the export dropped (its report at STOP 1) that are not also published
// keys elsewhere; matched only as JSON keys, raw or escaped inside the HTML's
// inline payload, so the same words in prose do not count.
const DROPPED_KEYS = [
  "profile_report",
  "created_at",
  "executive_layer",
  "cleaning_methodology",
  "highest_pair",
  "highest_value",
  "rows_removed",
  "columns_removed",
  "descriptive_stats",
  "value_counts",
  "most_important_finding",
  "most_surprising_finding",
  "profiler_concerns_addressed",
  "self_evaluation_loops",
  "unmet_criteria",
  "excluded_columns",
  "time_series",
];

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((rel) => statSync(path.join(dir, rel)).isFile())
    .sort();
}

function hasJsonKey(text: string, key: string): boolean {
  return new RegExp(`\\\\?"${key}\\\\?":`).test(text);
}

test("the committed snapshot is the real export: one analysis, its 14 kept charts and plotly.min.js", () => {
  expect(MANIFEST).toEqual({ analyses: [{ id: REAL_ID, note: NOTE }] });
  expect(ANALYSIS.id).toBe(REAL_ID);
  expect(KEPT_CHARTS).toHaveLength(14);
  expect(filesUnder(SNAPSHOT_ABS)).toEqual(
    ["manifest.json", `analyses/${REAL_ID}.json`, ...KEPT_CHARTS.map((name) => `charts/${name}`), `charts/${PLOTLY}`].sort(),
  );
});

test("the notice ships with the site and names the bundle's own header", () => {
  const notice = readFileSync(path.join(OUT, NOTICE));
  expect(notice.equals(readFileSync(path.join(__dirname, "..", "public", NOTICE))), "out/ equals public/, byte for byte").toBe(true);
  const text = notice.toString("utf8");
  // The bundle's own header comment ("/**\n* plotly.js v2.30.0\n* Copyright ...\n...*/"),
  // so a regenerated bundle cannot leave the notice behind (tasks.md, M2c).
  const header = /^\/\*\*([\s\S]*?)\*\//.exec(readFileSync(path.join(SNAPSHOT_ABS, "charts", PLOTLY), "latin1"))?.[1] ?? "";
  const lines = header.split("\n").map((line) => line.replace(/^\s*\*\s?/, "").trim());
  const version = lines.find((line) => /^plotly\.js v\d/.test(line));
  const copyright = lines.find((line) => line.startsWith("Copyright"));
  expect(version, "the header's version line").toBeDefined();
  expect(copyright, "the header's copyright line").toBeDefined();
  expect(text).toContain(String(version));
  expect(text).toContain(String(copyright));
  // plotly.js's own LICENSE and the bundled components' notices.
  expect(text).toContain("Copyright (c) 2021 Plotly, Inc");
  expect(text).toContain("/*! ieee754. BSD-3-Clause License. Feross Aboukhadijeh <https://feross.org/opensource> */");
});

test("out/analysis/ holds exactly the real id, one .html and one .txt", () => {
  expect(readdirSync(path.join(OUT, "analysis")).sort()).toEqual([`${REAL_ID}.html`, `${REAL_ID}.txt`]);
});

test("out/robots.txt allows every page and points to the sitemap at the site's address", () => {
  expect(readFileSync(path.join(OUT, "robots.txt"), "utf8")).toBe(robotsTxt(TEST_SITE_URL));
});

test("out/sitemap.xml lists '/' and the real analysis at the site's address", () => {
  expect(readFileSync(path.join(OUT, "sitemap.xml"), "utf8")).toBe(sitemapXml([TEST_SITE_URL, `${TEST_SITE_URL}/analysis/${REAL_ID}`]));
});

test("the icons and the link-preview card ship byte for byte, at their sizes", () => {
  for (const name of BRAND_FILES) {
    expect(readFileSync(path.join(OUT, name)).equals(readFileSync(path.join(APP, name))), name).toBe(true);
  }
  expect(icoSizes(readFileSync(path.join(OUT, "favicon.ico")))).toEqual([16, 32, 48]);
  expect(pngSize(readFileSync(path.join(OUT, "apple-icon.png")))).toEqual({ width: 180, height: 180 });
  expect(pngSize(readFileSync(path.join(OUT, "opengraph-image.png")))).toEqual({ width: 1200, height: 630 });
});

test("out/demo/charts/ holds exactly frontend/snapshot/charts/, byte for byte: the 14 kept charts and plotly.min.js", () => {
  const charts = path.join(OUT, "demo", "charts");
  const expected = [...KEPT_CHARTS, PLOTLY].sort();
  expect(readdirSync(charts).sort()).toEqual(expected);
  for (const name of expected) {
    expect(readFileSync(path.join(charts, name)).equals(readFileSync(path.join(SNAPSHOT_ABS, "charts", name))), name).toBe(true);
  }
});

// localhost:3000 is Next's fallback when metadataBase is unset (the site's
// address makes every metadata URL absolute); the old name is gone (M2b.4a).
test("no exported file contains the fixture id, another UUID, localhost:8000, localhost:3000, NEXT_PUBLIC_API_URL, the api-canary URL or the old name", () => {
  const needles = [FIXTURE_ID, "localhost:8000", "localhost:3000", "NEXT_PUBLIC_API_URL", new URL(CANARY_API_URL).hostname, OLD_NAME];
  const files = filesUnder(OUT);
  expect(files.length).toBeGreaterThan(0);
  const hits: string[] = [];
  for (const rel of files) {
    const text = readFileSync(path.join(OUT, rel), "latin1");
    for (const needle of needles) if (text.includes(needle)) hits.push(`${needle} in out/${rel}`);
    for (const uuid of findForeignUuids(text, REAL_ID)) hits.push(`UUID ${uuid} in out/${rel}`);
  }
  expect(hits).toEqual([]);
});

test("no exported file names a hidden chart: not the pages, their RSC payloads, the charts or the scripts", () => {
  const files = filesUnder(OUT);
  // The pages and their payloads are among the files scanned.
  expect(files).toEqual(expect.arrayContaining(PAGE_FILES));
  const hits: string[] = [];
  for (const rel of files) {
    const text = readFileSync(path.join(OUT, rel), "latin1");
    for (const stem of HIDDEN_STEMS) if (text.includes(stem)) hits.push(`${stem} in out/${rel}`);
  }
  expect(hits).toEqual([]);
});

test("the pages and their RSC payloads carry no key the export dropped", () => {
  const hits: string[] = [];
  for (const rel of PAGE_FILES) {
    const text = readFileSync(path.join(OUT, rel), "utf8");
    for (const key of DROPPED_KEYS) if (hasJsonKey(text, key)) hits.push(`${key} in out/${rel}`);
  }
  expect(hits).toEqual([]);
  // The matcher finds a published key in both forms: the payload and the
  // HTML's inline copy of it.
  for (const rel of [`analysis/${REAL_ID}.html`, `analysis/${REAL_ID}.txt`]) {
    expect(hasJsonKey(readFileSync(path.join(OUT, rel), "utf8"), "statistical_methodology"), rel).toBe(true);
  }
});
