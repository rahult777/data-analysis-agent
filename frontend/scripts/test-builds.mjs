// Representative failing public builds (spec M2b.1 3e): `npm run build:public`
// on each broken fixture under e2e/fixtures/snapshot-broken/ must exit
// non-zero with that fixture's own message, never with Next's misleading
// "missing generateStaticParams()". Every failure class itself is unit-tested
// in lib/snapshot-rules.test.mjs; these prove the build wiring.
//
// Run with `npm run test:builds` (or name cases: `npm run test:builds --
// fixture-guard`). Each case is a full build. Builds share .next and out/
// with every other build and both e2e suites, so run nothing else alongside.

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ID = "00000000-0000-4000-a000-000000000001";
const BROKEN = "e2e/fixtures/snapshot-broken";

const CASES = [
  {
    name: "missing-manifest",
    allowFixture: true,
    expected: `Snapshot: no manifest at ${BROKEN}/missing-manifest/manifest.json`,
  },
  {
    name: "forbidden-key",
    allowFixture: true,
    expected: `analyses/${ID}.json: forbidden key "sessionId" at executive_summary.bullets[0].sessionId`,
  },
  {
    name: "chart-mismatch",
    allowFixture: true,
    expected: `chart "${ID}_scatter_fixture_x_fixture_y.html" listed by ${ID} has no file in charts/`,
  },
  {
    name: "fixture-guard",
    allowFixture: false,
    expected: `Snapshot: ${BROKEN}/fixture-guard/manifest.json is a test fixture ("fixture": true)`,
  },
];

const only = process.argv.slice(2);
const unknown = only.filter((name) => !CASES.some((c) => c.name === name));
if (unknown.length > 0) {
  console.error(`Unknown case(s): ${unknown.join(", ")}. Cases: ${CASES.map((c) => c.name).join(", ")}.`);
  process.exit(2);
}

let failures = 0;
for (const testCase of CASES.filter((c) => only.length === 0 || only.includes(c.name))) {
  const env = { ...process.env, SNAPSHOT_DIR: `${BROKEN}/${testCase.name}` };
  // Only this case's variables: no flag value, fixture permission or VERCEL
  // inherited from the shell.
  delete env.NEXT_PUBLIC_DATA_SOURCE;
  delete env.SNAPSHOT_ALLOW_FIXTURE;
  delete env.VERCEL;
  if (testCase.allowFixture) env.SNAPSHOT_ALLOW_FIXTURE = "1";

  console.log(`\n=== ${testCase.name}: SNAPSHOT_DIR=${env.SNAPSHOT_DIR}${testCase.allowFixture ? " SNAPSHOT_ALLOW_FIXTURE=1" : ""} npm run build:public`);
  const run = spawnSync("npm", ["run", "build:public"], { cwd: FRONTEND, env, encoding: "utf8" });
  const lines = `${run.stdout}\n${run.stderr}`.split("\n");
  const start = lines.findIndex((line) => line.includes("Snapshot: "));
  // The snapshot error: its first line plus its "  - " problem lines.
  const message = start === -1 ? [] : [lines[start], ...takeWhile(lines.slice(start + 1), (l) => l.startsWith("  - "))];
  const misleading = lines.some((line) => line.includes('missing "generateStaticParams()"'));
  const passed = run.status !== 0 && message.some((line) => line.includes(testCase.expected)) && !misleading;
  if (!passed) failures += 1;

  console.log(`exit status: ${run.status}`);
  console.log(message.length > 0 ? message.map((line) => `message: ${line.trim()}`).join("\n") : "message: (no snapshot message)");
  if (misleading) console.log('Next\'s misleading "missing generateStaticParams()" message appeared.');
  console.log(passed ? "PASS" : `FAIL (expected a non-zero exit and: ${testCase.expected})`);
}

console.log(failures === 0 ? "\nAll broken builds failed with their own messages." : `\n${failures} case(s) did not.`);
process.exit(failures === 0 ? 0 : 1);

/**
 * @param {string[]} items
 * @param {(item: string) => boolean} keep
 */
function takeWhile(items, keep) {
  const end = items.findIndex((item) => !keep(item));
  return end === -1 ? items : items.slice(0, end);
}
