// The second half of `npm run build:public`: copies the snapshot's chart files
// into the static export at out/demo/charts/, where chartUrl (lib/api.ts)
// points. It runs after `next build`, which deletes out/ at the start of every
// export, so nothing stale survives; Vercel collects out/ after the whole
// build command has finished.
//
// It reads the snapshot with the loader's rules (lib/snapshot-rules.mjs): the
// same directory resolution and the same VERCEL and fixture guards. It first
// loads the .env files `next build` loads, the same way (production mode;
// next/dist/build/index.js:371), so both halves of build:public see the same
// SNAPSHOT_DIR and SNAPSHOT_ALLOW_FIXTURE; a value set in the process wins
// over the files. It copies exactly the files the manifest's analyses list in
// chart_paths, plus plotly.min.js when an HTML chart needs it, and fails on a
// missing or extra file (.DS_Store ignored).

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { readSnapshot } from "../lib/snapshot-rules.mjs";

// @next/env as next itself resolves it: a dependency of next, not a top-level
// one. CommonJS, so it is required, not imported.
const { loadEnvConfig } = createRequire(import.meta.resolve("next/package.json"))("@next/env");

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(FRONTEND, "out");
const TARGET = path.join(OUT, "demo", "charts");

/** @param {string} message */
function fail(message) {
  console.error(message);
  process.exit(1);
}

loadEnvConfig(FRONTEND, false);

let snapshot;
try {
  snapshot = readSnapshot(FRONTEND, process.env);
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}
if (!fs.existsSync(OUT)) {
  fail("copy-snapshot-charts: out/ does not exist. It runs after `next build`: use npm run build:public.");
}
if (fs.existsSync(path.join(OUT, "demo"))) {
  fail("copy-snapshot-charts: out/demo/ already exists; the export must not contain it.");
}

const files = [...snapshot.charts, ...(snapshot.plotly ? ["plotly.min.js"] : [])];
fs.mkdirSync(TARGET, { recursive: true });
for (const name of files) {
  fs.copyFileSync(path.join(snapshot.dir, "charts", name), path.join(TARGET, name), fs.constants.COPYFILE_EXCL);
}
console.log(`copied ${files.length} chart file(s) from ${snapshot.label}/charts/ into out/demo/charts/`);
