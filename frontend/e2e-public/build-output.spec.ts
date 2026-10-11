// Checks on the exported files (out/) after `npm run build:public` from the
// synthetic fixture. Project "build-output": runs once, with no browser.

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { CANARY_API_URL, FIXTURE_ABS, FIXTURE_ID, HTML_CHART, PNG_CHART } from "./fixture";

const OUT = path.join(__dirname, "..", "out");

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((rel) => statSync(path.join(dir, rel)).isFile())
    .sort();
}

test("no exported file contains localhost:8000, NEXT_PUBLIC_API_URL or the api-canary URL", () => {
  const needles = ["localhost:8000", "NEXT_PUBLIC_API_URL", new URL(CANARY_API_URL).hostname];
  const files = filesUnder(OUT);
  expect(files.length).toBeGreaterThan(0);
  const hits: string[] = [];
  for (const rel of files) {
    const text = readFileSync(path.join(OUT, rel), "latin1");
    for (const needle of needles) if (text.includes(needle)) hits.push(`${needle} in out/${rel}`);
  }
  expect(hits).toEqual([]);
});

test("out/analysis/ holds exactly the listed ids, one .html and one .txt each", () => {
  expect(readdirSync(path.join(OUT, "analysis")).sort()).toEqual([`${FIXTURE_ID}.html`, `${FIXTURE_ID}.txt`]);
});

test("out/demo/charts/ holds exactly the listed chart files, byte for byte", () => {
  const charts = path.join(OUT, "demo", "charts");
  expect(readdirSync(charts).sort()).toEqual([HTML_CHART, PNG_CHART].sort());
  for (const name of [PNG_CHART, HTML_CHART]) {
    expect(readFileSync(path.join(charts, name)).equals(readFileSync(path.join(FIXTURE_ABS, "charts", name))), name).toBe(true);
  }
});
