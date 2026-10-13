// Unit tests for scripts/export-snapshot.mjs (M2b.3a): the export of a saved
// analysis from a local, read-only backend into frontend/snapshot/. Every
// test runs against a fake backend on 127.0.0.1 (node:http) and writes only
// into temporary folders. Run with `npm run test:unit`. Never put this file
// under e2e/, e2e-public/ or e2e-snapshot/: Playwright's default test pattern
// matches *.test.mjs.

import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { projectPublished, readSnapshot } from "../lib/snapshot-rules.mjs";
import * as exporter from "./export-snapshot.mjs";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ID = "00000000-0000-4000-a000-000000000001";
const OTHER_ID = "00000000-0000-4000-a000-000000000002";
const PNG = `${ID}_histogram_fixture_value.png`;
const HIDDEN = `${ID}_barchart_customer_id.png`;
const HTML = `${ID}_scatter_fixture_x_fixture_y.html`;
const PNG_BYTES = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.from("synthetic png")]);
const SHARED_TAG = '<script charset="utf-8" src="plotly.min.js"></script>';
const HTML_TEXT = `<!doctype html><html><head><meta charset="utf-8" /></head><body><div id="chart"></div>${SHARED_TAG}<script type="text/javascript">/* ${ID} */</script></body></html>`;
const PLOTLY_TEXT = "/**\n* plotly.js v0.0.0 stand-in for the export tests: not plotly\n*/\n";
const sha256 = (data) => crypto.createHash("sha256").update(data).digest("hex");
const PLOTLY = { plotlySha256: sha256(PLOTLY_TEXT), plotlySize: Buffer.byteLength(PLOTLY_TEXT) };

// What GET /api/analysis/{id} returns for a finished run: published keys plus
// keys the page never reads, a derived summary count of -1 (cleaning added a
// column), and a path and an email in a dropped field.
function rawAnalysis() {
  return {
    id: ID,
    filename: "synthetic_export.csv",
    status: "complete",
    created_at: "2026-10-03T08:00:00+00:00",
    row_count: 4,
    column_count: 2,
    data_quality_score: 0.5,
    profile_report: { domain_hypothesis: "Synthetic", source_note: "read from /Users/someone/data/synthetic.csv by owner@example.com" },
    cleaning_report: {
      decisions: [{ column_name: "fixture_x", issue: "Synthetic issue.", action: "Synthetic action.", reason: "Synthetic reason." }],
      summary: { rows_before: 4, rows_after: 3, rows_removed: 1, columns_before: 2, columns_after: 3, columns_removed: -1 },
    },
    cleaning_decisions: [{ column_name: "fixture_x", issue: "Synthetic issue.", action: "Synthetic action.", reason: "Synthetic reason." }],
    analysis_report: {
      descriptive_stats: {},
      chart_paths: [PNG, HIDDEN, HTML],
      correlation_matrix: {
        matrix: { fixture_x: { fixture_x: 1, fixture_y: 0.08 }, fixture_y: { fixture_x: 0.08, fixture_y: 1 } },
        strong_pairs: [],
        highest_pair: ["fixture_x", "fixture_y"],
        highest_value: 0.08,
      },
    },
    insight_report: {
      analyst_layer: { narrative: "Synthetic narrative about the fixture: r = 0.08, units_sold/discount_pct and/or Y/N.", chart_references: [PNG] },
      open_questions: [{ question: "Synthetic question?", why_unanswerable: "Synthetic.", what_data_would_answer: "Synthetic." }],
      technical_layer: {
        statistical_methodology: "Synthetic methodology; available data: the Cleaner's table.",
        code_blocks: ["print('synthetic')"],
        limitations: "Synthetic limitations ($2,059–$750,000).",
        sophistication_suggestions: "Synthetic suggestions.",
        self_evaluation_notes: "Synthetic notes.",
        lead_override_note: null,
        cleaning_methodology: "Synthetic cleaning methodology.",
      },
      executive_layer: { bullets: [] },
      user_question_addressed: null,
      data_quality_score: 0.5,
    },
    executive_summary: { bullets: [{ finding: "Synthetic finding.", context: "Synthetic context.", recommended_action: "Synthetic action." }] },
    chart_paths: [PNG, HIDDEN, HTML],
  };
}

const STATUS = { analysis_id: ID, status: "complete", current_agent: null, progress_pct: 100.0, error_message: null, pause_data: null };

function routesFor(raw) {
  return {
    [`/api/analysis/${ID}/status`]: { type: "application/json", body: STATUS },
    [`/api/analysis/${ID}`]: { type: "application/json", body: raw },
    [`/api/analysis/${ID}/charts`]: { type: "application/json", body: { chart_paths: raw.chart_paths } },
    [`/charts/${PNG}`]: { type: "image/png", body: PNG_BYTES },
    [`/charts/${HIDDEN}`]: { type: "image/png", body: PNG_BYTES },
    [`/charts/${HTML}`]: { type: "text/html; charset=utf-8", body: HTML_TEXT },
    "/charts/plotly.min.js": { type: "text/javascript; charset=utf-8", body: PLOTLY_TEXT },
  };
}

const servers = [];
const tempRoots = [];
after(async () => {
  await Promise.all(servers.map((server) => server.close()));
  for (const root of tempRoots) fs.rmSync(root, { recursive: true, force: true });
});

// A fake backend on 127.0.0.1. A route is { status, type, body, headers,
// delayMs, chunked }; anything unrouted is a 404. `requests` logs every URL.
async function fakeBackend({ raw = rawAnalysis(), routes = {} } = {}) {
  const table = { ...routesFor(raw), ...routes };
  const requests = [];
  const server = http.createServer((req, res) => {
    requests.push(req.url);
    const route = table[req.url ?? ""];
    if (!route) {
      res.writeHead(404, { "content-type": "application/json" }).end('{"detail":"Not Found"}');
      return;
    }
    const { status = 200, type, body = "", headers = {}, delayMs = 0, chunked = false } = route;
    const send = () => {
      if (res.destroyed) return;
      const buf = Buffer.isBuffer(body) ? body : Buffer.from(typeof body === "string" ? body : JSON.stringify(body));
      res.writeHead(status, { "content-type": type, ...(chunked ? {} : { "content-length": buf.length }), ...headers });
      if (chunked) {
        res.write(buf.subarray(0, Math.ceil(buf.length / 2)));
        res.end(buf.subarray(Math.ceil(buf.length / 2)));
      } else {
        res.end(buf);
      }
    };
    if (delayMs) setTimeout(send, delayMs);
    else send();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = /** @type {import("node:net").AddressInfo} */ (server.address());
  const close = () => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  };
  const handle = { base: new URL(`http://127.0.0.1:${port}`), requests, close };
  servers.push(handle);
  return handle;
}

function tempFrontend() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "export-snapshot-"));
  tempRoots.push(root);
  return root;
}

function runExport(backend, options = {}) {
  return exporter.exportSnapshot({
    id: ID,
    baseUrl: backend.base,
    hide: [HIDDEN],
    frontendDir: options.frontendDir ?? tempFrontend(),
    timeoutMs: 2000,
    log: () => {},
    ...PLOTLY,
    ...options,
  });
}

// Every file under dir, relative, sorted.
function filesUnder(dir) {
  return fs
    .readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((rel) => fs.statSync(path.join(dir, rel)).isFile())
    .sort();
}

function nothingWritten(root) {
  assert.equal(fs.existsSync(path.join(root, "snapshot")), false, "no snapshot/");
  assert.equal(fs.existsSync(path.join(root, ".snapshot-export")), false, "no temporary folder");
}

// Expect the export to fail with a message matching `pattern` and to write nothing.
async function expectRefused(backend, pattern, options = {}) {
  const frontendDir = options.frontendDir ?? tempFrontend();
  await assert.rejects(runExport(backend, { ...options, frontendDir }), (error) => {
    assert.equal(error.name, "ExportError", String(error));
    assert.match(error.message, pattern);
    return true;
  });
  nothingWritten(frontendDir);
}

describe("parseArgs", () => {
  const BASE = "http://127.0.0.1:8000";

  it("reads the id, the base URL and every --hide", () => {
    const args = exporter.parseArgs([ID, BASE, "--hide", HIDDEN, "--hide", PNG]);
    assert.equal(args.id, ID);
    assert.equal(args.baseUrl.href, `${BASE}/`);
    assert.deepEqual(args.hide, [HIDDEN, PNG]);
    assert.deepEqual(exporter.parseArgs([ID, "http://localhost:8000"]).hide, []);
    assert.equal(exporter.parseArgs([ID, "http://[::1]:8000"]).baseUrl.hostname, "[::1]");
  });

  it("refuses an id that is not a lowercase canonical UUID", () => {
    for (const id of [ID.toUpperCase(), `{${ID}}`, ID.replace(/-/g, ""), ID.slice(1), "x"]) {
      assert.throws(() => exporter.parseArgs([id, BASE]), { name: "UsageError", message: /lowercase canonical UUID/ });
    }
  });

  it("refuses a base URL that is not plain http on a loopback host", () => {
    for (const base of [
      "https://127.0.0.1:8000",
      "http://example.com:8000",
      "http://10.0.0.5:8000",
      "http://127.0.0.2:8000",
      "http://user:secret@127.0.0.1:8000",
      "http://127.0.0.1:8000/api",
      "http://127.0.0.1:8000/?x=1",
      "http://127.0.0.1:8000/#x",
      "127.0.0.1:8000",
    ]) {
      assert.throws(() => exporter.parseArgs([ID, base]), { name: "UsageError" }, base);
    }
  });

  it("refuses a missing or extra argument, a bad --hide and any other option (there is no --replace)", () => {
    for (const argv of [
      [],
      [ID],
      [ID, BASE, "extra"],
      [ID, BASE, "--hide"],
      [ID, BASE, "--hide", HIDDEN, "--hide", HIDDEN],
      [ID, BASE, "--hide", "../x.png"],
      [ID, BASE, "--hide", "plotly.min.js"],
      [ID, BASE, "--replace"],
      [ID, BASE, `--hide=${HIDDEN}`],
    ]) {
      assert.throws(() => exporter.parseArgs(argv), { name: "UsageError" }, JSON.stringify(argv));
    }
  });
});

describe("scanText (the exact scan patterns)", () => {
  it("finds each kind of leak", () => {
    const cases = {
      "/Users/someone/data/synthetic.csv": "absolute path",
      "see /var/folders/x/y": "absolute path",
      "~/Backups/data": "home path",
      "C:\\data\\x.csv": "Windows path",
      "https://example.com/x": "URL",
      "s3://bucket/key": "URL",
      "mailto:someone": "mailto, javascript or file URI",
      "javascript:alert(1)": "mailto, javascript or file URI",
      "file:/etc/x": "mailto, javascript or file URI",
      "data:text/html;base64,AAAA": "data URI",
      "owner@example.com": "email",
      "sk-ant-api03-abc": "key-like string",
      "sb_secret_abc": "key-like string",
      "lsv2_pt_abc": "key-like string",
      "ghp_abc": "key-like string",
      // AWS's full access key ID format, built at runtime: a contiguous one in
      // the source would trip secret scanning on push.
      ["AKIA" + "ABCDEFGHIJKLMNOP"]: "key-like string",
      "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0": "key-like string",
      "-----BEGIN PRIVATE KEY-----": "key-like string",
      "abcdefghijklmnopqrst.supabase.co": "service host",
      "mcp.supabase.com": "service host",
      "project_ref": "service host",
      "api.anthropic.com": "service host",
      "smith.langchain.com": "service host",
      "localhost": "local host",
      "127.0.0.1": "local host",
      "[::1]": "local host",
      "10.0.0.5": "IPv4 address",
    };
    for (const [text, pattern] of Object.entries(cases)) {
      assert.ok(
        exporter.scanText(`before ${text} after`).some((hit) => hit.pattern === pattern),
        `${JSON.stringify(text)} should hit ${pattern}; got ${JSON.stringify(exporter.scanText(text))}`,
      );
    }
  });

  it("ignores ordinary analysis text", () => {
    for (const text of [
      "available data: the Cleaner",
      "units_sold/discount_pct and/or Y/N, N/A, 1/2, 50/50, mg/dL",
      "$2,059–$750,000 (r = 0.08), skewness -0.169, 2026-10-03",
      "messy_data.csv",
      "Matplotlib version3.8.0",
      "e.g., 'median (4.7 mg/dL)'",
      "notes: 'Needs review' 11 (10.9%)",
    ]) {
      assert.deepEqual(exporter.scanText(text), [], text);
    }
  });
});

describe("exportSnapshot", () => {
  it("writes exactly the published projection, the kept charts and plotly.min.js, then moves the folder into place", async () => {
    const backend = await fakeBackend();
    const frontendDir = tempFrontend();
    const report = await runExport(backend, { frontendDir });
    const snapshotDir = path.join(frontendDir, "snapshot");
    assert.deepEqual(filesUnder(snapshotDir), ["analyses/" + `${ID}.json`, `charts/${HTML}`, `charts/${PNG}`, "charts/plotly.min.js", "manifest.json"].sort());
    assert.equal(fs.existsSync(path.join(frontendDir, ".snapshot-export")), false);

    const expected = projectPublished({ ...rawAnalysis(), chart_paths: [PNG, HTML] });
    assert.equal(fs.readFileSync(path.join(snapshotDir, "analyses", `${ID}.json`), "utf8"), `${JSON.stringify(expected, null, 2)}\n`);
    assert.equal(fs.readFileSync(path.join(snapshotDir, "manifest.json"), "utf8"), `${JSON.stringify({ analyses: [{ id: ID }] }, null, 2)}\n`);
    assert.ok(fs.readFileSync(path.join(snapshotDir, "charts", PNG)).equals(PNG_BYTES));
    assert.equal(fs.readFileSync(path.join(snapshotDir, "charts", HTML), "utf8"), HTML_TEXT);
    assert.equal(fs.readFileSync(path.join(snapshotDir, "charts", "plotly.min.js"), "utf8"), PLOTLY_TEXT);

    const snapshot = readSnapshot(frontendDir, {});
    assert.deepEqual([snapshot.ids, snapshot.charts, snapshot.plotly], [[ID], [PNG, HTML], true]);

    // The hidden chart is never fetched, and only GET routes are used.
    assert.equal(backend.requests.includes(`/charts/${HIDDEN}`), false);
    assert.deepEqual(backend.requests, [
      `/api/analysis/${ID}/status`,
      `/api/analysis/${ID}`,
      `/api/analysis/${ID}/charts`,
      `/charts/${PNG}`,
      `/charts/${HTML}`,
      "/charts/plotly.min.js",
    ]);

    assert.deepEqual(report.kept, [PNG, HTML]);
    assert.deepEqual(report.hidden, [HIDDEN]);
    assert.deepEqual(
      report.dropped.map((entry) => entry.path),
      [
        "status",
        "created_at",
        "profile_report",
        "cleaning_report.decisions",
        "cleaning_report.summary.rows_removed",
        "cleaning_report.summary.columns_removed",
        "analysis_report.descriptive_stats",
        "analysis_report.chart_paths",
        "analysis_report.correlation_matrix.highest_pair",
        "analysis_report.correlation_matrix.highest_value",
        "insight_report.technical_layer.cleaning_methodology",
        "insight_report.executive_layer",
        "insight_report.data_quality_score",
      ],
    );
    assert.equal(report.dropped.find((entry) => entry.path === "profile_report").bytes, Buffer.byteLength(JSON.stringify(rawAnalysis().profile_report)));
    assert.equal(report.publishedHits, 0);
    assert.deepEqual(
      report.droppedHits.map((hit) => [hit.path, hit.pattern]),
      [
        ["profile_report.source_note", "absolute path"],
        ["profile_report.source_note", "email"],
      ],
    );
    assert.deepEqual(
      report.files.map((file) => file.path),
      ["manifest.json", `analyses/${ID}.json`, `charts/${PNG}`, `charts/${HTML}`, "charts/plotly.min.js"],
    );
    for (const file of report.files) {
      const bytes = fs.readFileSync(path.join(snapshotDir, file.path));
      assert.deepEqual([file.size, file.sha256], [bytes.length, sha256(bytes)], file.path);
    }
  });

  it("is deterministic: the same responses give the same bytes", async () => {
    const backend = await fakeBackend();
    const [a, b] = [tempFrontend(), tempFrontend()];
    await runExport(backend, { frontendDir: a });
    await runExport(backend, { frontendDir: b });
    const files = filesUnder(path.join(a, "snapshot"));
    assert.deepEqual(filesUnder(path.join(b, "snapshot")), files);
    for (const rel of files) {
      assert.ok(fs.readFileSync(path.join(a, "snapshot", rel)).equals(fs.readFileSync(path.join(b, "snapshot", rel))), rel);
    }
  });

  it("refuses before any request when snapshot/ or the temporary folder exists, and changes nothing", async () => {
    for (const existing of ["snapshot", ".snapshot-export"]) {
      const backend = await fakeBackend();
      const frontendDir = tempFrontend();
      fs.mkdirSync(path.join(frontendDir, existing));
      await assert.rejects(runExport(backend, { frontendDir }), { name: "ExportError", message: new RegExp(`${existing.replace(".", "\\.")}/ already exists`) });
      assert.deepEqual(backend.requests, []);
      assert.deepEqual(fs.readdirSync(frontendDir), [existing]);
      assert.deepEqual(fs.readdirSync(path.join(frontendDir, existing)), []);
    }
  });

  it("checks the status route by its exact keys and values", async () => {
    const statusRoute = `/api/analysis/${ID}/status`;
    for (const [edit, pattern] of [
      [{ status: "explaining" }, /status must be "complete"/],
      [{ error_message: "SYSTEM_ERROR" }, /error_message must be null/],
      [{ pause_data: { column_name: "x" } }, /pause_data must be null/],
      [{ current_agent: "explainer" }, /current_agent must be null/],
      [{ progress_pct: 80 }, /progress_pct must be 100/],
      [{ analysis_id: OTHER_ID }, /analysis_id must be/],
      [{ extra: 1 }, /status route keys/],
    ]) {
      const backend = await fakeBackend({ routes: { [statusRoute]: { type: "application/json", body: { ...STATUS, ...edit } } } });
      await expectRefused(backend, pattern);
      assert.deepEqual(backend.requests, [statusRoute]);
    }
  });

  it("checks the analysis and the charts routes", async () => {
    const analysisRoute = `/api/analysis/${ID}`;
    const chartsRoute = `/api/analysis/${ID}/charts`;
    for (const [routes, pattern] of [
      [{ [analysisRoute]: { type: "application/json", body: { ...rawAnalysis(), id: OTHER_ID } } }, /analysis id must be/],
      [{ [analysisRoute]: { type: "application/json", body: { ...rawAnalysis(), status: "error" } } }, /analysis status must be "complete"/],
      [{ [analysisRoute]: { type: "application/json", body: [] } }, /analysis must be a JSON object/],
      [{ [analysisRoute]: { type: "application/json", body: "{not json" } }, /not valid JSON/],
      [{ [chartsRoute]: { type: "application/json", body: { chart_paths: [PNG, HTML] } } }, /charts route does not match/],
      [{ [chartsRoute]: { type: "application/json", body: { chart_paths: rawAnalysis().chart_paths, extra: 1 } } }, /charts route keys/],
    ]) {
      await expectRefused(await fakeBackend({ routes }), pattern);
    }
  });

  it("refuses redirects, error statuses, wrong content types, oversized bodies and slow responses", async () => {
    const statusRoute = `/api/analysis/${ID}/status`;
    const big = Buffer.alloc(20 * 1024, 0x20);
    for (const [route, pattern, options] of [
      [{ status: 302, type: "text/plain", headers: { location: "http://example.com/" } }, /HTTP 302: redirects are refused/],
      [{ status: 500, type: "application/json", body: "{}" }, /HTTP 500/],
      [{ type: "text/html", body: STATUS }, /content type "text\/html"/],
      [{ type: "application/json", body: big }, /over its 16384-byte cap/],
      [{ type: "application/json", body: big, chunked: true }, /over its 16384-byte cap/],
      [{ type: "application/json", body: STATUS, delayMs: 1500 }, /timed out after 200 ms/, { timeoutMs: 200 }],
    ]) {
      await expectRefused(await fakeBackend({ routes: { [statusRoute]: route } }), pattern, options);
    }
  });

  it("fails on any scan hit in the published projection, naming where", async () => {
    for (const [edit, pattern] of [
      [(a) => (a.insight_report.analyst_layer.narrative = "See /Users/someone/x/y.csv."), /insight_report\.analyst_layer\.narrative: absolute path/],
      [(a) => (a.executive_summary.bullets[0].context = "Ask owner@example.com."), /executive_summary\.bullets\[0\]\.context: email/],
      [(a) => (a.insight_report.technical_layer.limitations = "See https://example.com."), /insight_report\.technical_layer\.limitations: URL/],
      [(a) => (a.insight_report.technical_layer.code_blocks = ["key = 'sk-ant-abc'"]), /insight_report\.technical_layer\.code_blocks\[0\]: key-like string/],
      [(a) => (a.cleaning_decisions[0].reason = "Served from localhost."), /cleaning_decisions\[0\]\.reason: local host/],
      [(a) => (a.analysis_report.correlation_matrix.matrix["owner@example.com"] = { fixture_x: 0.1 }), /analysis_report\.correlation_matrix\.matrix: email/],
      [(a) => (a.insight_report.analyst_layer.narrative = `Compare ${OTHER_ID}.`), /UUID other than its own id: 00000000-0000-4000-a000-000000000002/],
      [(a) => (a.analysis_report.correlation_matrix.matrix.session_id = { fixture_x: 0.1 }), /forbidden key "session_id"/],
    ]) {
      const raw = rawAnalysis();
      edit(raw);
      await expectRefused(await fakeBackend({ raw }), pattern);
    }
  });

  it("fails when a kept field references a hidden chart, and refuses a --hide the analysis does not list", async () => {
    for (const edit of [
      (a) => (a.insight_report.analyst_layer.narrative = `See ${HIDDEN}.`),
      (a) => (a.insight_report.analyst_layer.narrative = `See ${HIDDEN.slice(0, -".png".length)}.`),
      (a) => (a.insight_report.analyst_layer.chart_references = [PNG, HIDDEN]),
      (a) => (a.insight_report.technical_layer.code_blocks = [`plt.savefig('${HIDDEN}')`]),
    ]) {
      const raw = rawAnalysis();
      edit(raw);
      await expectRefused(await fakeBackend({ raw }), /references the hidden chart/);
    }
    await expectRefused(await fakeBackend(), /--hide .* is not one of the analysis's charts/, { hide: [`${ID}_barchart_other.png`] });
  });

  it("fails on a contract problem before writing anything", async () => {
    const raw = rawAnalysis();
    raw.cleaning_report.summary.rows_before = 5;
    await expectRefused(await fakeBackend({ raw }), /cleaning_report\.summary\.rows_before \(5\) must equal row_count \(4\)/);
  });

  it("checks every chart file and plotly.min.js", async () => {
    const big = `${HTML_TEXT}${" ".repeat(50 * 1024)}`;
    for (const [routes, pattern] of [
      [{ [`/charts/${PNG}`]: { type: "image/png", body: "not a png" } }, /PNG signature/],
      [{ [`/charts/${PNG}`]: { type: "text/html", body: PNG_BYTES } }, /content type "text\/html"/],
      [{ [`/charts/${HTML}`]: { type: "text/html", body: big } }, /over its 51199-byte cap/],
      [{ [`/charts/${HTML}`]: { type: "text/html", body: HTML_TEXT.replace(SHARED_TAG, "") } }, /does not load the shared plotly\.min\.js/],
      [{ [`/charts/${HTML}`]: { type: "text/html", body: `${HTML_TEXT}/* plotly.js v2.30.0 */` } }, /inlines plotly/],
      [{ [`/charts/${HTML}`]: { type: "text/html", body: HTML_TEXT.replace(`/* ${ID} */`, `/* ${OTHER_ID} */`) } }, /UUID other than its analysis id/],
      [{ "/charts/plotly.min.js": { type: "text/javascript", body: `${PLOTLY_TEXT} ` } }, /plotly\.min\.js is not the pinned bundle/],
      [{ "/charts/plotly.min.js": { type: "text/javascript", body: "!function(){}" } }, /plotly\.min\.js is not the pinned bundle/],
    ]) {
      await expectRefused(await fakeBackend({ routes }), pattern);
    }
  });

  it("keeps the build's own reader as the last gate: a failure there leaves the temporary folder, and no snapshot/", async () => {
    // A PNG carrying another analysis's id passes the signature check, but not the rules' per-file UUID scan.
    const png = Buffer.concat([PNG_BYTES, Buffer.from(` ${OTHER_ID}`)]);
    const frontendDir = tempFrontend();
    await assert.rejects(runExport(await fakeBackend({ routes: { [`/charts/${PNG}`]: { type: "image/png", body: png } } }), { frontendDir }), {
      name: "ExportError",
      message: /fails the build's rules; it stays in \.snapshot-export\/ for inspection[\s\S]*UUID other than its analysis id/,
    });
    assert.equal(fs.existsSync(path.join(frontendDir, "snapshot")), false);
    assert.equal(fs.existsSync(path.join(frontendDir, ".snapshot-export", "manifest.json")), true);
  });

  it("pins plotly.min.js 2.30.0 by default (decisions.md 2026-10-12)", () => {
    assert.equal(exporter.PLOTLY_SHA256, "3baddf12a4f47ac22f006078f95c38b21abd53d1511b80e600a60cf0c52bab6e");
    assert.equal(exporter.PLOTLY_SIZE, 3620780);
  });

  it("validates the base URL itself too", async () => {
    await assert.rejects(runExport(await fakeBackend(), { baseUrl: new URL("http://example.com:8000") }), { name: "UsageError" });
  });
});

describe("the command line", () => {
  const SCRIPT = path.join(FRONTEND, "scripts", "export-snapshot.mjs");

  // A child process, waited for asynchronously so the fake backend can answer.
  function run(script, args, cwd) {
    return new Promise((resolve) => {
      const child = spawn(process.execPath, [script, ...args], { cwd, env: { PATH: process.env.PATH ?? "" } });
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (chunk) => (stdout += chunk));
      child.stderr.on("data", (chunk) => (stderr += chunk));
      child.on("close", (status) => resolve({ status, stdout, stderr }));
    });
  }

  it("exits 2 with the usage on a bad argument, before any request or file access", () => {
    const result = spawnSync(process.execPath, [SCRIPT, ID.toUpperCase(), "http://127.0.0.1:1"], { env: { PATH: process.env.PATH ?? "" }, encoding: "utf8" });
    assert.equal(result.status, 2);
    assert.match(result.stderr, /lowercase canonical UUID/);
    assert.match(result.stderr, /Usage: node scripts\/export-snapshot\.mjs <analysis id> <base url> \[--hide <chart file name>\]\.\.\./);
  });

  it("exports into the frontend/ it sits in, and exits 1 with its message on a failure", async () => {
    // A temporary frontend/ holding copies of the script and the rules module;
    // PNG-only charts, since the command line always pins plotly's real bundle.
    const root = tempFrontend();
    for (const rel of ["scripts/export-snapshot.mjs", "lib/snapshot-rules.mjs"]) {
      fs.mkdirSync(path.join(root, path.dirname(rel)), { recursive: true });
      fs.copyFileSync(path.join(FRONTEND, rel), path.join(root, rel));
    }
    const raw = { ...rawAnalysis(), chart_paths: [PNG, HIDDEN] };
    raw.insight_report.analyst_layer.chart_references = [PNG];
    const backend = await fakeBackend({ raw });
    const script = path.join(root, "scripts", "export-snapshot.mjs");
    const ok = await run(script, [ID, backend.base.origin, "--hide", HIDDEN], root);
    assert.equal(ok.status, 0, ok.stderr);
    assert.match(ok.stdout, /hidden charts \(1\): .*barchart_customer_id\.png/);
    assert.match(ok.stdout, /written into snapshot\/:/);
    assert.deepEqual(filesUnder(path.join(root, "snapshot")), [`analyses/${ID}.json`, `charts/${PNG}`, "manifest.json"]);

    const again = await run(script, [ID, backend.base.origin, "--hide", HIDDEN], root);
    assert.equal(again.status, 1);
    assert.match(again.stderr, /^export-snapshot: snapshot\/ already exists/);
  });
});
