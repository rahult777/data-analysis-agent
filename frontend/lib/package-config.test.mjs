// frontend/package.json and frontend/.npmrc (M2c.1; the owner's rulings Q5, Q7, Q8 and Q9): the three
// unused packages stay removed; @playwright/test is pinned exactly, since brand-assets --check is
// byte-exact against the Chromium that version installs; next dev and next start listen on 127.0.0.1
// only; npm runs no install script. The expected values are literals, never read from the files under
// test.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";

const PACKAGE = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const NPMRC = new URL("../.npmrc", import.meta.url);
const SECTIONS = ["dependencies", "devDependencies", "optionalDependencies", "peerDependencies"];
const REMOVED = ["shadcn", "recharts", "tw-animate-css"];

describe("package.json and .npmrc", () => {
  it("lists none of shadcn, recharts or tw-animate-css", () => {
    const listed = SECTIONS.flatMap((section) =>
      Object.keys(PACKAGE[section] ?? {})
        .filter((name) => REMOVED.includes(name))
        .map((name) => `${section}.${name}`),
    );
    assert.deepEqual(listed, []);
  });

  it("pins @playwright/test to exactly 1.63.0", () => {
    assert.equal(PACKAGE.devDependencies?.["@playwright/test"], "1.63.0");
  });

  it("binds next dev and next start to 127.0.0.1", () => {
    assert.equal(PACKAGE.scripts.dev, "next dev -H 127.0.0.1");
    assert.equal(PACKAGE.scripts.start, "next start -H 127.0.0.1");
  });

  it("sets ignore-scripts=true in frontend/.npmrc", () => {
    assert.ok(existsSync(NPMRC), "frontend/.npmrc exists");
    const settings = readFileSync(NPMRC, "utf8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line !== "" && !line.startsWith("#") && !line.startsWith(";"));
    const ignoreScripts = settings.filter((line) => line.split("=")[0].trim() === "ignore-scripts");
    // npm takes the last value a file sets.
    assert.equal(ignoreScripts.at(-1), "ignore-scripts=true");
  });

  // With ignore-scripts=true npm skips every pre and post hook silently (`npm run x` still runs x) and
  // every install-lifecycle script, so none may exist to be skipped. A name that starts with "pre" or
  // "post" covers the hooks and preinstall, postinstall, prepare, preprepare, postprepare and prepublish.
  it("has no pre or post hook and no install-lifecycle script", () => {
    const names = Object.keys(PACKAGE.scripts ?? {});
    assert.deepEqual(
      names.filter((name) => name.startsWith("pre") || name.startsWith("post") || name === "install" || name === "dependencies"),
      [],
    );
  });
});
