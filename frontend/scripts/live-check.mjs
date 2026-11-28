// The deployed site's statuses, types and headers, checked from the owner's
// Mac (M3b.1). Node's built-ins only. The expected values are literals, never
// read from frontend/vercel.json, which lib/vercel-config.test.mjs pins;
// e2e-snapshot/live.spec.ts runs this script against serve-static, which
// applies vercel.json, so the two cannot drift apart unseen.
//
// In frontend/:
//   node scripts/live-check.mjs https://<host> --protected <commit URL> <branch URL>
//   node scripts/live-check.mjs http://127.0.0.1:<port> --local
// The first checks the deployed site. <commit URL> and <branch URL> are the
// production deployment's two generated URLs (on its page in the dashboard):
// neither may serve the site to an anonymous request. The second checks a local
// stand-in, e2e-public/serve-static.mjs serving a build: what only the host
// does (HSTS, compression, cache-control) is reported as INFO, and the
// requests only the host can answer (http, /_src, /_logs, the protected URLs)
// are not sent.
//
// Requests go only to the given addresses (and, live, the site's own host over
// http), follow no redirect and get 30 s each; files whose body is not needed
// are asked for with HEAD, the large ones among them. One PASS, FAIL or INFO
// line per check, then LIVE CHECK PASS or LIVE CHECK FAIL (<n>): exit 0, or 1
// on any failure. A usage error, or a snapshot the checks cannot use, exits 2
// before any request.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const USAGE = [
  "usage: node scripts/live-check.mjs https://<host> --protected <commit URL> <branch URL>",
  "       node scripts/live-check.mjs http://127.0.0.1:<port> --local",
].join("\n");
const TIMEOUT_MS = 30_000;

// The two header sets frontend/vercel.json gives the site, as
// e2e-public/site.ts writes them (names in lower case): the page set everywhere
// but under /demo/charts/, the chart set there.
const PAGE_HEADERS = {
  "content-security-policy":
    "default-src 'self'; script-src 'self' 'unsafe-inline'; script-src-attr 'none'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "cross-origin-opener-policy": "same-origin",
};
const CHART_HEADERS = {
  "content-security-policy": "script-src 'self' 'unsafe-inline'; sandbox allow-scripts",
  "x-content-type-options": "nosniff",
  "x-robots-tag": "noindex",
  "referrer-policy": "no-referrer",
};
// The content types e2e-public/serve-static.mjs sends, which the public suite
// pins, with a second form where hosts are known to differ.
const TYPES = {
  html: ["text/html; charset=utf-8"],
  txt: ["text/plain; charset=utf-8"],
  xml: ["application/xml"],
  ico: ["image/x-icon", "image/vnd.microsoft.icon"],
  svg: ["image/svg+xml"],
  png: ["image/png"],
  js: ["application/javascript; charset=utf-8", "text/javascript; charset=utf-8"],
  css: ["text/css; charset=utf-8"],
  woff2: ["font/woff2"],
};

/**
 * A URL, or null when the value is not one.
 * @param {string} value
 * @returns {URL | null}
 */
function urlOrNull(value) {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/**
 * The command line, or what is wrong with it.
 * @param {string[]} args
 * @returns {{ base: URL, local: boolean, protectedUrls: URL[] } | string}
 */
function parseArgs(args) {
  const [baseArg, ...rest] = args;
  if (baseArg === undefined) return "give the site's address";
  const base = urlOrNull(baseArg);
  if (base === null || base.origin !== baseArg) {
    return `the site's address must be an origin alone, with no path or trailing slash: ${baseArg}`;
  }
  if (rest[0] === "--local") {
    if (rest.length !== 1) return "--local takes no other argument";
    if (base.protocol !== "http:" || base.hostname !== "127.0.0.1" || base.port === "") {
      return `--local needs http://127.0.0.1:<port>: ${baseArg}`;
    }
    return { base, local: true, protectedUrls: [] };
  }
  if (base.protocol !== "https:") return `the deployed site's address must use https: ${baseArg}`;
  if (rest[0] !== "--protected" || rest.length !== 3) return "the live check needs --protected <commit URL> <branch URL>";
  /** @type {URL[]} */
  const protectedUrls = [];
  for (const value of rest.slice(1)) {
    const url = urlOrNull(value);
    if (url === null || url.protocol !== "https:") return `a protected URL must be an https URL: ${value}`;
    if (url.host === base.host) return `a protected URL is a generated URL, not the site's own address: ${value}`;
    protectedUrls.push(url);
  }
  if (protectedUrls[0].host === protectedUrls[1].host) return "the commit URL and the branch URL must differ";
  return { base, local: false, protectedUrls };
}

/**
 * The first analysis in the committed snapshot, and its chart files. It throws
 * when either file cannot be read or parsed, or lacks what the checks use, so
 * that main() stops before any request.
 * @returns {{ id: string, charts: string[] }}
 */
function readSnapshot() {
  const manifest = JSON.parse(readFileSync(path.join(FRONTEND, "snapshot", "manifest.json"), "utf8"));
  const id = manifest.analyses[0].id;
  if (typeof id !== "string") throw new Error("manifest.json: the first analysis's id is not a string");
  const analysis = JSON.parse(readFileSync(path.join(FRONTEND, "snapshot", "analyses", `${id}.json`), "utf8"));
  const charts = analysis.chart_paths;
  if (!Array.isArray(charts) || !charts.every((name) => typeof name === "string")) {
    throw new Error(`analyses/${id}.json: chart_paths is not an array of strings`);
  }
  return { id, charts };
}

// The run's settings, which main() takes from the command line before the
// first request: the site's address, whether it is the local stand-in, and the
// origins a request may go to.
/** @type {URL} */
let BASE;
/** @type {boolean} */
let LOCAL;
/** @type {Set<string>} */
let ALLOWED;
let failures = 0;

/**
 * One line of the report.
 * @param {"PASS" | "FAIL" | "INFO"} kind
 * @param {string} check
 * @param {string} [detail]
 * @returns {void}
 */
function report(kind, check, detail = "") {
  if (kind === "FAIL") failures += 1;
  console.log(`${kind} ${check}${detail === "" ? "" : ` (${detail})`}`);
}

/**
 * PASS when ok, FAIL otherwise.
 * @param {boolean} ok
 * @param {string} check
 * @param {string} [detail]
 * @returns {void}
 */
function expectThat(ok, check, detail) {
  report(ok ? "PASS" : "FAIL", check, detail);
}

/**
 * What only the host does: PASS or FAIL on the deployed site, INFO against the
 * local stand-in, which does not do it.
 * @param {boolean} ok
 * @param {string} check
 * @param {string} [detail]
 * @returns {void}
 */
function expectOnHost(ok, check, detail) {
  report(LOCAL ? "INFO" : ok ? "PASS" : "FAIL", check, detail);
}

/**
 * Named headers and their values, for an INFO line.
 * @param {Headers} headers
 * @param {string[]} names
 * @returns {string}
 */
function describe(headers, names) {
  return names.map((name) => `${name} ${headers.get(name) ?? "(none)"}`).join("; ");
}

/**
 * Where a redirect points, without its query (it may carry a token).
 * @param {Headers} headers
 * @returns {string}
 */
function redirectTarget(headers) {
  const location = headers.get("location");
  if (location === null) return "no Location";
  const url = urlOrNull(location);
  return url === null ? `to ${location.split("?")[0]}` : `to ${url.origin}${url.pathname}`;
}

/**
 * One request to a given address: no redirect followed, TIMEOUT_MS at most,
 * the body read only when asked for and cancelled otherwise.
 * @param {URL} url
 * @param {{ method?: "GET" | "HEAD", read?: boolean, headers?: Record<string, string> }} [options]
 * @returns {Promise<{ status: number, headers: Headers, body: string }>}
 */
async function request(url, { method = "GET", read = false, headers = {} } = {}) {
  if (!ALLOWED.has(url.origin)) throw new Error(`refused: ${url.origin} is not one of the given addresses`);
  const response = await fetch(url, { method, headers, redirect: "manual", signal: AbortSignal.timeout(TIMEOUT_MS) });
  let body = "";
  if (read) body = await response.text();
  else await response.body?.cancel();
  return { status: response.status, headers: response.headers, body };
}

/**
 * e2e-public/site.ts's expectOneHeaderSet: every header of the set the path
 * takes, with that set's value, and none of the other set's own headers (so
 * no x-robots-tag on a page). Any other header is allowed, the host's own
 * among them (server, x-vercel-*, strict-transport-security, cache-control,
 * etag, age).
 * @param {string} pathname
 * @param {Headers} headers
 * @returns {void}
 */
function checkHeaderSet(pathname, headers) {
  const chart = pathname.startsWith("/demo/charts/");
  const [want, other] = chart ? [CHART_HEADERS, PAGE_HEADERS] : [PAGE_HEADERS, CHART_HEADERS];
  const wrong = Object.entries(want)
    .filter(([key, value]) => headers.get(key) !== value)
    .map(([key]) => key);
  const extra = Object.keys(other).filter((key) => !(key in want) && headers.get(key) !== null);
  const problems = [wrong.length > 0 ? `wrong or missing: ${wrong.join(", ")}` : "", extra.length > 0 ? `from the other set: ${extra.join(", ")}` : ""];
  expectThat(wrong.length === 0 && extra.length === 0, `${pathname}: the ${chart ? "chart" : "page"} header set`, problems.filter((p) => p !== "").join("; "));
}

/**
 * A file's status, content type and header set.
 * @param {string} pathname
 * @param {keyof typeof TYPES} kind
 * @param {{ status?: number, method?: "GET" | "HEAD", read?: boolean, headers?: Record<string, string> }} [options]
 * @returns {Promise<{ status: number, headers: Headers, body: string }>}
 */
async function checkFile(pathname, kind, { status = 200, method = "HEAD", read = false, headers = {} } = {}) {
  const response = await request(new URL(pathname, BASE), { method, read, headers });
  const type = response.headers.get("content-type") ?? "(none)";
  expectThat(response.status === status, `${pathname}: status ${status}`, `got ${response.status}`);
  expectThat(TYPES[kind].includes(type), `${pathname}: type ${TYPES[kind][0]}`, `got ${type}`);
  checkHeaderSet(pathname, response.headers);
  return response;
}

/**
 * Run one group of checks. An error inside it (a refused, failed or timed-out
 * request) becomes that group's FAIL line, and the next group runs.
 * @param {string} name
 * @param {() => Promise<void>} run
 * @returns {Promise<void>}
 */
async function group(name, run) {
  try {
    await run();
  } catch (error) {
    const cause = error instanceof Error && error.cause instanceof Error ? `; ${error.cause.message}` : "";
    report("FAIL", name, error instanceof Error ? `${error.name}: ${error.message}${cause}` : String(error));
  }
}

/**
 * Every check, in order, then the summary line.
 * @returns {Promise<number>} the exit code: 0 when every check passes, 1 on any
 *   failure, 2 for a usage error or a snapshot the checks cannot use (before any
 *   request)
 */
async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (typeof parsed === "string") {
    console.error(`live-check: ${parsed}\n${USAGE}`);
    return 2;
  }
  /** @type {{ id: string, charts: string[] }} */
  let snapshot;
  try {
    snapshot = readSnapshot();
  } catch (error) {
    console.error(`live-check: cannot read frontend/snapshot/: ${error instanceof Error ? error.message : String(error)}`);
    return 2;
  }
  BASE = parsed.base;
  LOCAL = parsed.local;
  const PROTECTED = parsed.protectedUrls;
  ALLOWED = new Set([BASE.origin, ...(LOCAL ? [] : [`http://${BASE.host}`, ...PROTECTED.map((url) => url.origin)])]);
  const ANALYSIS = `/analysis/${snapshot.id}`;

  // The pages, the 404 and the site's own files.
  let home = "";
  await group("/", async () => {
    const response = await checkFile("/", "html", { method: "GET", read: true, headers: { "accept-encoding": "br, gzip" } });
    home = response.body;
    const hsts = response.headers.get("strict-transport-security") ?? "(none)";
    expectOnHost(hsts.startsWith("max-age=63072000"), "/: HSTS max-age=63072000", hsts);
    const encoding = response.headers.get("content-encoding") ?? "(none)";
    expectOnHost(encoding === "br" || encoding === "gzip", "/: compressed (br or gzip)", encoding);
    report("INFO", "/: the host's headers", describe(response.headers, ["server", "x-vercel-cache", "cache-control", "etag", "age"]));
  });
  await group(ANALYSIS, async () => {
    await checkFile(ANALYSIS, "html");
  });
  await group("/no-such-page", async () => {
    const response = await checkFile("/no-such-page", "html", { status: 404, method: "GET", read: true });
    expectThat(response.body.includes("Page not found"), "/no-such-page: the site's 404 page");
  });
  /** @type {Array<[string, keyof typeof TYPES]>} */
  const SITE_FILES = [
    ["/robots.txt", "txt"],
    ["/sitemap.xml", "xml"],
    ["/favicon.ico", "ico"],
    ["/icon.svg", "svg"],
    ["/apple-icon.png", "png"],
    ["/opengraph-image.png", "png"],
    ["/third-party-notices.txt", "txt"],
    ["/index.txt", "txt"],
    [`${ANALYSIS}.txt`, "txt"],
  ];
  for (const [pathname, kind] of SITE_FILES) {
    await group(pathname, async () => {
      await checkFile(pathname, kind);
    });
  }

  // Next's hashed files: a chunk, the CSS and a font that "/" links to.
  /** @type {Array<[RegExp, keyof typeof TYPES]>} */
  const LINKED = [
    [/src="(\/_next\/static\/chunks\/[^"]+\.js)"/, "js"],
    [/href="(\/_next\/static\/css\/[^"]+\.css)"/, "css"],
    [/href="(\/_next\/static\/media\/[^"]+\.woff2)"/, "woff2"],
  ];
  for (const [pattern, kind] of LINKED) {
    const pathname = pattern.exec(home)?.[1];
    if (pathname === undefined) {
      report("FAIL", `a ${kind} file linked from /`, "none found");
      continue;
    }
    await group(pathname, async () => {
      const response = await checkFile(pathname, kind);
      const cacheControl = response.headers.get("cache-control") ?? "(none)";
      expectOnHost(cacheControl.includes("immutable"), `${pathname}: cache-control immutable`, cacheControl);
      report("INFO", `${pathname}: the host's headers`, describe(response.headers, ["access-control-allow-origin"]));
    });
  }

  // Every chart (HEAD: the bodies stay on the server), plotly's bundle, and a
  // chart that does not exist: the 404 page, under the chart set.
  for (const name of snapshot.charts) {
    const pathname = `/demo/charts/${name.replace(/\.html$/, "")}`;
    await group(pathname, async () => {
      const response = await checkFile(pathname, name.endsWith(".html") ? "html" : "png");
      if (name === snapshot.charts[0]) {
        report("INFO", `${pathname}: the host's headers`, describe(response.headers, ["cache-control", "etag", "access-control-allow-origin"]));
      }
    });
  }
  await group("/demo/charts/plotly.min.js", async () => {
    const response = await checkFile("/demo/charts/plotly.min.js", "js");
    report("INFO", "/demo/charts/plotly.min.js: the host's headers", describe(response.headers, ["cache-control", "etag", "content-length"]));
  });
  await group("/demo/charts/no-such-chart.png", async () => {
    const response = await checkFile("/demo/charts/no-such-chart.png", "html", { status: 404, method: "GET", read: true });
    expectThat(response.body.includes("Page not found"), "/demo/charts/no-such-chart.png: the site's 404 page");
  });

  // The routing rules.
  await group(`${ANALYSIS}/`, async () => {
    const response = await request(new URL(`${ANALYSIS}/`, BASE));
    const location = response.headers.get("location") ?? "(none)";
    expectThat(response.status === 308, `${ANALYSIS}/: status 308`, `got ${response.status}`);
    expectThat(location === ANALYSIS || location === new URL(ANALYSIS, BASE).href, `${ANALYSIS}/: Location ${ANALYSIS}`, `got ${location}`);
  });
  for (const pathname of [`${ANALYSIS}.html`, "/index.html"]) {
    await group(pathname, async () => {
      const response = await request(new URL(pathname, BASE));
      expectThat(response.status === 404, `${pathname}: status 404 (no .html URLs)`, `got ${response.status}`);
    });
  }
  await group("/_next/image", async () => {
    const pathname = "/_next/image?url=%2Fapple-icon.png&w=64&q=75";
    const response = await request(new URL(pathname, BASE));
    const type = response.headers.get("content-type") ?? "(none)";
    expectThat(!type.startsWith("image/"), `${pathname}: no image`, `${response.status} ${type}`);
  });

  // Only the host can answer these.
  if (!LOCAL) {
    await group("http", async () => {
      const response = await request(new URL(`http://${BASE.host}/`));
      const location = response.headers.get("location") ?? "(none)";
      const ok = (response.status === 301 || response.status === 308) && location.startsWith(`${BASE.origin}/`);
      expectThat(ok, "http: redirects to https", `${response.status} ${location}`);
    });
    for (const pathname of ["/_src", "/_logs"]) {
      await group(pathname, async () => {
        const response = await request(new URL(pathname, BASE));
        expectThat(response.status !== 200, `${pathname}: not served to an anonymous request`, `${response.status} ${redirectTarget(response.headers)}`);
      });
    }
    for (const url of PROTECTED) {
      await group(url.host, async () => {
        const response = await request(url, { read: true });
        const served = response.status === 200 && response.body.includes("Omnalynt");
        expectThat(!served, `${url.host}: does not serve the site to an anonymous request`, `${response.status} ${redirectTarget(response.headers)}`);
      });
    }
  }

  console.log(failures === 0 ? "LIVE CHECK PASS" : `LIVE CHECK FAIL (${failures})`);
  return failures === 0 ? 0 : 1;
}

// No process.exit(): it can drop lines still on their way to a pipe (Node's
// process docs). The exit code is set, and the script ends on its own.
process.exitCode = await main();
