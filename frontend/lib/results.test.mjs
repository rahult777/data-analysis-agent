// Unit tests for lib/results.ts, the results view's client-safe helpers
// (M2b.3b.2): the header's counts and its second line, the en-US count format,
// and the matcher that turns chart file names in the narrative into links.
// Run with `npm run test:unit` (Node's built-in test runner; no dependency).
// Node strips the types when it imports the .ts file and prints one
// "Reparsing as ES module" warning, because frontend/package.json has no
// "type" (harmless). Never put this file under e2e/ or e2e-public/:
// Playwright's default test pattern matches *.test.mjs.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { formatCount, headerLine, readHeaderShape, splitChartNames } from "./results.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));

// The backend's cleaning_report.summary (backend/agents/cleaner.py): six
// counts. Cleaning added a column in the demo run, so columns_removed is -1.
const BACKEND_SUMMARY = {
  rows_before: 200,
  rows_after: 185,
  rows_removed: 15,
  columns_before: 9,
  columns_after: 10,
  columns_removed: -1,
};
// The snapshot's four counts (lib/snapshot-rules.mjs, PUBLISHED).
const SNAPSHOT_SUMMARY = { rows_before: 200, rows_after: 185, columns_before: 9, columns_after: 10 };
const CLEANED = { kind: "cleaned", rows: 185, columns: 10, originalRows: 200, originalColumns: 9 };
const ORIGINAL = { kind: "original", rows: 200, columns: 9 };

// Evaluates `expression` (with the module bound to `m`) in a fresh Node
// process whose default locale is `locale`: LC_ALL sets ICU's default, so
// toLocaleString() there follows it, as a browser's follows the visitor's.
function inLocale(locale, expression) {
  const url = pathToFileURL(path.join(HERE, "results.ts")).href;
  const code = `const m = await import(${JSON.stringify(url)}); process.stdout.write(JSON.stringify(${expression}));`;
  const child = spawnSync(process.execPath, ["--input-type=module", "--eval", code], {
    cwd: HERE,
    env: { PATH: process.env.PATH, LC_ALL: locale },
    encoding: "utf8",
  });
  assert.equal(child.status, 0, `child process failed:\n${child.stderr}`);
  return JSON.parse(child.stdout);
}

describe("readHeaderShape", () => {
  it("reads the cleaned counts from the backend's six-count summary, ignoring its derived counts", () => {
    assert.deepEqual(readHeaderShape({ summary: BACKEND_SUMMARY }, 200, 9), CLEANED);
  });

  it("reads the snapshot's four-count summary", () => {
    assert.deepEqual(readHeaderShape({ summary: SNAPSHOT_SUMMARY }, 200, 9), CLEANED);
  });

  it("reads a summary in which nothing changed", () => {
    const summary = { rows_before: 185, rows_after: 185, columns_before: 10, columns_after: 10 };
    assert.deepEqual(readHeaderShape({ summary }, 185, 10), {
      kind: "cleaned",
      rows: 185,
      columns: 10,
      originalRows: 185,
      originalColumns: 10,
    });
  });

  it("falls back to the original file's counts when the summary is missing or invalid", () => {
    const cases = [
      ["no report", null],
      ["no summary", {}],
      ["a null summary", { summary: null }],
      ["an array summary", { summary: [200, 185, 9, 10] }],
      ["a string summary", { summary: "200 185 9 10" }],
      ["a missing count", { summary: { rows_before: 200, rows_after: 185, columns_before: 9 } }],
      ["a fractional count", { summary: { ...SNAPSHOT_SUMMARY, rows_after: 185.5 } }],
      ["a negative count", { summary: { ...SNAPSHOT_SUMMARY, columns_after: -1 } }],
      ["a count as a string", { summary: { ...SNAPSHOT_SUMMARY, rows_after: "185" } }],
      ["NaN", { summary: { ...SNAPSHOT_SUMMARY, rows_after: Number.NaN } }],
    ];
    for (const [what, report] of cases) assert.deepEqual(readHeaderShape(report, 200, 9), ORIGINAL, what);
  });

  it("falls back when a before-count differs from the analysis's own count", () => {
    assert.deepEqual(readHeaderShape({ summary: { ...SNAPSHOT_SUMMARY, rows_before: 201 } }, 200, 9), ORIGINAL);
    assert.deepEqual(readHeaderShape({ summary: { ...SNAPSHOT_SUMMARY, columns_before: 8 } }, 200, 9), ORIGINAL);
  });

  it("falls back when row_count or column_count is null: a null count never equals the summary's", () => {
    assert.deepEqual(readHeaderShape({ summary: SNAPSHOT_SUMMARY }, null, 9), { kind: "original", rows: null, columns: 9 });
    assert.deepEqual(readHeaderShape({ summary: SNAPSHOT_SUMMARY }, 200, null), { kind: "original", rows: 200, columns: null });
  });
});

describe("headerLine", () => {
  it("gives the original file's counts after cleaning, with one sentence for screen readers", () => {
    assert.deepEqual(headerLine(CLEANED), {
      visible: "after cleaning \u00b7 200 \u00d7 9 in the original file",
      spoken: "After cleaning. The original file had 200 rows and 9 columns.",
    });
  });

  it("says when cleaning changed neither count", () => {
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 185, columns: 10, originalRows: 185, originalColumns: 10 }), {
      visible: "after cleaning \u00b7 same as the original file",
      spoken: "After cleaning. The original file had the same 185 rows and 10 columns.",
    });
  });

  it("gives both counts when only one changed", () => {
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 185, columns: 10, originalRows: 185, originalColumns: 9 }), {
      visible: "after cleaning \u00b7 185 \u00d7 9 in the original file",
      spoken: "After cleaning. The original file had 185 rows and 9 columns.",
    });
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 185, columns: 9, originalRows: 200, originalColumns: 9 }), {
      visible: "after cleaning \u00b7 200 \u00d7 9 in the original file",
      spoken: "After cleaning. The original file had 200 rows and 9 columns.",
    });
  });

  it("labels the fallback's counts as the original file's, in one text", () => {
    assert.deepEqual(headerLine(ORIGINAL), { visible: "as in the original file", spoken: null });
  });

  it("gives no line when a count is missing", () => {
    assert.equal(headerLine({ kind: "original", rows: null, columns: 9 }), null);
    assert.equal(headerLine({ kind: "original", rows: 200, columns: null }), null);
    assert.equal(headerLine({ kind: "original", rows: null, columns: null }), null);
  });

  it("uses the singular for one row or one column", () => {
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 1, columns: 2, originalRows: 1, originalColumns: 1 }), {
      visible: "after cleaning \u00b7 1 \u00d7 1 in the original file",
      spoken: "After cleaning. The original file had 1 row and 1 column.",
    });
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 1, columns: 1, originalRows: 1, originalColumns: 1 }), {
      visible: "after cleaning \u00b7 same as the original file",
      spoken: "After cleaning. The original file had the same 1 row and 1 column.",
    });
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 2, columns: 3, originalRows: 2, originalColumns: 1 }), {
      visible: "after cleaning \u00b7 2 \u00d7 1 in the original file",
      spoken: "After cleaning. The original file had 2 rows and 1 column.",
    });
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 1, columns: 2, originalRows: 1, originalColumns: 2 }), {
      visible: "after cleaning \u00b7 same as the original file",
      spoken: "After cleaning. The original file had the same 1 row and 2 columns.",
    });
  });

  it("formats the counts in en-US", () => {
    assert.deepEqual(headerLine({ kind: "cleaned", rows: 1000, columns: 12, originalRows: 1234, originalColumns: 12 }), {
      visible: "after cleaning \u00b7 1,234 \u00d7 12 in the original file",
      spoken: "After cleaning. The original file had 1,234 rows and 12 columns.",
    });
  });
});

describe("formatCount", () => {
  it("formats a count in en-US", () => {
    assert.equal(formatCount(0), "0");
    assert.equal(formatCount(185), "185");
    assert.equal(formatCount(1234), "1,234");
    assert.equal(formatCount(1234567), "1,234,567");
  });

  it("keeps Latin digits under a locale whose digits differ, where toLocaleString() does not (M1)", () => {
    // The old header called toLocaleString(): under fa-IR or ar-SA the browser
    // drew other digits than the prerendered page, and hydration failed.
    assert.equal((200).toLocaleString("fa-IR"), "\u06f2\u06f0\u06f0");
    assert.deepEqual(inLocale("fa_IR.UTF-8", "[m.formatCount(1234), (1234).toLocaleString()]"), [
      "1,234",
      "\u06f1\u066c\u06f2\u06f3\u06f4",
    ]);
    assert.deepEqual(inLocale("ar_SA.UTF-8", "[m.formatCount(1234), (1234).toLocaleString()]"), [
      "1,234",
      "\u0661\u066c\u0662\u0663\u0664",
    ]);
  });
});

describe("splitChartNames", () => {
  // Synthetic names in viz_tools.py's shape: an id, then the chart kind.
  const A = "id_histogram_a.png";
  const B = "id_boxplot_a.png";
  const FLAG = "id_histogram_a_flag.png";

  it("finds two names in one parenthesis, then a longer one (the demo's second paragraph)", () => {
    assert.deepEqual(splitChartNames(`Revenue (${A} ${B}) and the flag (${FLAG}).`, [A, B, FLAG]), [
      "Revenue (",
      { name: A },
      " ",
      { name: B },
      ") and the flag (",
      { name: FLAG },
      ").",
    ]);
  });

  it("finds two names separated by one comma", () => {
    assert.deepEqual(splitChartNames(`${A},${B}`, [A, B]), [{ name: A }, ",", { name: B }]);
  });

  it("finds a name at the very start and at the very end", () => {
    assert.deepEqual(splitChartNames(`${A} then ${B}`, [A, B]), [{ name: A }, " then ", { name: B }]);
  });

  it("leaves a name inside a longer token as text", () => {
    for (const text of [`x${A}`, `${A}_x`, `${A}-x`, `${A}9`, `${A}\u00e9`, `\u00e9${A}`]) {
      assert.deepEqual(splitChartNames(text, [A]), [text], text);
    }
  });

  it("leaves an unlisted name as text", () => {
    assert.deepEqual(splitChartNames(`see ${B}`, [A]), [`see ${B}`]);
  });

  it("returns the text alone when no name is listed, and nothing for empty text", () => {
    assert.deepEqual(splitChartNames("plain text", []), ["plain text"]);
    assert.deepEqual(splitChartNames("", [A]), []);
  });

  it("ignores an empty or repeated name in the list", () => {
    assert.deepEqual(splitChartNames(`(${A}) x`, ["", A, A]), ["(", { name: A }, ") x"]);
  });

  it("takes the longest name at a position when one name continues another", () => {
    const html = `${A}.html`;
    assert.deepEqual(splitChartNames(`see ${html} now`, [A, html]), ["see ", { name: html }, " now"]);
    assert.deepEqual(splitChartNames(`see ${A}. now`, [A, html]), ["see ", { name: A }, ". now"]);
  });
});
