// Checks on the exported files (out/) after `npm run build:public` from the
// synthetic fixture. Project "build-output": runs once, with no browser.

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { CANARY_API_URL, FIXTURE_ABS, FIXTURE_ID, HTML_CHART, PLOTLY, PNG_CHART, TEST_GITHUB_URL, TEST_SITE_URL } from "./fixture";
import { BRAND_FILES, OLD_NAME, icoSizes, pngSize, robotsTxt, sitemapXml } from "./site";

const OUT = path.join(__dirname, "..", "out");
const APP = path.join(__dirname, "..", "app");

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((rel) => statSync(path.join(dir, rel)).isFile())
    .sort();
}

// localhost:3000 is Next's fallback when metadataBase is unset (the site's
// address makes every metadata URL absolute); the old name is gone (M2b.4a).
test("no exported file contains localhost:8000, localhost:3000, NEXT_PUBLIC_API_URL, the api-canary URL or the old name", () => {
  const needles = ["localhost:8000", "localhost:3000", "NEXT_PUBLIC_API_URL", new URL(CANARY_API_URL).hostname, OLD_NAME];
  const files = filesUnder(OUT);
  expect(files.length).toBeGreaterThan(0);
  const hits: string[] = [];
  for (const rel of files) {
    const text = readFileSync(path.join(OUT, rel), "latin1");
    for (const needle of needles) if (text.includes(needle)) hits.push(`${needle} in out/${rel}`);
  }
  expect(hits).toEqual([]);
});

// lib/site.ts is for server code only (owner ruling, 2026-11-11): a client
// component that imported it would compile the settings into its bundle. The
// pages' HTML and RSC payloads do carry the addresses; the scripts must not.
test("no client script or style carries a site setting: neither address is in out/_next/static", () => {
  const dir = path.join(OUT, "_next", "static");
  const files = filesUnder(dir);
  expect(files.filter((rel) => rel.endsWith(".js")).length, "client scripts").toBeGreaterThan(0);
  const hits: string[] = [];
  for (const rel of files) {
    const text = readFileSync(path.join(dir, rel), "latin1");
    for (const needle of [TEST_SITE_URL, new URL(TEST_SITE_URL).hostname, TEST_GITHUB_URL]) if (text.includes(needle)) hits.push(`${needle} in out/_next/static/${rel}`);
  }
  expect(hits).toEqual([]);
  // The check sees the addresses where they belong: the page itself.
  const home = readFileSync(path.join(OUT, "index.html"), "utf8");
  expect(home.includes(TEST_SITE_URL), "the site's address is in index.html").toBe(true);
  expect(home.includes(TEST_GITHUB_URL), "the repository's address is in index.html").toBe(true);
});

test("out/analysis/ holds exactly the listed ids, one .html and one .txt each", () => {
  expect(readdirSync(path.join(OUT, "analysis")).sort()).toEqual([`${FIXTURE_ID}.html`, `${FIXTURE_ID}.txt`]);
});

test("out/robots.txt allows every page and points to the sitemap at the site's address", () => {
  expect(readFileSync(path.join(OUT, "robots.txt"), "utf8")).toBe(robotsTxt(TEST_SITE_URL));
});

test("out/sitemap.xml lists '/' and the analysis at the site's address", () => {
  expect(readFileSync(path.join(OUT, "sitemap.xml"), "utf8")).toBe(
    sitemapXml([TEST_SITE_URL, `${TEST_SITE_URL}/analysis/${FIXTURE_ID}`]),
  );
});

test("the icons and the link-preview card ship byte for byte, at their sizes", () => {
  for (const name of BRAND_FILES) {
    expect(readFileSync(path.join(OUT, name)).equals(readFileSync(path.join(APP, name))), name).toBe(true);
  }
  expect(icoSizes(readFileSync(path.join(OUT, "favicon.ico")))).toEqual([16, 32, 48]);
  expect(pngSize(readFileSync(path.join(OUT, "apple-icon.png")))).toEqual({ width: 180, height: 180 });
  expect(pngSize(readFileSync(path.join(OUT, "opengraph-image.png")))).toEqual({ width: 1200, height: 630 });
});

test("the third-party notice in public/ ships as out/third-party-notices.txt, byte for byte", () => {
  const notice = "third-party-notices.txt";
  expect(readFileSync(path.join(OUT, notice)).equals(readFileSync(path.join(__dirname, "..", "public", notice)))).toBe(true);
});

test("out/demo/charts/ holds exactly the listed chart files and plotly.min.js, byte for byte", () => {
  const charts = path.join(OUT, "demo", "charts");
  expect(readdirSync(charts).sort()).toEqual([HTML_CHART, PNG_CHART, PLOTLY].sort());
  for (const name of [PNG_CHART, HTML_CHART, PLOTLY]) {
    expect(readFileSync(path.join(charts, name)).equals(readFileSync(path.join(FIXTURE_ABS, "charts", name))), name).toBe(true);
  }
});
