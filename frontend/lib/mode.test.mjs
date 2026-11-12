// Unit tests for the build-time data source (NEXT_PUBLIC_DATA_SOURCE) and the
// public build's two site settings (NEXT_PUBLIC_SITE_URL,
// NEXT_PUBLIC_GITHUB_URL): next.config.mjs, their only validator, and the
// values lib/mode.ts and lib/site.ts compute. The settings' rules have their
// own tests (lib/site-settings.test.mjs).
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
const SITE = "NEXT_PUBLIC_SITE_URL";
const GITHUB = "NEXT_PUBLIC_GITHUB_URL";
// Valid site settings: the public e2e's values (e2e-public/fixture.ts).
const SETTINGS = { [SITE]: "https://omnalynt.example", [GITHUB]: "https://github.com/e2e-owner/e2e-repo" };

// Sets each variable (undefined = unset) and returns the previous values.
function setEnv(values) {
  const previous = {};
  for (const [name, value] of Object.entries(values)) {
    previous[name] = process.env[name];
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
  return previous;
}

// Calls the config function with the flag set to `value` and the two site
// settings as given (undefined = unset; valid by default), restoring the
// environment afterwards.
function configWith(value, phase, settings = SETTINGS) {
  const previous = setEnv({ [FLAG]: value, [SITE]: settings[SITE], [GITHUB]: settings[GITHUB] });
  try {
    return nextConfig(phase);
  } finally {
    setEnv(previous);
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

describe("next.config.mjs requires both site settings in the public build", () => {
  const HEADER = "The public build (npm run build:public) needs both site settings, set inline or in frontend/.env.local:";
  const SITE_MISSING = `  - ${SITE} is not set: give the site's address, https://<host> with no path and no trailing slash`;
  const GITHUB_MISSING = `  - ${GITHUB} is not set: give the repository's address, https://github.com/<owner>/<repo> with nothing after it`;

  it("fails closed without the site's address, naming it", () => {
    assert.throws(() => configWith("snapshot", PHASE_PRODUCTION_BUILD, { [GITHUB]: SETTINGS[GITHUB] }), {
      message: `${HEADER}\n${SITE_MISSING}`,
    });
  });

  it("fails closed without the GitHub repository, naming it", () => {
    assert.throws(() => configWith("snapshot", PHASE_PRODUCTION_BUILD, { [SITE]: SETTINGS[SITE] }), {
      message: `${HEADER}\n${GITHUB_MISSING}`,
    });
  });

  it("lists both, the site's address first, when both are unset or empty", () => {
    for (const settings of [{}, { [SITE]: "", [GITHUB]: "" }]) {
      assert.throws(() => configWith("snapshot", PHASE_PRODUCTION_BUILD, settings), {
        message: `${HEADER}\n${SITE_MISSING}\n${GITHUB_MISSING}`,
      });
    }
  });

  it("fails closed on an invalid value, with that value's problem", () => {
    assert.throws(() => configWith("snapshot", PHASE_PRODUCTION_BUILD, { ...SETTINGS, [SITE]: "https://omnalynt.example/" }), {
      message:
        `${HEADER}\n  - ${SITE} must be the site's origin alone: https://<host> in lower case, with no path, trailing slash, ` +
        'query, fragment, user name or default port; got "https://omnalynt.example/"',
    });
    assert.throws(() => configWith("snapshot", PHASE_PRODUCTION_BUILD, { ...SETTINGS, [GITHUB]: "https://github.com/o/r/tree/main" }), {
      message:
        `${HEADER}\n  - ${GITHUB} must be https://github.com/<owner>/<repo> with nothing after it ` +
        '(no trailing slash, path, query or fragment); got "https://github.com/o/r/tree/main"',
    });
  });

  it("local mode ignores both settings, valid, invalid or missing, in every phase", () => {
    const variants = [{}, { [SITE]: "not a url", [GITHUB]: "not a url" }, SETTINGS];
    for (const flag of [undefined, ""]) {
      for (const phase of [PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER]) {
        for (const settings of variants) assert.equal(configWith(flag, phase, settings).output, undefined);
      }
    }
  });

  it("refuses snapshot mode under next dev before it reads the settings", () => {
    assert.throws(() => configWith("snapshot", PHASE_DEVELOPMENT_SERVER, {}), {
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

  it("lib/site.ts gives both site settings as set in the public build", () => {
    assert.deepEqual(
      runModule("lib/site.ts", { [FLAG]: "snapshot", ...SETTINGS }, "return { site: m.SITE_URL ?? null, github: m.GITHUB_URL ?? null };"),
      { site: SETTINGS[SITE], github: SETTINGS[GITHUB] },
    );
  });

  it("lib/site.ts ignores both site settings in local mode, even when they are set", () => {
    for (const env of [{ ...SETTINGS }, { [FLAG]: "", ...SETTINGS }]) {
      assert.deepEqual(
        runModule("lib/site.ts", env, "return { site: m.SITE_URL ?? null, github: m.GITHUB_URL ?? null };"),
        { site: null, github: null },
      );
    }
  });

  it("lib/site.ts derives the owner's GitHub profile from the repository in the public build", () => {
    assert.deepEqual(
      runModule("lib/site.ts", { [FLAG]: "snapshot", ...SETTINGS }, "return { profile: m.GITHUB_PROFILE_URL ?? null };"),
      { profile: "https://github.com/e2e-owner" },
    );
  });

  it("lib/site.ts gives no profile in local mode, even when the repository is set", () => {
    for (const env of [{ ...SETTINGS }, { [FLAG]: "", ...SETTINGS }]) {
      assert.deepEqual(runModule("lib/site.ts", env, "return { profile: m.GITHUB_PROFILE_URL ?? null };"), { profile: null });
    }
  });

  it("lib/site.ts never throws on a repository the rules refuse: it gives no profile", () => {
    assert.deepEqual(
      runModule("lib/site.ts", { [FLAG]: "snapshot", ...SETTINGS, [GITHUB]: "not a url" }, "return { profile: m.GITHUB_PROFILE_URL ?? null };"),
      { profile: null },
    );
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
