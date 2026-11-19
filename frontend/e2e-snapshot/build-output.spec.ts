// Checks on the exported files (out/) after `npm run build:public` from the
// committed snapshot (frontend/snapshot/). Project "build-output": runs once,
// with no browser. out/analysis/<id>.txt is the page's RSC payload; the .html
// carries the same payload inline.

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { clientMarkerHits, markersMissingFromSources } from "../e2e-public/client-markers";
import { exactFiles, unexpectedFiles } from "../e2e-public/export-files";
import { CANARY_API_URL, FIXTURE_ID, TEST_GITHUB_URL, TEST_SITE_URL } from "../e2e-public/fixture";
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

// The full license text of every component the bundle's own notices name
// (plotly.min.js.LICENSE.txt; M3a; docs/infrastructure.md, "The third-party
// notice"), in the notice's order: each sits verbatim between two lines of
// eight hyphens, under its section's heading line (the line above the one that
// leads into it), and is pinned by the sha256 of the license file it comes from.
// native-promise-only ships no license file: its text is reconstructed, the
// standard MIT text with its header's holder, and the notice says so.
const LICENSE_TEXTS: ReadonlyArray<readonly [string, string]> = [
  ["polybooljs 1.2.0 (MIT)", "6a3969e97bc3b992c17bfdcd6fcabd9b5688650cc0078235d512c014e86b716e"],
  ["object-assign 4.1.1 (MIT)", "6fb9754611c20f6649f68805e8c990e83261f29316e29de9e6cedae607b8634c"],
  ["is-buffer (MIT)", "c7cc929b57080f4b9d0c6cf57669f0463fc5b39906344dfc8d3bc43426b30eac"],
  ["buffer (MIT)", "06bafa45fdad2579ba0e43b0c9b2c6290287c99c4203c300254a462b38a307f6"],
  ["pad-left (MIT)", "3672fb6ef1c214578dfee689643516c2685f61ab08d130517ca8ea24f383a840"],
  ["repeat-string (MIT)", "3672fb6ef1c214578dfee689643516c2685f61ab08d130517ca8ea24f383a840"],
  ["native-promise-only 0.8.1 (MIT)", "ee6661307ebbac585d4574a87a18577b69f86326c2c4f2d1902ad0f497909b50"],
  ["ieee754 1.2.1 (BSD-3-Clause)", "18d45466ba3253deae04667e267a91ea8de8548f18c1125264d1c9db28194cc1"],
  ["safe-buffer 5.2.1 (MIT)", "c7cc929b57080f4b9d0c6cf57669f0463fc5b39906344dfc8d3bc43426b30eac"],
];

test("the notice carries the full license text of every component the bundle's notices name, verbatim, under its heading", () => {
  const notice = readFileSync(path.join(__dirname, "..", "public", NOTICE), "utf8");
  const parts = notice.split("\n--------\n");
  const texts = parts.filter((_, index) => index % 2 === 1);
  const headings = parts.filter((_, index) => index % 2 === 0).slice(0, texts.length).map((part) => {
    const lines = part.split("\n");
    return lines[lines.length - 2];
  });
  expect(headings).toEqual(LICENSE_TEXTS.map(([heading]) => heading));
  expect(texts.map((text) => createHash("sha256").update(`${text}\n`).digest("hex"))).toEqual(LICENSE_TEXTS.map(([, sha256]) => sha256));
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

// The deployed build ships no axios and none of lib/api.ts's code (M3a): this
// suite builds the committed snapshot, which is what Vercel deploys. The
// markers and their source-first control are shared with the public suite
// (e2e-public/client-markers.ts).
test("no client script carries axios or lib/api.ts's code", () => {
  expect(markersMissingFromSources(path.join(__dirname, "..")), "markers missing from their sources").toEqual([]);
  const { scripts, hits } = clientMarkerHits(path.join(OUT, "_next", "static"));
  expect(scripts, "client scripts").toBeGreaterThan(0);
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

// Every exported file is expected (M3a; the list and patterns are shared with
// the public suite, e2e-public/export-files.ts): the exact pages, site files
// and charts, Next's hashed files by pattern, and never a source map, a dotfile
// or an .env-like file. A file put in public/ fails here until it is listed.
test("out/ holds exactly the expected files: the pages, the site's own files, the charts and Next's hashed files", () => {
  const files = filesUnder(OUT);
  const exact = exactFiles([REAL_ID], [...KEPT_CHARTS, PLOTLY]);
  expect(exact.filter((rel) => !files.includes(rel)), "missing").toEqual([]);
  expect(unexpectedFiles(files, exact), "unexpected").toEqual([]);
});
