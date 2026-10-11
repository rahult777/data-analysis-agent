// Unit tests for the build-time data source (NEXT_PUBLIC_DATA_SOURCE):
// next.config.mjs, its only validator, and the values lib/mode.ts computes.
// Run with `npm run test:unit` (Node's built-in test runner; no dependency).
// Never put this file under e2e/ or e2e-public/: Playwright's default test
// pattern matches *.test.mjs.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
  PHASE_PRODUCTION_SERVER,
} from "next/constants.js";

import nextConfig from "../next.config.mjs";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const FLAG = "NEXT_PUBLIC_DATA_SOURCE";

// Calls the config function with the flag set to `value` (undefined = unset),
// restoring the environment afterwards.
function configWith(value, phase) {
  const saved = process.env[FLAG];
  if (value === undefined) delete process.env[FLAG];
  else process.env[FLAG] = value;
  try {
    return nextConfig(phase);
  } finally {
    if (saved === undefined) delete process.env[FLAG];
    else process.env[FLAG] = saved;
  }
}

// Imports a frontend TypeScript module in a fresh Node process (type
// stripping) with exactly `env` (plus PATH), evaluates `body` with the module
// bound to `m`, and returns the JSON-serialized result. Relative imports
// without an extension resolve to .ts, as the bundler resolves them.
// `prelude` runs before the import.
function runModule(relativeFile, env, body, prelude = "") {
  const url = pathToFileURL(path.join(FRONTEND, relativeFile)).href;
  const code = `
import { registerHooks } from "node:module";
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (/^\\.{1,2}\\//.test(specifier) && !/\\.[cm]?[jt]sx?$/.test(specifier)) {
      try { return nextResolve(specifier + ".ts", context); } catch {}
    }
    return nextResolve(specifier, context);
  },
});
${prelude}
const m = await import(${JSON.stringify(url)});
const result = await (async () => { ${body} })();
process.stdout.write(JSON.stringify(result));
`;
  const child = spawnSync(process.execPath, ["--input-type=module", "--eval", code], {
    cwd: FRONTEND,
    env: { PATH: process.env.PATH, ...env },
    encoding: "utf8",
  });
  assert.equal(child.status, 0, `child process failed:\n${child.stderr}`);
  return JSON.parse(child.stdout);
}

describe("next.config.mjs validates NEXT_PUBLIC_DATA_SOURCE", () => {
  it("unset means local mode: no static export, in every phase", () => {
    for (const phase of [PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER]) {
      assert.equal(configWith(undefined, phase).output, undefined);
    }
  });

  it("empty means local mode", () => {
    assert.equal(configWith("", PHASE_PRODUCTION_BUILD).output, undefined);
    assert.equal(configWith("", PHASE_DEVELOPMENT_SERVER).output, undefined);
  });

  it('exactly "snapshot" builds a static export', () => {
    assert.equal(configWith("snapshot", PHASE_PRODUCTION_BUILD).output, "export");
  });

  it("rejects any other value and names it, in every phase", () => {
    const values = ["Snapshot", "SNAPSHOT", " snapshot", "snapshot ", "snapshot\n", "local", "1", "true", "snapshots"];
    for (const value of values) {
      for (const phase of [PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD]) {
        assert.throws(() => configWith(value, phase), {
          message: `NEXT_PUBLIC_DATA_SOURCE must be unset, empty or "snapshot"; got ${JSON.stringify(value)}.`,
        });
      }
    }
  });

  it("refuses snapshot mode under next dev (an unlisted id would be a server error there, not a 404)", () => {
    assert.throws(() => configWith("snapshot", PHASE_DEVELOPMENT_SERVER), {
      message: "snapshot mode is build-only; use npm run build:public",
    });
  });
});

describe("lib/mode.ts", () => {
  const read = "return { isSnapshot: m.isSnapshot, API_URL: m.API_URL };";

  it('snapshot mode: isSnapshot, and API_URL is "" whatever NEXT_PUBLIC_API_URL says', () => {
    assert.deepEqual(
      runModule("lib/mode.ts", { [FLAG]: "snapshot", NEXT_PUBLIC_API_URL: "http://api-canary.invalid" }, read),
      { isSnapshot: true, API_URL: "" },
    );
  });

  it("local mode uses NEXT_PUBLIC_API_URL", () => {
    assert.deepEqual(
      runModule("lib/mode.ts", { NEXT_PUBLIC_API_URL: "http://127.0.0.1:9" }, read),
      { isSnapshot: false, API_URL: "http://127.0.0.1:9" },
    );
  });

  it("local mode falls back to http://localhost:8000", () => {
    assert.deepEqual(runModule("lib/mode.ts", {}, read), {
      isSnapshot: false,
      API_URL: "http://localhost:8000",
    });
    assert.deepEqual(runModule("lib/mode.ts", { [FLAG]: "" }, read), {
      isSnapshot: false,
      API_URL: "http://localhost:8000",
    });
  });

  it("never throws: next.config.mjs is the only validator", () => {
    assert.deepEqual(runModule("lib/mode.ts", { [FLAG]: "Snapshot" }, read), {
      isSnapshot: false,
      API_URL: "http://localhost:8000",
    });
  });

  it("lib/api.ts re-exports the same API_URL", () => {
    assert.deepEqual(
      runModule("lib/api.ts", { [FLAG]: "snapshot", NEXT_PUBLIC_API_URL: "http://api-canary.invalid" }, "return m.API_URL;"),
      "",
    );
    assert.deepEqual(
      runModule("lib/api.ts", { NEXT_PUBLIC_API_URL: "http://127.0.0.1:9" }, "return m.API_URL;"),
      "http://127.0.0.1:9",
    );
  });
});

// Records every outgoing HTTP attempt (and makes it fail) before lib/api.ts
// is imported, so a test can prove a function made no request.
const RECORD_REQUESTS = `
import http from "node:http";
import https from "node:https";
globalThis.attempts = [];
const record = (...args) => {
  const target = args[0];
  globalThis.attempts.push(typeof target === "string" || target instanceof URL
    ? String(target)
    : \`\${target.hostname ?? target.host}:\${target.port}\${target.path}\`);
  throw new Error("e2e: network request attempted");
};
for (const mod of [http, https]) { mod.request = record; mod.get = record; }
globalThis.fetch = async (...args) => record(...args);
`;

// Calls every network function in lib/api.ts and reports how each settled.
const CALL_EVERY_NETWORK_FUNCTION = `
const id = "00000000-0000-4000-a000-000000000001";
const calls = {
  uploadFile: () => m.uploadFile(new File(["a,b\\n1,2\\n"], "x.csv")),
  getAnalysisStatus: () => m.getAnalysisStatus(id),
  getAnalysis: () => m.getAnalysis(id),
  getCharts: () => m.getCharts(id),
  postQuestion: () => m.postQuestion(id, "session", "question?"),
  getQuestion: () => m.getQuestion(id, id),
  resumeAnalysis: () => m.resumeAnalysis(id, "session", { choice: "x" }),
};
const results = {};
for (const [name, call] of Object.entries(calls)) {
  try {
    await call();
    results[name] = "resolved";
  } catch (error) {
    results[name] = { name: error.name, status: error.status, message: error.message };
  }
}
return { results, attempts: globalThis.attempts };
`;

describe("lib/api.ts network functions", () => {
  const READ_ONLY = {
    name: "ApiError",
    status: null,
    message: "This is a read-only snapshot: it makes no API requests.",
  };

  it("refuse in the snapshot build, before any request", () => {
    const { results, attempts } = runModule(
      "lib/api.ts",
      { [FLAG]: "snapshot", NEXT_PUBLIC_API_URL: "http://api-canary.invalid" },
      CALL_EVERY_NETWORK_FUNCTION,
      RECORD_REQUESTS,
    );
    assert.deepEqual(attempts, []);
    assert.equal(Object.keys(results).length, 7);
    for (const [name, result] of Object.entries(results)) assert.deepEqual(result, READ_ONLY, name);
  });

  it("reach the API in local mode (the control)", () => {
    const { results, attempts } = runModule(
      "lib/api.ts",
      { NEXT_PUBLIC_API_URL: "http://127.0.0.1:9" },
      CALL_EVERY_NETWORK_FUNCTION,
      RECORD_REQUESTS,
    );
    assert.equal(attempts.length, 7);
    assert.ok(attempts.every((target) => target.startsWith("127.0.0.1:9/")), attempts.join("\n"));
    for (const result of Object.values(results)) assert.equal(result.message, "e2e: network request attempted");
  });
});

describe("lib/api.ts chartUrl", () => {
  const PNG = "00000000-0000-4000-a000-000000000001_histogram_x.png";
  const HTML = "00000000-0000-4000-a000-000000000001_scatter_x_y.html";
  const urls = `return [m.chartUrl(${JSON.stringify(PNG)}), m.chartUrl(${JSON.stringify(HTML)})];`;

  it("local mode: the backend's /charts route, file names unchanged", () => {
    assert.deepEqual(runModule("lib/api.ts", { NEXT_PUBLIC_API_URL: "http://127.0.0.1:9" }, urls), [
      `http://127.0.0.1:9/charts/${PNG}`,
      `http://127.0.0.1:9/charts/${HTML}`,
    ]);
  });

  it("snapshot build: /demo/charts/, .html dropped (Vercel strips it from exported files), PNG unchanged", () => {
    assert.deepEqual(runModule("lib/api.ts", { [FLAG]: "snapshot", NEXT_PUBLIC_API_URL: "http://api-canary.invalid" }, urls), [
      `/demo/charts/${PNG}`,
      `/demo/charts/${HTML.slice(0, -".html".length)}`,
    ]);
  });
});
