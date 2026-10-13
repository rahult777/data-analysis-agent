// Unit tests for lib/snapshot-rules.mjs: every failure class of the public
// snapshot build, on in-memory values, on temporary snapshot directories and
// on the committed fixtures under e2e/fixtures/. Run with `npm run test:unit`
// (Node's built-in test runner; no dependency). Never put this file under
// e2e/ or e2e-public/: Playwright's default test pattern matches *.test.mjs.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import {
  checkAnalysis,
  checkFileAccounting,
  checkFixtureGuard,
  checkManifest,
  findForbiddenKeys,
  findForeignUuids,
  isPlotlyBundle,
  normalizeKey,
  readSnapshot,
  resolveSnapshotDir,
} from "./snapshot-rules.mjs";
// The published key set's API (M2b.3a), read at call time so that a missing
// export fails its own tests rather than the whole file.
import * as rules from "./snapshot-rules.mjs";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ID = "00000000-0000-4000-a000-000000000001";
const OTHER_ID = "00000000-0000-4000-a000-000000000002";
const PNG = `${ID}_histogram_fixture_value.png`;
const HTML = `${ID}_scatter_fixture_x_fixture_y.html`;
const PLOTLY_HEADER = "/**\n* plotly.js v2.30.0\n* Copyright 2012-2024, Plotly, Inc.\n* All rights reserved.\n* Licensed under the MIT license\n*/\n";
const PLOTLY_STANDIN = `${PLOTLY_HEADER}!function(){}`;

function validAnalysis(id = ID) {
  return {
    id,
    filename: "synthetic_fixture.csv",
    row_count: 4,
    column_count: 2,
    data_quality_score: 0.5,
    cleaning_report: {
      summary: { rows_before: 4, rows_after: 3, columns_before: 2, columns_after: 2 },
    },
    cleaning_decisions: [
      { column_name: "fixture_x", issue: "Synthetic issue.", action: "Synthetic action.", reason: "Synthetic reason." },
      { column_name: null, issue: "Synthetic issue.", action: "Synthetic action.", reason: "Synthetic reason." },
    ],
    analysis_report: {
      correlation_matrix: {
        matrix: { fixture_x: { fixture_x: 1, fixture_y: 0.5 }, fixture_y: { fixture_x: 0.5, fixture_y: null } },
        strong_pairs: [{ col1: "fixture_x", col2: "fixture_y" }],
      },
    },
    insight_report: {
      analyst_layer: { narrative: "Synthetic narrative.", chart_references: [`${id}_histogram_fixture_value.png`] },
      open_questions: [{ question: "Synthetic question?", why_unanswerable: "Synthetic.", what_data_would_answer: "Synthetic." }],
      technical_layer: {
        statistical_methodology: "Synthetic.",
        code_blocks: ["print('synthetic')"],
        limitations: "Synthetic.",
        sophistication_suggestions: "Synthetic.",
        self_evaluation_notes: "Synthetic.",
        lead_override_note: null,
      },
      user_question_addressed: null,
    },
    executive_summary: {
      bullets: [{ finding: "Synthetic finding.", context: "Synthetic context.", recommended_action: "Synthetic action." }],
    },
    chart_paths: [`${id}_histogram_fixture_value.png`, `${id}_scatter_fixture_x_fixture_y.html`],
  };
}

// A deep copy of the valid analysis with `edit` applied.
function analysisWith(edit, id = ID) {
  const value = structuredClone(validAnalysis(id));
  edit(value);
  return value;
}

function validFiles(id = ID) {
  return {
    "manifest.json": { analyses: [{ id }] },
    [`analyses/${id}.json`]: validAnalysis(id),
    [`charts/${id}_histogram_fixture_value.png`]: "\x89PNG synthetic bytes",
    [`charts/${id}_scatter_fixture_x_fixture_y.html`]: "<!doctype html><p>synthetic chart</p>",
    "charts/plotly.min.js": PLOTLY_STANDIN,
  };
}

const tempRoots = [];
after(() => {
  for (const root of tempRoots) fs.rmSync(root, { recursive: true, force: true });
});

// A temporary frontend directory whose snapshot/ holds `files` (relative
// path → content; objects are written as JSON). No files: no snapshot/.
function tempFrontend(files = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "snapshot-rules-"));
  tempRoots.push(root);
  for (const [rel, content] of Object.entries(files)) {
    const file = path.join(root, "snapshot", rel);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, typeof content === "string" ? content : JSON.stringify(content, null, 2));
  }
  return root;
}

function snapshotError(pattern) {
  return { name: "SnapshotError", message: pattern };
}

describe("resolveSnapshotDir", () => {
  it("defaults to frontend/snapshot", () => {
    assert.equal(resolveSnapshotDir("/repo/frontend", {}), path.join("/repo/frontend", "snapshot"));
  });

  it("treats an empty SNAPSHOT_DIR as unset", () => {
    assert.equal(resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: "" }), path.join("/repo/frontend", "snapshot"));
  });

  it("resolves SNAPSHOT_DIR relative to frontend/", () => {
    assert.equal(
      resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: "e2e/fixtures/snapshot" }),
      path.join("/repo/frontend", "e2e/fixtures/snapshot"),
    );
    assert.equal(resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: "..data" }), path.join("/repo/frontend", "..data"));
    assert.equal(resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: "/repo/frontend/x" }), "/repo/frontend/x");
  });

  it("refuses a SNAPSHOT_DIR outside frontend/, or frontend/ itself", () => {
    for (const value of ["..", "../backend/outputs", "/tmp/snapshot", "e2e/../../x", ".", "/repo/frontend"]) {
      assert.throws(
        () => resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: value }),
        snapshotError(`Snapshot: SNAPSHOT_DIR must point to a directory inside frontend/; got ${JSON.stringify(value)}`),
      );
    }
  });

  it("refuses a SNAPSHOT_DIR in public/, out/, .next/ or node_modules/, in any case", () => {
    for (const value of ["public", "public/snapshot", "./out/snapshot", ".next/snapshot", "node_modules/snapshot", "e2e/../out", "/repo/frontend/public/x", "Public/snapshot", "OUT"]) {
      assert.throws(
        () => resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: value }),
        snapshotError(`Snapshot: SNAPSHOT_DIR must not point into public/, out/, .next/ or node_modules/; got ${JSON.stringify(value)}`),
      );
    }
  });

  it("allows folders whose names only begin like those, or nest one deeper", () => {
    for (const value of ["outputs/snapshot", "public-snapshot", ".next-snapshot", "node_modules_snapshot", "e2e/out"]) {
      assert.equal(resolveSnapshotDir("/repo/frontend", { SNAPSHOT_DIR: value }), path.join("/repo/frontend", value));
    }
  });

  it("refuses SNAPSHOT_DIR when VERCEL is set [A2]", () => {
    assert.throws(
      () => resolveSnapshotDir("/repo/frontend", { VERCEL: "1", SNAPSHOT_DIR: "e2e/fixtures/snapshot" }),
      snapshotError("Snapshot: SNAPSHOT_DIR must be unset when VERCEL is set"),
    );
  });

  it("accepts VERCEL without SNAPSHOT_DIR", () => {
    assert.equal(resolveSnapshotDir("/repo/frontend", { VERCEL: "1" }), path.join("/repo/frontend", "snapshot"));
  });
});

describe("checkFixtureGuard", () => {
  it('refuses a fixture manifest unless SNAPSHOT_ALLOW_FIXTURE is exactly "1"', () => {
    for (const env of [{}, { SNAPSHOT_ALLOW_FIXTURE: "" }, { SNAPSHOT_ALLOW_FIXTURE: "true" }, { SNAPSHOT_ALLOW_FIXTURE: "0" }, { SNAPSHOT_ALLOW_FIXTURE: " 1" }]) {
      assert.throws(
        () => checkFixtureGuard(true, env, "snapshot/manifest.json"),
        snapshotError(/^Snapshot: snapshot\/manifest\.json is a test fixture \("fixture": true\); it builds only with SNAPSHOT_ALLOW_FIXTURE=1/),
      );
    }
  });

  it("allows a fixture with SNAPSHOT_ALLOW_FIXTURE=1, and a real manifest always", () => {
    checkFixtureGuard(true, { SNAPSHOT_ALLOW_FIXTURE: "1" }, "x");
    checkFixtureGuard(false, {}, "x");
    checkFixtureGuard(false, { SNAPSHOT_ALLOW_FIXTURE: "1" }, "x");
  });
});

describe("checkManifest", () => {
  it("accepts a manifest and returns its ids", () => {
    assert.deepEqual(checkManifest({ analyses: [{ id: ID }, { id: OTHER_ID }] }), {
      ids: [ID, OTHER_ID],
      fixture: false,
      problems: [],
    });
    assert.deepEqual(checkManifest({ fixture: true, analyses: [{ id: ID }] }), { ids: [ID], fixture: true, problems: [] });
  });

  it("rejects a manifest that is not an object", () => {
    for (const value of [null, [], "x", 3]) {
      assert.deepEqual(checkManifest(value).problems, ["must be a JSON object"]);
    }
  });

  it("rejects a missing, empty or non-array analyses list", () => {
    assert.deepEqual(checkManifest({}).problems, ['missing key "analyses"']);
    assert.deepEqual(checkManifest({ analyses: [] }).problems, ['"analyses" is empty']);
    assert.deepEqual(checkManifest({ analyses: { id: ID } }).problems, ['"analyses" must be an array']);
  });

  it("rejects unknown keys at the top and in each entry", () => {
    assert.deepEqual(checkManifest({ analyses: [{ id: ID }], title: "x" }).problems, ['unknown key "title"']);
    assert.deepEqual(checkManifest({ analyses: [{ id: ID, name: "x" }] }).problems, ['unknown key "analyses[0].name"']);
  });

  it('accepts "fixture" only as true', () => {
    for (const fixture of [false, "true", 1, null]) {
      assert.deepEqual(checkManifest({ fixture, analyses: [{ id: ID }] }).problems, ['"fixture" must be true when present']);
    }
  });

  it("rejects an entry that is not an object or has no id", () => {
    assert.deepEqual(checkManifest({ analyses: [ID] }).problems, ["analyses[0] must be an object"]);
    assert.deepEqual(checkManifest({ analyses: [{}] }).problems, ['missing key "analyses[0].id"']);
  });

  it("rejects an id that is not a lowercase canonical UUID", () => {
    for (const id of [ID.toUpperCase(), `{${ID}}`, ID.replace(/-/g, ""), ID.slice(1), `${ID} `, "not-a-uuid", 7]) {
      assert.deepEqual(checkManifest({ analyses: [{ id }] }).problems, [
        `analyses[0].id ${JSON.stringify(id)} is not a lowercase canonical UUID`,
      ]);
    }
  });

  it("rejects a duplicate id", () => {
    assert.deepEqual(checkManifest({ analyses: [{ id: ID }, { id: ID }] }).problems, [`analyses[1].id duplicates ${ID}`]);
  });
});

describe("checkAnalysis (the SnapshotAnalysis contract)", () => {
  it("accepts the valid analysis", () => {
    assert.deepEqual(checkAnalysis(validAnalysis(), ID), []);
  });

  it("rejects a value that is not an object", () => {
    assert.deepEqual(checkAnalysis([], ID), ["must be a JSON object"]);
  });

  it("rejects unknown and missing top-level keys", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.status = "complete")), ID), ['unknown key "status"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.profile_report = {})), ID), ['unknown key "profile_report"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => delete a.chart_paths), ID), ['missing key "chart_paths"']);
  });

  it("rejects an id that differs from the manifest", () => {
    assert.deepEqual(checkAnalysis(validAnalysis(), OTHER_ID), [`id "${ID}" differs from the manifest id ${OTHER_ID}`]);
  });

  it("checks the header fields", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.filename = "")), ID), ["filename must be a non-empty string"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.row_count = null)), ID), ["row_count must be a non-negative integer"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.column_count = 2.5)), ID), ["column_count must be a non-negative integer"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.data_quality_score = 1.2)), ID), ["data_quality_score must be a number from 0 to 1"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.data_quality_score = "0.5")), ID), ["data_quality_score must be a number from 0 to 1"]);
  });

  it("allows only summary, with exactly its four counts, in cleaning_report", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.operations = [])), ID), ['unknown key "cleaning_report.operations"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report = null)), ID), ["cleaning_report must be an object"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => delete a.cleaning_report.summary), ID), ['missing key "cleaning_report.summary"']);
    for (const key of ["rows_before", "rows_after", "columns_before", "columns_after"]) {
      assert.deepEqual(checkAnalysis(analysisWith((a) => delete a.cleaning_report.summary[key]), ID), [
        `missing key "cleaning_report.summary.${key}"`,
      ]);
    }
    // The derived counts are not published (owner ruling D1): columns_removed is -1 when cleaning adds a column.
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.summary.rows_removed = 1)), ID), [
      'unknown key "cleaning_report.summary.rows_removed"',
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.summary.columns_removed = -1)), ID), [
      'unknown key "cleaning_report.summary.columns_removed"',
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.summary.notes = "x")), ID), [
      'unknown key "cleaning_report.summary.notes"',
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.summary.rows_after = -1)), ID), [
      "cleaning_report.summary.rows_after must be a non-negative integer",
    ]);
  });

  it("requires the summary's before-counts to equal row_count and column_count (the upload's shape)", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.summary.rows_before = 5)), ID), [
      "cleaning_report.summary.rows_before (5) must equal row_count (4)",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.column_count = 9)), ID), [
      "cleaning_report.summary.columns_before (2) must equal column_count (9)",
    ]);
    // A count that is itself invalid is reported once, without a comparison.
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.row_count = null)), ID), ["row_count must be a non-negative integer"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_report.summary.columns_before = "2")), ID), [
      "cleaning_report.summary.columns_before must be a non-negative integer",
    ]);
  });

  it("allows only correlation_matrix in analysis_report and checks what the matrix view reads", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation = {})), ID), ['unknown key "analysis_report.correlation"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => delete a.analysis_report.correlation_matrix.matrix), ID), [
      'missing key "analysis_report.correlation_matrix.matrix"',
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation_matrix.matrix.fixture_x.fixture_y = "0.5")), ID), [
      "analysis_report.correlation_matrix.matrix must map column names to objects of numbers or null",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation_matrix.strong_pairs = {})), ID), [
      "analysis_report.correlation_matrix.strong_pairs must be an array",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation_matrix.strong_pairs[0].col2 = 3)), ID), [
      "analysis_report.correlation_matrix.strong_pairs[0].col2 must be a string",
    ]);
    // Only what the page reads (owner ruling D3): matrix and strong_pairs, and col1/col2 in each pair.
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation_matrix.method = "pearson")), ID), [
      'unknown key "analysis_report.correlation_matrix.method"',
    ]);
    assert.deepEqual(
      checkAnalysis(analysisWith((a) => Object.assign(a.analysis_report.correlation_matrix, { highest_pair: ["fixture_x", "fixture_y"], highest_value: 0.5 })), ID),
      ['unknown key "analysis_report.correlation_matrix.highest_pair"', 'unknown key "analysis_report.correlation_matrix.highest_value"'],
    );
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation_matrix.strong_pairs[0].r = 0.5)), ID), [
      'unknown key "analysis_report.correlation_matrix.strong_pairs[0].r"',
    ]);
    // The matrix itself is a leaf: its keys are column names.
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.analysis_report.correlation_matrix.matrix.fixture_x.any_column = 0.1)), ID), []);
  });

  it("allows only the four insight_report keys and checks what the layers' views read", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.executive_layer = {})), ID), ['unknown key "insight_report.executive_layer"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => delete a.insight_report.open_questions), ID), ['missing key "insight_report.open_questions"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.analyst_layer.narrative = ["x"])), ID), [
      "insight_report.analyst_layer.narrative must be a string",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.analyst_layer.chart_references = [1])), ID), [
      "insight_report.analyst_layer.chart_references must be an array of strings",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.open_questions = {})), ID), ["insight_report.open_questions must be an array"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.open_questions[0].question = null)), ID), [
      "insight_report.open_questions[0].question must be a string",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.technical_layer.code_blocks = "x")), ID), [
      "insight_report.technical_layer.code_blocks must be an array of strings",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.technical_layer.lead_override_note = 1)), ID), [
      "insight_report.technical_layer.lead_override_note must be a string or null",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.user_question_addressed = 1)), ID), [
      "insight_report.user_question_addressed must be a string or null",
    ]);
    // Only what the page reads (owner ruling D3), inside every layer and every open question.
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.analyst_layer.confidence = "High")), ID), [
      'unknown key "insight_report.analyst_layer.confidence"',
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.technical_layer.cleaning_methodology = "x")), ID), [
      'unknown key "insight_report.technical_layer.cleaning_methodology"',
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.insight_report.open_questions[0].priority = "high")), ID), [
      'unknown key "insight_report.open_questions[0].priority"',
    ]);
  });

  it("allows only bullets in executive_summary, and in each bullet only the three keys the page reads", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.executive_summary.headline = "x")), ID), ['unknown key "executive_summary.headline"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.executive_summary = {})), ID), ['missing key "executive_summary.bullets"']);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.executive_summary.bullets[0].confidence = "High")), ID), [
      'unknown key "executive_summary.bullets[0].confidence"',
    ]);
  });

  it("checks what the executive summary and the cleaning decisions views read", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.executive_summary = { bullets: "x" })), ID), ["executive_summary.bullets must be an array"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.executive_summary.bullets[0].finding = 1)), ID), [
      "executive_summary.bullets[0].finding must be a string",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_decisions = {})), ID), ["cleaning_decisions must be an array"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_decisions[0].column_name = 1)), ID), [
      "cleaning_decisions[0].column_name must be a string or null",
    ]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => delete a.cleaning_decisions[1].reason), ID), ["cleaning_decisions[1].reason must be a string"]);
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.cleaning_decisions[0].operation = "fill_missing")), ID), [
      'unknown key "cleaning_decisions[0].operation"',
    ]);
  });

  it("checks chart_paths: an array of distinct plain .png or .html file names", () => {
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.chart_paths = "x.png")), ID), ["chart_paths must be an array"]);
    for (const name of ["../x.png", "a/b.png", ".hidden.png", "x.svg", "x.PNG", "plotly.min.js", "x y.png", 3]) {
      assert.deepEqual(checkAnalysis(analysisWith((a) => (a.chart_paths = [name])), ID), [
        `chart_paths[0] ${JSON.stringify(name)} is not a chart file name (a plain name ending in .png or .html, with no other dot)`,
      ]);
    }
    assert.deepEqual(checkAnalysis(analysisWith((a) => a.chart_paths.push(a.chart_paths[0])), ID), [`chart_paths[2] duplicates "${PNG}"`]);
    // _safe_name keeps Unicode word characters.
    assert.deepEqual(checkAnalysis(analysisWith((a) => (a.chart_paths = [`${ID}_histogram_größe.png`])), ID), []);
  });

  it("rejects a chart name with an inner dot: x.png.html would become x.png once chartUrl drops .html", () => {
    for (const name of [`${ID}_scatter_x.png.html`, "x.png.png", "a.b.png", "x..html"]) {
      assert.deepEqual(checkAnalysis(analysisWith((a) => (a.chart_paths = [name])), ID), [
        `chart_paths[0] ${JSON.stringify(name)} is not a chart file name (a plain name ending in .png or .html, with no other dot)`,
      ]);
    }
  });
});

describe("the published key set (PUBLISHED; owner ruling D3: publish only what the page renders)", () => {
  // What GET /api/analysis/{id} returns for a finished run, keys shuffled,
  // with keys the page never reads at every level.
  function richAnalysis() {
    const a = validAnalysis();
    return {
      status: "complete",
      chart_paths: a.chart_paths,
      executive_summary: {
        bullets: a.executive_summary.bullets.map((b) => ({ context: b.context, recommended_action: b.recommended_action, finding: b.finding, confidence: "High" })),
      },
      created_at: "2026-10-03T08:00:00+00:00",
      insight_report: {
        user_question_addressed: null,
        technical_layer: { ...a.insight_report.technical_layer, cleaning_methodology: "Synthetic methodology." },
        executive_layer: { bullets: [] },
        open_questions: a.insight_report.open_questions.map((q) => ({ ...q, priority: "high" })),
        analyst_layer: { chart_references: a.insight_report.analyst_layer.chart_references, narrative: a.insight_report.analyst_layer.narrative },
        data_quality_score: 0.5,
      },
      analysis_report: {
        descriptive_stats: {},
        correlation_matrix: {
          highest_value: 0.5,
          strong_pairs: [{ r: 0.5, col2: "fixture_y", col1: "fixture_x", n: 3 }],
          highest_pair: ["fixture_x", "fixture_y"],
          matrix: a.analysis_report.correlation_matrix.matrix,
        },
        chart_paths: a.chart_paths,
      },
      cleaning_decisions: a.cleaning_decisions.map((d) => ({ reason: d.reason, action: d.action, issue: d.issue, column_name: d.column_name })),
      cleaning_report: { summary: { ...a.cleaning_report.summary, rows_removed: 1, columns_removed: 0 }, decisions: a.cleaning_decisions },
      profile_report: { domain_hypothesis: "Synthetic" },
      data_quality_score: a.data_quality_score,
      column_count: a.column_count,
      row_count: a.row_count,
      filename: a.filename,
      id: a.id,
    };
  }

  // Every key the rich analysis has and the page does not read, in walk order.
  const DROPPED = [
    "status",
    "executive_summary.bullets[0].confidence",
    "created_at",
    "insight_report.technical_layer.cleaning_methodology",
    "insight_report.executive_layer",
    "insight_report.open_questions[0].priority",
    "insight_report.data_quality_score",
    "analysis_report.descriptive_stats",
    "analysis_report.correlation_matrix.highest_value",
    "analysis_report.correlation_matrix.strong_pairs[0].r",
    "analysis_report.correlation_matrix.strong_pairs[0].n",
    "analysis_report.correlation_matrix.highest_pair",
    "analysis_report.chart_paths",
    "cleaning_report.summary.rows_removed",
    "cleaning_report.summary.columns_removed",
    "cleaning_report.decisions",
    "profile_report",
  ];

  // Every key path of a value, array items as [i].
  function keyPaths(value, where = "") {
    if (Array.isArray(value)) return value.flatMap((item, i) => keyPaths(item, `${where}[${i}]`));
    if (typeof value !== "object" || value === null) return [];
    return Object.entries(value).flatMap(([key, child]) => {
      const at = where === "" ? key : `${where}.${key}`;
      return [at, ...keyPaths(child, at)];
    });
  }

  // Every path the definition names, array items as [].
  function definitionPaths(node, where = "") {
    return Object.entries(node).flatMap(([key, child]) => {
      const at = where === "" ? key : `${where}.${key}`;
      if (child === true) return [at];
      return Array.isArray(child) ? [at, ...definitionPaths(child[0], `${at}[]`)] : [at, ...definitionPaths(child, at)];
    });
  }

  it("projectPublished keeps exactly the keys the page reads, at every level, in the definition's order", () => {
    assert.equal(JSON.stringify(rules.projectPublished(richAnalysis())), JSON.stringify(validAnalysis()));
  });

  it("unpublishedEntries lists every other key by path, with its value; findUnpublishedKeys reports them as unknown keys", () => {
    const rich = richAnalysis();
    assert.deepEqual(rules.unpublishedEntries(rich).map((entry) => entry.path), DROPPED);
    assert.deepEqual(rules.unpublishedEntries(rich).find((entry) => entry.path === "profile_report")?.value, { domain_hypothesis: "Synthetic" });
    assert.deepEqual(rules.findUnpublishedKeys(rich), DROPPED.map((at) => `unknown key ${JSON.stringify(at)}`));
    assert.deepEqual(rules.unpublishedEntries(validAnalysis()), []);
  });

  it("the projection and the unpublished entries account for every key of the input, each exactly once", () => {
    const rich = richAnalysis();
    const kept = new Set(keyPaths(rules.projectPublished(rich)));
    const dropped = rules.unpublishedEntries(rich).map((entry) => entry.path);
    for (const at of keyPaths(rich)) {
      const underDropped = dropped.some((d) => at === d || at.startsWith(`${d}.`) || at.startsWith(`${d}[`));
      assert.equal(kept.has(at) !== underDropped, true, at);
    }
  });

  it("leaves a value of the wrong shape as it is, for the rules to report", () => {
    const odd = analysisWith((a) => ((a.insight_report.technical_layer = "x"), (a.cleaning_decisions = {})));
    const projected = rules.projectPublished(odd);
    assert.equal(projected.insight_report.technical_layer, "x");
    assert.deepEqual(projected.cleaning_decisions, {});
    assert.deepEqual(checkAnalysis(projected, ID), ["cleaning_decisions must be an array", "insight_report.technical_layer must be an object"]);
  });

  it("is idempotent, never adds a key, returns a new object, and treats inherited names as unknown keys", () => {
    const rich = richAnalysis();
    const once = rules.projectPublished(rich);
    assert.deepEqual(rules.projectPublished(once), once);
    assert.notEqual(once, rich);
    const partial = { id: ID, insight_report: { analyst_layer: {} } };
    assert.deepEqual(rules.projectPublished(partial), partial);
    const inherited = JSON.parse(`{"id":"${ID}","constructor":1,"__proto__":{"x":1},"insight_report":{"toString":"x"}}`);
    assert.deepEqual(rules.findUnpublishedKeys(inherited), ['unknown key "constructor"', 'unknown key "__proto__"', 'unknown key "insight_report.toString"']);
    assert.deepEqual(keyPaths(rules.projectPublished(inherited)), ["id", "insight_report"]);
  });

  it("its projection of a full GET response passes the contract", () => {
    assert.deepEqual(checkAnalysis(rules.projectPublished(richAnalysis()), ID), []);
  });

  it("defines exactly these paths, frozen (a change here is a publication decision)", () => {
    assert.deepEqual(definitionPaths(rules.PUBLISHED), [
      "id",
      "filename",
      "row_count",
      "column_count",
      "data_quality_score",
      "cleaning_report",
      "cleaning_report.summary",
      "cleaning_report.summary.rows_before",
      "cleaning_report.summary.rows_after",
      "cleaning_report.summary.columns_before",
      "cleaning_report.summary.columns_after",
      "cleaning_decisions",
      "cleaning_decisions[].column_name",
      "cleaning_decisions[].issue",
      "cleaning_decisions[].action",
      "cleaning_decisions[].reason",
      "analysis_report",
      "analysis_report.correlation_matrix",
      "analysis_report.correlation_matrix.matrix",
      "analysis_report.correlation_matrix.strong_pairs",
      "analysis_report.correlation_matrix.strong_pairs[].col1",
      "analysis_report.correlation_matrix.strong_pairs[].col2",
      "insight_report",
      "insight_report.analyst_layer",
      "insight_report.analyst_layer.narrative",
      "insight_report.analyst_layer.chart_references",
      "insight_report.open_questions",
      "insight_report.open_questions[].question",
      "insight_report.open_questions[].why_unanswerable",
      "insight_report.open_questions[].what_data_would_answer",
      "insight_report.technical_layer",
      "insight_report.technical_layer.statistical_methodology",
      "insight_report.technical_layer.code_blocks",
      "insight_report.technical_layer.limitations",
      "insight_report.technical_layer.sophistication_suggestions",
      "insight_report.technical_layer.self_evaluation_notes",
      "insight_report.technical_layer.lead_override_note",
      "insight_report.user_question_addressed",
      "executive_summary",
      "executive_summary.bullets",
      "executive_summary.bullets[].finding",
      "executive_summary.bullets[].context",
      "executive_summary.bullets[].recommended_action",
      "chart_paths",
    ]);
    for (const node of [rules.PUBLISHED, rules.PUBLISHED.insight_report.technical_layer, rules.PUBLISHED.cleaning_decisions, rules.PUBLISHED.cleaning_decisions[0]]) {
      assert.equal(Object.isFrozen(node), true);
    }
  });
});

describe("findForbiddenKeys", () => {
  const forbidden = ["session_id", "stored_filename", "file_size", "pause_data", "user_pause_response", "error_message", "updated_at", "original_filename"];

  it("finds every forbidden key at any depth, inside arrays too", () => {
    for (const key of forbidden) {
      assert.deepEqual(findForbiddenKeys({ a: [{ b: { [key]: 1 } }] }), [`forbidden key "${key}" at a[0].b.${key}`]);
    }
  });

  it("normalizes names: case and non-alphanumerics do not matter", () => {
    for (const key of ["sessionId", "session-id", "SESSION_ID", "Session ID", "updatedAt", "pauseData"]) {
      assert.deepEqual(findForbiddenKeys({ [key]: "x" }), [`forbidden key "${key}" at ${key}`]);
    }
    assert.equal(normalizeKey("Session-ID"), "sessionid");
  });

  it("matches whole names only, and keys only, never values", () => {
    assert.deepEqual(findForbiddenKeys({ session_identifier: 1, notes: "session_id", list: ["error_message"] }), []);
  });
});

describe("findForeignUuids", () => {
  it("ignores the file's own id, in any case", () => {
    assert.deepEqual(findForeignUuids(`${ID} ${ID.toUpperCase()}`, ID), []);
  });

  it("reports every other UUID once, lower-cased", () => {
    const text = `x ${OTHER_ID} y ${OTHER_ID.toUpperCase()} 1f0317e4-cbad-4f76-94b7-7bfe419ccdbe`;
    assert.deepEqual(findForeignUuids(text, ID), [OTHER_ID, "1f0317e4-cbad-4f76-94b7-7bfe419ccdbe"]);
  });

  it("treats every UUID as foreign when there is no own id", () => {
    assert.deepEqual(findForeignUuids(`a ${ID}`, null), [ID]);
  });
});

describe("isPlotlyBundle", () => {
  it("accepts plotly's header comment and nothing else", () => {
    assert.equal(isPlotlyBundle(`${PLOTLY_HEADER}!function(t){}`), true);
    assert.equal(isPlotlyBundle("console.log('plotly.js v2.30.0')"), false);
    assert.equal(isPlotlyBundle(`\n${PLOTLY_HEADER}`), false);
    assert.equal(isPlotlyBundle(""), false);
  });
});

describe("checkFileAccounting", () => {
  const file = (name) => ({ name, kind: "file" });
  const dir = (name) => ({ name, kind: "dir" });
  const charts = [
    { name: PNG, id: ID },
    { name: HTML, id: ID },
  ];
  const valid = () => ({
    top: [file("manifest.json"), dir("analyses"), dir("charts")],
    analyses: [file(`${ID}.json`)],
    charts: [file(PNG), file(HTML), file("plotly.min.js")],
  });

  it("accepts exactly the manifest's files", () => {
    assert.deepEqual(checkFileAccounting(valid(), { ids: [ID], charts }), []);
  });

  it("ignores .DS_Store by name at every level", () => {
    const listing = valid();
    listing.top.push(file(".DS_Store"));
    listing.analyses.push(file(".DS_Store"));
    listing.charts.push(file(".DS_Store"));
    assert.deepEqual(checkFileAccounting(listing, { ids: [ID], charts }), []);
  });

  it("rejects anything the manifest does not account for", () => {
    const listing = valid();
    listing.top.push(file("README.md"), dir("extra"));
    listing.analyses.push(file(`${OTHER_ID}.json`), dir("old"));
    assert.deepEqual(checkFileAccounting(listing, { ids: [ID], charts }), [
      'unaccounted entry "README.md" in the snapshot dir',
      'unaccounted entry "extra" in the snapshot dir',
      `unaccounted entry "analyses/${OTHER_ID}.json"`,
      'unaccounted entry "analyses/old"',
    ]);
  });

  it("rejects an id with no file", () => {
    assert.deepEqual(checkFileAccounting({ ...valid(), analyses: [] }, { ids: [ID], charts }), [
      `analysis ${ID} has no file analyses/${ID}.json`,
    ]);
    assert.deepEqual(checkFileAccounting({ ...valid(), top: [file("manifest.json"), dir("charts")], analyses: null }, { ids: [ID], charts }), [
      `analysis ${ID} has no file analyses/${ID}.json`,
    ]);
  });

  it("rejects a listed chart with no file, and a file no analysis lists", () => {
    assert.deepEqual(checkFileAccounting({ ...valid(), charts: [file(PNG), file("other.png"), file("plotly.min.js")] }, { ids: [ID], charts }), [
      `chart "${HTML}" listed by ${ID} has no file in charts/`,
      'unaccounted entry "charts/other.png"',
    ]);
  });

  it("allows plotly.min.js only when an analysis lists an HTML chart", () => {
    assert.deepEqual(checkFileAccounting(valid(), { ids: [ID], charts }), []);
    assert.deepEqual(
      checkFileAccounting({ ...valid(), charts: [file(PNG), file("plotly.min.js")] }, { ids: [ID], charts: [{ name: PNG, id: ID }] }),
      ["charts/plotly.min.js is allowed only when an analysis lists an HTML chart"],
    );
  });

  it("requires plotly.min.js when an analysis lists an HTML chart: the chart loads it (M2b.2 Code Review #2)", () => {
    assert.deepEqual(checkFileAccounting({ ...valid(), charts: [file(PNG), file(HTML)] }, { ids: [ID], charts }), [
      "charts/plotly.min.js is required when an analysis lists an HTML chart",
    ]);
    // A PNG-only snapshot needs none.
    assert.deepEqual(checkFileAccounting({ ...valid(), charts: [file(PNG)] }, { ids: [ID], charts: [{ name: PNG, id: ID }] }), []);
  });

  it("rejects entries of the wrong kind (a symlink, or a directory where a file belongs)", () => {
    const listing = valid();
    listing.top[0] = { name: "manifest.json", kind: "other" };
    listing.analyses = [{ name: `${ID}.json`, kind: "other" }];
    listing.charts = [{ name: PNG, kind: "other" }, dir(HTML), file("plotly.min.js")];
    assert.deepEqual(checkFileAccounting(listing, { ids: [ID], charts }), [
      "manifest.json must be a regular file",
      `analyses/${ID}.json must be a regular file`,
      `charts/${PNG} must be a regular file`,
      `charts/${HTML} must be a regular file`,
    ]);
  });

  it("rejects analyses or charts that are not directories", () => {
    const listing = valid();
    listing.top = [file("manifest.json"), file("analyses"), file("charts")];
    assert.deepEqual(checkFileAccounting({ ...listing, analyses: null, charts: null }, { ids: [ID], charts: [] }), [
      "analyses must be a directory",
      "charts must be a directory",
      `analysis ${ID} has no file analyses/${ID}.json`,
    ]);
  });
});

describe("readSnapshot (temporary snapshot directories)", () => {
  it("reads a valid snapshot", () => {
    const root = tempFrontend(validFiles());
    const snapshot = readSnapshot(root, {});
    assert.equal(snapshot.dir, path.join(root, "snapshot"));
    assert.deepEqual(snapshot.ids, [ID]);
    assert.equal(snapshot.fixture, false);
    assert.deepEqual(snapshot.analyses, [validAnalysis()]);
    assert.deepEqual(snapshot.charts, [PNG, HTML]);
    assert.equal(snapshot.plotly, true);
  });

  it("fails on an HTML chart without plotly.min.js beside it", () => {
    const files = validFiles();
    delete files["charts/plotly.min.js"];
    assert.throws(
      () => readSnapshot(tempFrontend(files), {}),
      snapshotError("Snapshot: 1 problem in snapshot:\n  - charts/plotly.min.js is required when an analysis lists an HTML chart"),
    );
  });

  it("works with no charts at all (no charts/ directory)", () => {
    const files = { "manifest.json": { analyses: [{ id: ID }] }, [`analyses/${ID}.json`]: analysisWith((a) => (a.chart_paths = [])) };
    assert.deepEqual(readSnapshot(tempFrontend(files), {}).charts, []);
  });

  it("fails on a missing snapshot dir or manifest", () => {
    assert.throws(() => readSnapshot(tempFrontend(), {}), snapshotError("Snapshot: no manifest at snapshot/manifest.json"));
    const files = validFiles();
    delete files["manifest.json"];
    assert.throws(() => readSnapshot(tempFrontend(files), {}), snapshotError("Snapshot: no manifest at snapshot/manifest.json"));
  });

  it("fails on a manifest that is not JSON, or invalid", () => {
    assert.throws(
      () => readSnapshot(tempFrontend({ ...validFiles(), "manifest.json": "{" }), {}),
      snapshotError("Snapshot: snapshot/manifest.json is not valid JSON"),
    );
    assert.throws(
      () => readSnapshot(tempFrontend({ ...validFiles(), "manifest.json": { analyses: [] } }), {}),
      snapshotError('Snapshot: 1 problem in snapshot/manifest.json:\n  - "analyses" is empty'),
    );
  });

  it("applies the fixture guard", () => {
    const files = { ...validFiles(), "manifest.json": { fixture: true, analyses: [{ id: ID }] } };
    assert.throws(() => readSnapshot(tempFrontend(files), {}), snapshotError(/is a test fixture/));
    assert.equal(readSnapshot(tempFrontend(files), { SNAPSHOT_ALLOW_FIXTURE: "1" }).fixture, true);
  });

  it("fails on an analysis file that is not JSON, or breaks the contract, with every problem listed", () => {
    assert.throws(
      () => readSnapshot(tempFrontend({ ...validFiles(), [`analyses/${ID}.json`]: "not json" }), {}),
      snapshotError(`Snapshot: 1 problem in snapshot:\n  - analyses/${ID}.json is not valid JSON`),
    );
    const files = { ...validFiles(), [`analyses/${ID}.json`]: analysisWith((a) => ((a.status = "complete"), (a.row_count = -1))) };
    assert.throws(
      () => readSnapshot(tempFrontend(files), {}),
      snapshotError(
        `Snapshot: 2 problems in snapshot:\n  - analyses/${ID}.json: unknown key "status"\n  - analyses/${ID}.json: row_count must be a non-negative integer`,
      ),
    );
  });

  it("fails on a forbidden key anywhere in an analysis", () => {
    // Inside a defined object it is also an unknown key (owner ruling D3); both rules report it.
    const files = { ...validFiles(), [`analyses/${ID}.json`]: analysisWith((a) => (a.executive_summary.bullets[0].sessionId = "s")) };
    assert.throws(
      () => readSnapshot(tempFrontend(files), {}),
      snapshotError(
        `Snapshot: 2 problems in snapshot:\n  - analyses/${ID}.json: unknown key "executive_summary.bullets[0].sessionId"\n  - analyses/${ID}.json: forbidden key "sessionId" at executive_summary.bullets[0].sessionId`,
      ),
    );
    // Inside a leaf (the matrix's keys are column names) only the forbidden-key rule can catch it.
    const leaf = { ...validFiles(), [`analyses/${ID}.json`]: analysisWith((a) => (a.analysis_report.correlation_matrix.matrix.session_id = { fixture_x: 0.1 })) };
    assert.throws(
      () => readSnapshot(tempFrontend(leaf), {}),
      snapshotError(`Snapshot: 1 problem in snapshot:\n  - analyses/${ID}.json: forbidden key "session_id" at analysis_report.correlation_matrix.matrix.session_id`),
    );
  });

  it("fails on a foreign UUID in the JSON or in a chart file", () => {
    const json = { ...validFiles(), [`analyses/${ID}.json`]: analysisWith((a) => (a.insight_report.analyst_layer.narrative = `See ${OTHER_ID}.`)) };
    assert.throws(
      () => readSnapshot(tempFrontend(json), {}),
      snapshotError(`Snapshot: 1 problem in snapshot:\n  - analyses/${ID}.json contains a UUID other than its own id: ${OTHER_ID}`),
    );
    const chart = { ...validFiles(), [`charts/${HTML}`]: `<div id="1f0317e4-cbad-4f76-94b7-7bfe419ccdbe"></div>` };
    assert.throws(
      () => readSnapshot(tempFrontend(chart), {}),
      snapshotError(`Snapshot: 1 problem in snapshot:\n  - charts/${HTML} contains a UUID other than its analysis id ${ID}: 1f0317e4-cbad-4f76-94b7-7bfe419ccdbe`),
    );
  });

  it("fails on unaccounted files and chart mismatches", () => {
    const files = { ...validFiles(), "notes.txt": "x", [`charts/${ID}_barchart_extra.png`]: "x" };
    delete files[`charts/${PNG}`];
    assert.throws(
      () => readSnapshot(tempFrontend(files), {}),
      snapshotError(
        `Snapshot: 3 problems in snapshot:\n  - unaccounted entry "notes.txt" in the snapshot dir\n  - chart "${PNG}" listed by ${ID} has no file in charts/\n  - unaccounted entry "charts/${ID}_barchart_extra.png"`,
      ),
    );
  });

  it("accepts plotly.min.js with an HTML chart, and checks its header and its UUIDs", () => {
    const ok = { ...validFiles(), "charts/plotly.min.js": `${PLOTLY_HEADER}!function(){}` };
    assert.equal(readSnapshot(tempFrontend(ok), {}).plotly, true);
    const header = { ...validFiles(), "charts/plotly.min.js": "!function(){}" };
    assert.throws(
      () => readSnapshot(tempFrontend(header), {}),
      snapshotError('Snapshot: 1 problem in snapshot:\n  - charts/plotly.min.js does not begin with plotly\'s header comment ("plotly.js v")'),
    );
    const uuid = { ...validFiles(), "charts/plotly.min.js": `${PLOTLY_HEADER}var id="${ID}";` };
    assert.throws(
      () => readSnapshot(tempFrontend(uuid), {}),
      snapshotError(`Snapshot: 1 problem in snapshot:\n  - charts/plotly.min.js contains a UUID: ${ID}`),
    );
  });

  it("rejects symlinks: they could pull files from outside the snapshot dir", () => {
    const root = tempFrontend(validFiles());
    const outside = path.join(root, "outside.png");
    fs.writeFileSync(outside, "x");
    fs.rmSync(path.join(root, "snapshot", "charts", PNG));
    fs.symlinkSync(outside, path.join(root, "snapshot", "charts", PNG));
    assert.throws(() => readSnapshot(root, {}), snapshotError(`Snapshot: 1 problem in snapshot:\n  - charts/${PNG} must be a regular file`));
  });

  it("reports a snapshot dir that is not a directory", () => {
    const root = tempFrontend();
    fs.writeFileSync(path.join(root, "snapshot"), "x");
    assert.throws(() => readSnapshot(root, {}), snapshotError("Snapshot: snapshot must be a directory (not a symlink)"));
  });

  it("returns each chart once, in manifest order, when two analyses are listed", () => {
    const files = {
      ...validFiles(ID),
      ...validFiles(OTHER_ID),
      "manifest.json": { analyses: [{ id: ID }, { id: OTHER_ID }] },
    };
    const snapshot = readSnapshot(tempFrontend(files), {});
    assert.deepEqual(snapshot.ids, [ID, OTHER_ID]);
    assert.deepEqual(snapshot.charts, [PNG, HTML, `${OTHER_ID}_histogram_fixture_value.png`, `${OTHER_ID}_scatter_fixture_x_fixture_y.html`]);
  });
});

describe("the committed fixtures (e2e/fixtures/)", () => {
  const read = (dir, env = {}) => readSnapshot(FRONTEND, { SNAPSHOT_DIR: dir, ...env });

  it("e2e/fixtures/snapshot is valid and marked as a fixture", () => {
    const snapshot = read("e2e/fixtures/snapshot", { SNAPSHOT_ALLOW_FIXTURE: "1" });
    assert.deepEqual(snapshot.ids, [ID]);
    assert.equal(snapshot.fixture, true);
    assert.deepEqual(snapshot.charts, [PNG, HTML]);
    assert.equal(snapshot.plotly, true);
  });

  it("e2e/fixtures/snapshot is refused without SNAPSHOT_ALLOW_FIXTURE=1", () => {
    assert.throws(() => read("e2e/fixtures/snapshot"), snapshotError(/is a test fixture/));
  });

  it("snapshot-broken/missing-manifest fails: no manifest", () => {
    assert.throws(
      () => read("e2e/fixtures/snapshot-broken/missing-manifest", { SNAPSHOT_ALLOW_FIXTURE: "1" }),
      snapshotError("Snapshot: no manifest at e2e/fixtures/snapshot-broken/missing-manifest/manifest.json"),
    );
  });

  it("snapshot-broken/forbidden-key fails on its forbidden key only", () => {
    // The key sits in the correlation matrix, a leaf: in a defined object it would also be an unknown key.
    assert.throws(
      () => read("e2e/fixtures/snapshot-broken/forbidden-key", { SNAPSHOT_ALLOW_FIXTURE: "1" }),
      snapshotError(
        `Snapshot: 1 problem in e2e/fixtures/snapshot-broken/forbidden-key:\n  - analyses/${ID}.json: forbidden key "sessionId" at analysis_report.correlation_matrix.matrix.sessionId`,
      ),
    );
  });

  it("snapshot-broken/missing-plotly fails on its missing plotly.min.js only", () => {
    assert.throws(
      () => read("e2e/fixtures/snapshot-broken/missing-plotly", { SNAPSHOT_ALLOW_FIXTURE: "1" }),
      snapshotError(
        "Snapshot: 1 problem in e2e/fixtures/snapshot-broken/missing-plotly:\n  - charts/plotly.min.js is required when an analysis lists an HTML chart",
      ),
    );
  });

  it("snapshot-broken/chart-mismatch fails on its missing chart only", () => {
    assert.throws(
      () => read("e2e/fixtures/snapshot-broken/chart-mismatch", { SNAPSHOT_ALLOW_FIXTURE: "1" }),
      snapshotError(`Snapshot: 1 problem in e2e/fixtures/snapshot-broken/chart-mismatch:\n  - chart "${HTML}" listed by ${ID} has no file in charts/`),
    );
  });

  it("snapshot-broken/fixture-guard fails on the guard alone: it is otherwise valid", () => {
    assert.throws(() => read("e2e/fixtures/snapshot-broken/fixture-guard"), snapshotError(/is a test fixture/));
    assert.deepEqual(read("e2e/fixtures/snapshot-broken/fixture-guard", { SNAPSHOT_ALLOW_FIXTURE: "1" }).ids, [ID]);
  });
});

describe("scripts/copy-snapshot-charts.mjs (the second half of build:public)", () => {
  const FIXTURE_ENV = { SNAPSHOT_DIR: "e2e/fixtures/snapshot", SNAPSHOT_ALLOW_FIXTURE: "1" };

  // A temporary frontend/ holding the script, the rules module, a copy of the
  // committed fixture and a link to node_modules/ (for next's @next/env);
  // `out` creates an (empty) export folder. The cleanup removes the link, not
  // what it points to.
  function copyLayout({ out = true } = {}) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "copy-charts-"));
    tempRoots.push(root);
    for (const rel of ["scripts/copy-snapshot-charts.mjs", "lib/snapshot-rules.mjs"]) {
      fs.mkdirSync(path.join(root, path.dirname(rel)), { recursive: true });
      fs.copyFileSync(path.join(FRONTEND, rel), path.join(root, rel));
    }
    fs.cpSync(path.join(FRONTEND, "e2e/fixtures/snapshot"), path.join(root, "e2e/fixtures/snapshot"), { recursive: true });
    fs.symlinkSync(path.join(FRONTEND, "node_modules"), path.join(root, "node_modules"), "dir");
    if (out) fs.mkdirSync(path.join(root, "out"));
    return root;
  }

  function runCopy(root, env) {
    return spawnSync(process.execPath, [path.join(root, "scripts/copy-snapshot-charts.mjs")], {
      cwd: root,
      env: { PATH: process.env.PATH, ...env },
      encoding: "utf8",
    });
  }

  // The first half of build:public, in a temporary frontend/: `next build`
  // loads the .env files through Next's config loader for the build phase
  // (next/dist/server/config.js:683; next/dist/build/index.js:371 makes the
  // same call first), then lib/snapshot.ts calls readSnapshot(process.cwd(),
  // process.env). Prints the snapshot dir it read, or its error.
  const LOADER_HALF = `
    import { createRequire } from "node:module";
    import { readSnapshot } from "./lib/snapshot-rules.mjs";
    const require = createRequire(import.meta.url);
    const { PHASE_PRODUCTION_BUILD } = require("next/constants");
    await require("next/dist/server/config").default(PHASE_PRODUCTION_BUILD, process.cwd());
    let result;
    try {
      result = { label: readSnapshot(process.cwd(), process.env).label };
    } catch (error) {
      result = { error: error.message };
    }
    console.log(JSON.stringify(result));`;

  function loaderHalf(root, env) {
    const run = spawnSync(process.execPath, ["--input-type=module", "-e", LOADER_HALF], {
      cwd: root,
      env: { PATH: process.env.PATH, ...env },
      encoding: "utf8",
    });
    assert.equal(run.status, 0, run.stderr);
    return JSON.parse(run.stdout.trim().split("\n").pop());
  }

  // The second half: the snapshot dir the copy step read, or its error.
  function copyHalf(root, env) {
    const run = runCopy(root, env);
    if (run.status !== 0) return { error: run.stderr.trim() };
    return { label: /^copied \d+ chart file\(s\) from (.+)\/charts\/ into/.exec(run.stdout)?.[1] };
  }

  // A temporary frontend/ with three copies of the fixture under snapshots/
  // and the given .env files.
  function envLayout(envFiles) {
    const root = copyLayout();
    for (const name of ["a", "b", "c"]) {
      fs.cpSync(path.join(FRONTEND, "e2e/fixtures/snapshot"), path.join(root, "snapshots", name), { recursive: true });
    }
    for (const [file, text] of Object.entries(envFiles)) fs.writeFileSync(path.join(root, file), text);
    return root;
  }

  it("sees the same SNAPSHOT_DIR and SNAPSHOT_ALLOW_FIXTURE as next build: the same .env files, production mode, process values first", () => {
    // Files only: .env.local beats .env, .env.production beats .env, and
    // .env.development is not loaded.
    const files = envLayout({
      ".env": "SNAPSHOT_DIR=snapshots/a\nSNAPSHOT_ALLOW_FIXTURE=0\n",
      ".env.local": "SNAPSHOT_DIR=snapshots/b\n",
      ".env.production": "SNAPSHOT_ALLOW_FIXTURE=1\n",
      ".env.development": "SNAPSHOT_DIR=snapshots/c\n",
    });
    const loader = loaderHalf(files, {});
    assert.deepEqual(loader, { label: "snapshots/b" });
    assert.deepEqual(copyHalf(files, {}), loader);

    // A value set in the process beats every file, and a fixture permission
    // only in .env.development does not count: both halves refuse.
    const processFirst = envLayout({
      ".env.local": "SNAPSHOT_DIR=snapshots/b\n",
      ".env.development": "SNAPSHOT_ALLOW_FIXTURE=1\n",
    });
    const refused = loaderHalf(processFirst, { SNAPSHOT_DIR: "snapshots/a" });
    assert.match(refused.error, /^Snapshot: snapshots\/a\/manifest\.json is a test fixture/);
    assert.deepEqual(copyHalf(processFirst, { SNAPSHOT_DIR: "snapshots/a" }), refused);
  });

  it("copies exactly the listed chart files and plotly.min.js into out/demo/charts/, byte for byte", () => {
    const root = copyLayout();
    const run = runCopy(root, FIXTURE_ENV);
    assert.equal(run.status, 0, run.stderr);
    assert.match(run.stdout, /^copied 3 chart file\(s\) from e2e\/fixtures\/snapshot\/charts\/ into out\/demo\/charts\//);
    const target = path.join(root, "out/demo/charts");
    assert.deepEqual(fs.readdirSync(target).sort(), [HTML, PNG, "plotly.min.js"].sort());
    for (const name of [PNG, HTML, "plotly.min.js"]) {
      assert.ok(fs.readFileSync(path.join(target, name)).equals(fs.readFileSync(path.join(FRONTEND, "e2e/fixtures/snapshot/charts", name))), name);
    }
  });

  it("copies plotly.min.js when an HTML chart needs it", () => {
    const root = copyLayout();
    fs.writeFileSync(path.join(root, "e2e/fixtures/snapshot/charts/plotly.min.js"), `${PLOTLY_HEADER}!function(){}`);
    const run = runCopy(root, FIXTURE_ENV);
    assert.equal(run.status, 0, run.stderr);
    assert.deepEqual(fs.readdirSync(path.join(root, "out/demo/charts")).sort(), [HTML, PNG, "plotly.min.js"].sort());
  });

  it("refuses a fixture without SNAPSHOT_ALLOW_FIXTURE=1, as the loader does", () => {
    const root = copyLayout();
    const run = runCopy(root, { SNAPSHOT_DIR: "e2e/fixtures/snapshot" });
    assert.notEqual(run.status, 0);
    assert.match(run.stderr, /Snapshot: e2e\/fixtures\/snapshot\/manifest\.json is a test fixture/);
    assert.equal(fs.existsSync(path.join(root, "out/demo")), false);
  });

  it("refuses SNAPSHOT_DIR when VERCEL is set, as the loader does", () => {
    const root = copyLayout();
    const run = runCopy(root, { ...FIXTURE_ENV, VERCEL: "1" });
    assert.notEqual(run.status, 0);
    assert.match(run.stderr, /Snapshot: SNAPSHOT_DIR must be unset when VERCEL is set/);
  });

  it("fails on an extra or a missing chart file (.DS_Store ignored)", () => {
    const extra = copyLayout();
    fs.writeFileSync(path.join(extra, "e2e/fixtures/snapshot/charts/.DS_Store"), "x");
    fs.writeFileSync(path.join(extra, "e2e/fixtures/snapshot/charts/extra.png"), "x");
    const run = runCopy(extra, FIXTURE_ENV);
    assert.notEqual(run.status, 0);
    assert.match(run.stderr, /unaccounted entry "charts\/extra\.png"/);
    assert.doesNotMatch(run.stderr, /DS_Store/);
    assert.equal(fs.existsSync(path.join(extra, "out/demo")), false);

    const missing = copyLayout();
    fs.rmSync(path.join(missing, "e2e/fixtures/snapshot/charts", PNG));
    assert.match(runCopy(missing, FIXTURE_ENV).stderr, new RegExp(`chart "${PNG}" listed by ${ID} has no file in charts/`));
  });

  it("runs only after next build: no out/, no copy", () => {
    const root = copyLayout({ out: false });
    const run = runCopy(root, FIXTURE_ENV);
    assert.notEqual(run.status, 0);
    assert.match(run.stderr, /out\/ does not exist/);
  });

  it("never writes into an existing out/demo/", () => {
    const root = copyLayout();
    fs.mkdirSync(path.join(root, "out/demo"));
    const run = runCopy(root, FIXTURE_ENV);
    assert.notEqual(run.status, 0);
    assert.match(run.stderr, /out\/demo\/ already exists/);
  });
});
