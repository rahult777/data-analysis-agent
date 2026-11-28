// frontend/vercel.json (M2b.4c; owner rulings Q5, Q13 and Q14): the public
// build on Vercel's Next.js preset, a trailing slash dropped with a 308, and
// two disjoint header sets, the page set everywhere but under /demo/charts/
// and the chart set there. Since M3b.1 (ruling Q4 of the M3b evaluation) the
// install takes the lock exactly and runs no install script, the build command
// prints the Node and npm versions and VERCEL before the public build, and only
// main deploys. The sources are matched as Vercel matches them
// (lib/vercel-headers.mjs: next's bundled path-to-regexp, case-sensitive). The
// ten paths are the M2b.4 evaluation's (report M10). The expected values are
// literals, never read from the file under test.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { headersFor, vercelHeaderRules } from "./vercel-headers.mjs";

const CONFIG = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));

const PAGE_SOURCE = "/((?!demo/charts/).*)";
const CHART_SOURCE = "/demo/charts/(.*)";
const PAGE_HEADERS = [
  {
    key: "Content-Security-Policy",
    value:
      "default-src 'self'; script-src 'self' 'unsafe-inline'; script-src-attr 'none'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];
const CHART_HEADERS = [
  { key: "Content-Security-Policy", value: "script-src 'self' 'unsafe-inline'; sandbox allow-scripts" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Robots-Tag", value: "noindex" },
  { key: "Referrer-Policy", value: "no-referrer" },
];

const ID = "77faa166-668b-4001-92e0-94e037de7e3b";
// Each path, and the one source that must match it.
const PATHS = [
  ["/", PAGE_SOURCE],
  [`/analysis/${ID}`, PAGE_SOURCE],
  ["/404", PAGE_SOURCE],
  [`/demo/charts/${ID}_histogram_revenue.png`, CHART_SOURCE],
  ["/demo/charts/plotly.min.js", CHART_SOURCE],
  ["/demo/charts/", CHART_SOURCE],
  ["/demo/chartsX", PAGE_SOURCE],
  ["/_next/static/chunks/main-app.js", PAGE_SOURCE],
  ["/opengraph-image.png", PAGE_SOURCE],
  ["/DEMO/charts/x", PAGE_SOURCE],
];

describe("frontend/vercel.json", () => {
  it("uses the Next.js preset and drops a trailing slash, and sets nothing beyond its commands, Git deploys and headers", () => {
    assert.deepEqual(Object.keys(CONFIG).sort(), ["buildCommand", "framework", "git", "headers", "installCommand", "trailingSlash"]);
    assert.equal(CONFIG.framework, "nextjs");
    assert.equal(CONFIG.trailingSlash, false);
  });

  // Vercel runs both commands with `sh -c` (the Next builder's execCommand), so
  // the build log shows the Node and npm versions, then VERCEL=1 when Vercel
  // exposes its system variables (the SNAPSHOT_DIR guard relies on it) or
  // VERCEL=unset when it does not, then the public build.
  it("installs the locked tree without install scripts, prints node, npm and VERCEL before the public build, and deploys main only", () => {
    assert.equal(CONFIG.installCommand, "npm ci --ignore-scripts");
    assert.equal(CONFIG.buildCommand, "node -v && npm -v && echo VERCEL=${VERCEL:-unset} && npm run build:public");
    assert.deepEqual(CONFIG.git, { deploymentEnabled: { main: true, "**": false } });
  });

  it("has two header rules, the page set and then the chart set", () => {
    assert.deepEqual(CONFIG.headers, [
      { source: PAGE_SOURCE, headers: PAGE_HEADERS },
      { source: CHART_SOURCE, headers: CHART_HEADERS },
    ]);
  });

  it("matches each of the ten paths with exactly one rule and gives it that rule's headers", () => {
    const rules = vercelHeaderRules(CONFIG);
    for (const [path, source] of PATHS) {
      assert.deepEqual(
        rules.filter((rule) => rule.matcher.test(path)).map((rule) => rule.source),
        [source],
        path,
      );
      assert.deepEqual(headersFor(rules, path), source === PAGE_SOURCE ? PAGE_HEADERS : CHART_HEADERS, path);
    }
  });
});
