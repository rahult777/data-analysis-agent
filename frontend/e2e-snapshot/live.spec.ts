// The live run's own tooling (M3b.1), checked without a browser and once, in
// the desktop project. scripts/live-check.mjs, run against this suite's server
// (the committed snapshot, built with the test settings and served the way
// Vercel serves it), must pass every check, and against a bare server it must
// fail and name each failure; a usage error exits 2 before any check. The
// Playwright configs: playwright.live.config.ts refuses to start without its
// three variables, or with one malformed, and runs only the snapshot suite's
// browser specs, and the other three configs refuse to start while
// E2E_LIVE_URL is set, which switches e2e-public/fixture.ts to the deployed
// site's settings. playwright.live.config.ts leaves this file out: it needs
// this suite's server.

import { execFile } from "node:child_process";
import { readdirSync } from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { promisify } from "node:util";

import { expect, test } from "@playwright/test";

import { KEPT_CHARTS, PLOTLY } from "./snapshot";

const execFileAsync = promisify(execFile);
const FRONTEND = path.join(__dirname, "..");
// Both run with node, in frontend/.
const LIVE_CHECK = "scripts/live-check.mjs";
const PLAYWRIGHT_CLI = "node_modules/@playwright/test/cli.js";
// The two settings the live config needs besides the site's address: test
// values, never fetched (listing tests reaches no server).
const SETTINGS: Record<string, string> = {
  E2E_SITE_URL: "https://omnalynt.example",
  E2E_GITHUB_URL: "https://github.com/e2e-owner/e2e-repo",
};
const UNUSED_PORT_URL = "http://127.0.0.1:9";

interface Run {
  code: number;
  stdout: string;
  stderr: string;
}

// Node on a script, in frontend/, with a minimal environment (PATH, HOME,
// TMPDIR and the given variables), so no E2E_ variable of the shell that
// started this suite reaches the child. A non-zero exit is a result here.
async function runNode(args: string[], env: Record<string, string> = {}): Promise<Run> {
  const base: Record<string, string> = { PATH: process.env.PATH ?? "", HOME: process.env.HOME ?? "" };
  if (process.env.TMPDIR !== undefined) base.TMPDIR = process.env.TMPDIR;
  try {
    const { stdout, stderr } = await execFileAsync(process.execPath, args, {
      cwd: FRONTEND,
      // No NODE_ENV, which Next's types make a required key of ProcessEnv.
      env: { ...base, ...env } as NodeJS.ProcessEnv,
      // Under the suite's 60 s test timeout: a child that hangs fails its test,
      // whose own cleanup then runs (the config tests allow 180 s).
      timeout: 50_000,
      maxBuffer: 16 * 1024 * 1024,
    });
    return { code: 0, stdout, stderr };
  } catch (error) {
    const failed = error as { code?: unknown; stdout?: unknown; stderr?: unknown };
    if (typeof failed.code !== "number") throw error;
    return { code: failed.code, stdout: String(failed.stdout ?? ""), stderr: String(failed.stderr ?? "") };
  }
}

function outputLines(run: Run): string[] {
  return run.stdout.split("\n").filter((line): boolean => line !== "");
}

// The tests below use no browser: the desktop project runs them, once.
function oncePerRun(): void {
  test.skip(test.info().project.name !== "desktop-1280", "once, in the desktop project; no browser");
}

test.describe("scripts/live-check.mjs", () => {
  test("--local against this suite's own server: every check passes, every chart among them", async ({ baseURL }) => {
    oncePerRun();
    const run = await runNode([LIVE_CHECK, new URL(baseURL ?? "").origin, "--local"]);
    const lines = outputLines(run);
    expect(lines.filter((line): boolean => line.startsWith("FAIL")), run.stdout + run.stderr).toEqual([]);
    for (const name of KEPT_CHARTS.concat(PLOTLY)) {
      const url = `/demo/charts/${name.replace(/\.html$/, "")}`;
      expect(lines.some((line): boolean => line.startsWith("PASS") && line.includes(`${url}:`)), url).toBe(true);
    }
    expect(lines[lines.length - 1], run.stderr).toBe("LIVE CHECK PASS");
    expect(run.code).toBe(0);
  });

  test("--local against a bare server: it fails, and names each failure", async () => {
    oncePerRun();
    // Every answer: 200, plain text, neither header set.
    const server = http.createServer((_request, response): void => {
      response.writeHead(200, { "content-type": "text/plain; charset=utf-8" }).end("bare");
    });
    await new Promise<void>((resolve): void => {
      server.listen(0, "127.0.0.1", resolve);
    });
    try {
      const { port } = server.address() as AddressInfo;
      const run = await runNode([LIVE_CHECK, `http://127.0.0.1:${port}`, "--local"]);
      const lines = outputLines(run);
      const failures = lines.filter((line): boolean => line.startsWith("FAIL"));
      expect(failures.length, run.stdout + run.stderr).toBeGreaterThan(0);
      expect(lines[lines.length - 1]).toBe(`LIVE CHECK FAIL (${failures.length})`);
      expect(run.code).toBe(1);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve): void => {
        server.close((): void => resolve());
      });
    }
  });

  test("a usage error exits 2 before any check", async () => {
    oncePerRun();
    const cases: string[][] = [
      [],
      [UNUSED_PORT_URL],
      ["https://site.invalid", "--local"],
      [UNUSED_PORT_URL, "--local", "--protected"],
      ["https://site.invalid"],
      ["https://site.invalid", "--protected", "https://commit.invalid"],
      ["https://site.invalid", "--protected", "https://commit.invalid", "http://branch.invalid"],
      ["https://site.invalid/x", "--protected", "https://commit.invalid", "https://branch.invalid"],
      ["https://site.invalid", "--protected", "https://site.invalid/x", "https://branch.invalid"],
    ];
    for (const args of cases) {
      const run = await runNode([LIVE_CHECK, ...args]);
      const label = JSON.stringify(args);
      expect(run.code, label).toBe(2);
      expect(run.stdout, label).toBe("");
      expect(run.stderr, label).toContain("usage: node scripts/live-check.mjs");
    }
  });
});

test.describe("the Playwright configs", () => {
  test("the local, public and snapshot configs refuse to start while E2E_LIVE_URL is set, even empty", async () => {
    oncePerRun();
    test.setTimeout(180_000);
    for (const config of ["playwright.config.ts", "playwright.public.config.ts", "playwright.snapshot.config.ts"]) {
      for (const value of [UNUSED_PORT_URL, ""]) {
        const run = await runNode([PLAYWRIGHT_CLI, "test", "-c", config, "--list"], { E2E_LIVE_URL: value });
        const label = `${config} with E2E_LIVE_URL=${JSON.stringify(value)}`;
        expect(run.code, label).not.toBe(0);
        expect(run.stdout + run.stderr, label).toContain(`${config}: E2E_LIVE_URL is set; only playwright.live.config.ts may run with it`);
      }
    }
  });

  test("playwright.live.config.ts refuses to start unless E2E_LIVE_URL, E2E_SITE_URL and E2E_GITHUB_URL are all set, each in its form", async () => {
    oncePerRun();
    test.setTimeout(180_000);
    const all: Record<string, string> = { E2E_LIVE_URL: UNUSED_PORT_URL, ...SETTINGS };
    // Each case: the environment, and the refusal it must print. A missing or
    // empty variable is listed after "set"; a malformed one is named alone.
    const cases: Array<[Record<string, string>, string]> = [[{}, "set E2E_LIVE_URL, E2E_SITE_URL, E2E_GITHUB_URL:"]];
    for (const name of Object.keys(all)) {
      const without = { ...all };
      delete without[name];
      cases.push([without, `set ${name}:`], [{ ...all, [name]: "" }, `set ${name}:`]);
    }
    // A malformed value would make the specs fail without naming it.
    const malformed: Array<[string, string]> = [
      ["E2E_LIVE_URL", "http://127.0.0.1:9/"],
      ["E2E_SITE_URL", "https://omnalynt.example/"],
      ["E2E_SITE_URL", "http://omnalynt.example"],
      ["E2E_GITHUB_URL", "https://github.com/e2e-owner/e2e-repo/"],
      ["E2E_GITHUB_URL", "https://github.com/e2e-owner/e2e-repo.git"],
    ];
    for (const [name, value] of malformed) cases.push([{ ...all, [name]: value }, `${name} must be `]);
    // Soft: a run reports every case that fails, not only the first.
    for (const [env, refusal] of cases) {
      const run = await runNode([PLAYWRIGHT_CLI, "test", "-c", "playwright.live.config.ts", "--list"], env);
      const label = JSON.stringify(env);
      expect.soft(run.code, label).not.toBe(0);
      expect.soft(run.stdout + run.stderr, label).toContain(`playwright.live.config.ts: ${refusal}`);
    }
  });

  test("playwright.live.config.ts runs the snapshot suite's browser specs in its two projects, and nothing else", async () => {
    oncePerRun();
    test.setTimeout(180_000);
    const run = await runNode([PLAYWRIGHT_CLI, "test", "-c", "playwright.live.config.ts", "--list"], {
      E2E_LIVE_URL: UNUSED_PORT_URL,
      ...SETTINGS,
    });
    expect(run.code, run.stdout + run.stderr).toBe(0);
    // A listed test: "  [project] > file:line:column > title", the separators
    // being one non-space character each.
    const listed = new Set<string>();
    for (const line of outputLines(run)) {
      const match = /^\s*\[([^\]]+)\] \S (\S+):\d+:\d+ \S /.exec(line);
      if (match !== null) listed.add(`${match[1]} ${path.basename(match[2])}`);
    }
    const specs = readdirSync(__dirname).filter(
      (name): boolean => name.endsWith(".spec.ts") && name !== "build-output.spec.ts" && name !== "live.spec.ts",
    );
    const want = ["mobile-320", "desktop-1280"].flatMap((project): string[] => specs.map((name): string => `${project} ${name}`));
    expect(Array.from(listed).sort()).toEqual(want.sort());
  });
});
