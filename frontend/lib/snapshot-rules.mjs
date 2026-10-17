// @ts-check
// The rules of the public snapshot build (`npm run build:public`), which
// renders saved analyses from built-in JSON and must fail closed. Every rule
// is a pure function; readSnapshot reads a snapshot directory and applies
// them all. Shared as is by the build's loader (lib/snapshot.ts), the chart
// copy step (scripts/copy-snapshot-charts.mjs) and the unit tests
// (lib/snapshot-rules.test.mjs): plain .mjs with JSDoc types, so Node runs it
// with no TypeScript step and the TS loader still gets its types.
//
// Layout of a snapshot directory:
//   manifest.json          {"analyses":[{"id":"<lowercase canonical uuid>","note":"<the About-this-example text>"}]};
//                          a test fixture also carries "fixture": true. A note is one line of at
//                          most 600 code points, with no control or invisible format (Cf)
//                          character, UUID or scan hit.
//   analyses/<id>.json     one SnapshotAnalysis (lib/types.ts) per id: exactly
//                          the keys PUBLISHED defines, at every level
//   charts/<file>          exactly the files the analyses' chart_paths list,
//                          plus plotly.min.js, required beside an HTML chart
// The default is frontend/snapshot/. Never put snapshot files in public/:
// Next copies public/ into every build and serves it in dev.

import fs from "node:fs";
import path from "node:path";

/** @typedef {import("./types").SnapshotAnalysis} SnapshotAnalysis */
/** @typedef {Record<string, string | undefined>} Env */
/** @typedef {"file" | "dir" | "other"} EntryKind */
/** @typedef {{ name: string, kind: EntryKind }} Entry */
/** @typedef {{ name: string, id: string }} ListedChart */
/**
 * A node of the published key set: `true` (a leaf, published whole and
 * type-checked by the rules below), an object of keys, or a one-item array
 * whose item describes every element.
 * @typedef {true | PublishedObject | PublishedArray} PublishedNode
 * @typedef {{ readonly [key: string]: PublishedNode }} PublishedObject
 * @typedef {readonly [PublishedObject]} PublishedArray
 */
/** @typedef {{ path: string, value: unknown }} UnpublishedEntry */

export class SnapshotError extends Error {
  /** @param {string} message */
  constructor(message) {
    super(`Snapshot: ${message}`);
    this.name = "SnapshotError";
  }
}

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const UUID_SHAPED = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
// A plain file name as viz_tools.py writes it (`_safe_name` keeps Unicode word
// characters): no path separator, .png or .html, and no other dot (x.png.html
// would become x.png once chartUrl drops .html). (A RegExp call, not a
// literal: tsconfig sets no target, and TS checks a literal's "u" flag against
// ES5.)
const CHART_NAME = new RegExp(String.raw`^[\p{L}\p{N}_][\p{L}\p{N}_-]*\.(?:png|html)$`, "u");
const PLOTLY = "plotly.min.js";
const PLOTLY_HEADER = /^\/\*+[\s*]*plotly\.js v\d/;
// A manifest note's length limit, in code points.
export const NOTE_MAX = 600;
// Control characters (line breaks and tabs included) and the two Unicode line
// separators: a note is one line. (A RegExp call, as CHART_NAME is; not
// global, so .test keeps no state.)
const CONTROL = new RegExp("[\\p{Cc}\\u2028\\u2029]", "u");
// Invisible format characters (Unicode category Cf): a byte order mark, the
// bidi controls, zero-width characters (owner ruling, 2026-10-17).
const FORMAT = new RegExp("\\p{Cf}", "u");
// macOS Finder metadata; gitignored, so it can never reach the repo.
const IGNORED = new Set([".DS_Store"]);

const FORBIDDEN_KEYS = new Set(
  [
    "session_id",
    "stored_filename",
    "file_size",
    "pause_data",
    "user_pause_response",
    "error_message",
    "updated_at",
    "original_filename",
  ].map(normalizeKey),
);

/**
 * The published key set (owner ruling D3, M2b.3a): every key the public page
 * renders, at every level, in render order, plus cleaning_report.summary's
 * four counts for the results header (M2b.3b; owner ruling D1: no derived
 * "removed" counts). One definition for both the export's projection
 * (projectPublished, scripts/export-snapshot.mjs) and the build's validation
 * (findUnpublishedKeys, in checkAnalysis), so the two cannot drift. Changing
 * it is a publication decision.
 * @type {PublishedObject}
 */
export const PUBLISHED = deepFreeze(
  /** @type {PublishedObject} */ ({
    id: true,
    filename: true,
    row_count: true,
    column_count: true,
    data_quality_score: true,
    cleaning_report: { summary: { rows_before: true, rows_after: true, columns_before: true, columns_after: true } },
    cleaning_decisions: [{ column_name: true, issue: true, action: true, reason: true }],
    analysis_report: { correlation_matrix: { matrix: true, strong_pairs: [{ col1: true, col2: true }] } },
    insight_report: {
      analyst_layer: { narrative: true, chart_references: true },
      open_questions: [{ question: true, why_unanswerable: true, what_data_would_answer: true }],
      technical_layer: {
        statistical_methodology: true,
        code_blocks: true,
        limitations: true,
        sophistication_suggestions: true,
        self_evaluation_notes: true,
        lead_override_note: true,
      },
      user_question_addressed: true,
    },
    executive_summary: { bullets: [{ finding: true, context: true, recommended_action: true }] },
    chart_paths: true,
  }),
);

// Folders SNAPSHOT_DIR may not point into: Next copies public/ into every
// export and serves it in dev, the export deletes out/ first, .next/ is the
// build's own folder and node_modules/ belongs to npm. Compared in lower case:
// macOS file systems ignore case by default.
const RESERVED_DIRS = new Set(["public", "out", ".next", "node_modules"]);

// ---------------------------------------------------------------------------
// Snapshot directory, VERCEL and fixture guards
// ---------------------------------------------------------------------------

/**
 * @param {string | undefined} value
 * @returns {value is string}
 */
function isSet(value) {
  return value !== undefined && value !== "";
}

/**
 * The snapshot directory: frontend/snapshot/, or SNAPSHOT_DIR (a build
 * variable, never public) resolved relative to frontend/ and refused outside
 * it or inside its public/, out/, .next/ or node_modules/. [A2] When VERCEL
 * is set, SNAPSHOT_DIR must be unset. Vercel sets VERCEL only when system
 * environment variables are exposed to the project, so this layer can be
 * inert; the fixture guard does not depend on it.
 * @param {string} frontendDir absolute path of frontend/
 * @param {Env} env
 * @returns {string}
 */
export function resolveSnapshotDir(frontendDir, env) {
  const custom = env.SNAPSHOT_DIR;
  if (!isSet(custom)) return path.join(frontendDir, "snapshot");
  if (isSet(env.VERCEL)) throw new SnapshotError("SNAPSHOT_DIR must be unset when VERCEL is set");
  const dir = path.resolve(frontendDir, custom);
  const rel = path.relative(frontendDir, dir);
  if (rel === "" || rel === ".." || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
    throw new SnapshotError(`SNAPSHOT_DIR must point to a directory inside frontend/; got ${JSON.stringify(custom)}`);
  }
  if (RESERVED_DIRS.has(rel.split(path.sep)[0].toLowerCase())) {
    throw new SnapshotError(`SNAPSHOT_DIR must not point into public/, out/, .next/ or node_modules/; got ${JSON.stringify(custom)}`);
  }
  return dir;
}

/**
 * A test fixture ("fixture": true) builds only with SNAPSHOT_ALLOW_FIXTURE=1,
 * which only playwright.public.config.ts sets.
 * @param {boolean} isFixture
 * @param {Env} env
 * @param {string} manifestLabel
 */
export function checkFixtureGuard(isFixture, env, manifestLabel) {
  if (isFixture && env.SNAPSHOT_ALLOW_FIXTURE !== "1") {
    throw new SnapshotError(
      `${manifestLabel} is a test fixture ("fixture": true); it builds only with SNAPSHOT_ALLOW_FIXTURE=1, which only the public e2e sets`,
    );
  }
}

// ---------------------------------------------------------------------------
// Manifest
// ---------------------------------------------------------------------------

/**
 * @param {unknown} value the parsed manifest.json
 * @returns {{ ids: string[], notes: Record<string, string>, fixture: boolean, problems: string[] }}
 *   notes: each valid entry's note, by id
 */
export function checkManifest(value) {
  /** @type {string[]} */
  const ids = [];
  // No prototype, so no key is inherited: a lookup of an id that is not in the
  // manifest (such as "constructor" or "__proto__") finds nothing.
  /** @type {Record<string, string>} */
  const notes = Object.create(null);
  if (!isPlainObject(value)) return { ids, notes, fixture: false, problems: ["must be a JSON object"] };
  const problems = unknownKeys(value, ["analyses", "fixture"], "");
  if ("fixture" in value && value.fixture !== true) problems.push('"fixture" must be true when present');
  const analyses = value.analyses;
  if (!("analyses" in value)) problems.push('missing key "analyses"');
  else if (!Array.isArray(analyses)) problems.push('"analyses" must be an array');
  else if (analyses.length === 0) problems.push('"analyses" is empty');
  else {
    analyses.forEach((entry, i) => {
      const where = `analyses[${i}]`;
      if (!isPlainObject(entry)) {
        problems.push(`${where} must be an object`);
        return;
      }
      problems.push(...unknownKeys(entry, ["id", "note"], where));
      /** @type {string | null} */
      let accepted = null;
      if (!("id" in entry)) {
        problems.push(`missing key "${where}.id"`);
      } else {
        const id = entry.id;
        if (typeof id !== "string" || !CANONICAL_UUID.test(id)) {
          problems.push(`${where}.id ${JSON.stringify(id)} is not a lowercase canonical UUID`);
        } else if (ids.includes(id)) {
          problems.push(`${where}.id duplicates ${id}`);
        } else {
          ids.push(id);
          accepted = id;
        }
      }
      if (!("note" in entry)) {
        problems.push(`missing key "${where}.note"`);
        return;
      }
      const noteProblems = checkNote(entry.note, `${where}.note`);
      problems.push(...noteProblems);
      if (accepted !== null && noteProblems.length === 0) notes[accepted] = /** @type {string} */ (entry.note);
    });
  }
  return { ids, notes, fixture: value.fixture === true, problems };
}

/**
 * Problems with an "About this example" note, the owner's text the analysis
 * page shows above the results: one line of at most NOTE_MAX code points, with
 * no surrounding whitespace, no control character, no invisible format
 * character (Unicode Cf), no UUID and no hit of the exact scan.
 * @param {unknown} value
 * @param {string} where what the messages call the note
 * @returns {string[]}
 */
export function checkNote(value, where) {
  if (typeof value !== "string") return [`${where} must be a string`];
  if (value.trim() === "") return [`${where} must not be empty`];
  /** @type {string[]} */
  const problems = [];
  if (value !== value.trim()) problems.push(`${where} must not start or end with whitespace`);
  // Code points, not UTF-16 units (spreading a string fails tsc's ES5 check).
  const length = Array.from(value).length;
  if (length > NOTE_MAX) problems.push(`${where} has ${length} characters; at most ${NOTE_MAX} (code points)`);
  if (CONTROL.test(value)) problems.push(`${where} must be one line, with no control characters`);
  if (FORMAT.test(value)) problems.push(`${where} must not contain invisible format characters (Unicode category Cf)`);
  if (findForeignUuids(value, null).length > 0) problems.push(`${where} contains a UUID`);
  for (const hit of scanText(value)) problems.push(`${where}: ${hit.pattern} ${JSON.stringify(hit.match)}`);
  return problems;
}

// ---------------------------------------------------------------------------
// The published key set: projection and unknown keys
// ---------------------------------------------------------------------------

/**
 * The published part of an analysis: only the keys PUBLISHED defines, at
 * every level, in its order; leaves are kept whole. A value whose shape
 * differs from the definition (not an object, not an array) is kept as it
 * is, for checkAnalysis to report. The export writes exactly this.
 * @param {unknown} value
 * @returns {unknown}
 */
export function projectPublished(value) {
  return project(value, PUBLISHED);
}

/**
 * Every key of value that PUBLISHED does not define, with its path (the
 * rules' format, e.g. `insight_report.open_questions[0].priority`) and value:
 * what projectPublished leaves out. Keys inside a leaf are not listed.
 * @param {unknown} value
 * @returns {UnpublishedEntry[]}
 */
export function unpublishedEntries(value) {
  /** @type {UnpublishedEntry[]} */
  const entries = [];
  collectUnpublished(value, PUBLISHED, "", entries);
  return entries;
}

/**
 * An unknown-key problem for every key PUBLISHED does not define, at every
 * level it defines.
 * @param {unknown} value
 * @returns {string[]}
 */
export function findUnpublishedKeys(value) {
  return unpublishedEntries(value).map((entry) => `unknown key ${JSON.stringify(entry.path)}`);
}

/**
 * @param {unknown} value
 * @param {PublishedNode} node
 * @returns {unknown}
 */
function project(value, node) {
  if (node === true) return value;
  if (isArrayNode(node)) {
    const item = node[0];
    return Array.isArray(value) ? value.map((entry) => project(entry, item)) : value;
  }
  if (!isPlainObject(value)) return value;
  /** @type {Record<string, unknown>} */
  const out = {};
  for (const key of Object.keys(node)) {
    if (hasOwn(value, key)) out[key] = project(value[key], node[key]);
  }
  return out;
}

/**
 * @param {unknown} value
 * @param {PublishedNode} node
 * @param {string} where
 * @param {UnpublishedEntry[]} entries
 */
function collectUnpublished(value, node, where, entries) {
  if (node === true) return;
  if (isArrayNode(node)) {
    const item = node[0];
    if (Array.isArray(value)) value.forEach((entry, i) => collectUnpublished(entry, item, `${where}[${i}]`, entries));
    return;
  }
  if (!isPlainObject(value)) return;
  for (const key of Object.keys(value)) {
    const at = where === "" ? key : `${where}.${key}`;
    if (hasOwn(node, key)) collectUnpublished(value[key], node[key], at, entries);
    else entries.push({ path: at, value: value[key] });
  }
}

/**
 * @param {PublishedNode} node
 * @returns {node is PublishedArray}
 */
function isArrayNode(node) {
  return Array.isArray(node);
}

/**
 * The keys an object node defines (none for a leaf or an array node).
 * @param {PublishedNode} node
 * @returns {string[]}
 */
function keysOf(node) {
  return node === true || isArrayNode(node) ? [] : Object.keys(node);
}

// ---------------------------------------------------------------------------
// The SnapshotAnalysis contract
// ---------------------------------------------------------------------------

/**
 * Problems with one analysis against SnapshotAnalysis (lib/types.ts): exactly
 * the keys PUBLISHED defines (the fields the results view reads, plus
 * cleaning_report.summary); an unknown key fails at every level it defines.
 * Inside, the fields the UI reads are type-checked; the summary's
 * before-counts must equal row_count and column_count. Forbidden keys and
 * foreign UUIDs are separate rules.
 * @param {unknown} value
 * @param {string} id the manifest id
 * @returns {string[]}
 */
export function checkAnalysis(value, id) {
  if (!isPlainObject(value)) return ["must be a JSON object"];
  const problems = [...findUnpublishedKeys(value), ...missingKeys(value, keysOf(PUBLISHED), "")];
  if ("id" in value && value.id !== id) problems.push(`id ${JSON.stringify(value.id)} differs from the manifest id ${id}`);
  if ("filename" in value && !(typeof value.filename === "string" && value.filename !== "")) {
    problems.push("filename must be a non-empty string");
  }
  for (const key of ["row_count", "column_count"]) {
    if (key in value && !isCount(value[key])) problems.push(`${key} must be a non-negative integer`);
  }
  const score = value.data_quality_score;
  if ("data_quality_score" in value && !(typeof score === "number" && score >= 0 && score <= 1)) {
    problems.push("data_quality_score must be a number from 0 to 1");
  }
  if ("cleaning_report" in value) problems.push(...checkCleaningReport(value.cleaning_report), ...checkSummaryCounts(value));
  if ("cleaning_decisions" in value) problems.push(...checkCleaningDecisions(value.cleaning_decisions));
  if ("analysis_report" in value) problems.push(...checkAnalysisReport(value.analysis_report));
  if ("insight_report" in value) problems.push(...checkInsightReport(value.insight_report));
  if ("executive_summary" in value) problems.push(...checkExecutiveSummary(value.executive_summary));
  if ("chart_paths" in value) problems.push(...checkChartPaths(value.chart_paths));
  return problems;
}

/** @param {unknown} report */
function checkCleaningReport(report) {
  if (!isPlainObject(report)) return ["cleaning_report must be an object"];
  const node = PUBLISHED.cleaning_report;
  const problems = missingKeys(report, keysOf(node), "cleaning_report");
  if (!("summary" in report)) return problems;
  const summary = report.summary;
  if (!isPlainObject(summary)) return [...problems, "cleaning_report.summary must be an object"];
  const summaryKeys = node === true || isArrayNode(node) ? [] : keysOf(node.summary);
  problems.push(...missingKeys(summary, summaryKeys, "cleaning_report.summary"));
  for (const key of summaryKeys) {
    if (key in summary && !isCount(summary[key])) problems.push(`cleaning_report.summary.${key} must be a non-negative integer`);
  }
  return problems;
}

/**
 * The summary's before-counts describe the upload, as row_count and
 * column_count do (owner ruling D1): both pairs must agree. A count that is
 * itself invalid is reported by its own check, not compared.
 * @param {Record<string, unknown>} analysis
 */
function checkSummaryCounts(analysis) {
  const report = analysis.cleaning_report;
  const summary = isPlainObject(report) ? report.summary : undefined;
  if (!isPlainObject(summary)) return [];
  /** @type {string[]} */
  const problems = [];
  for (const [before, count] of [["rows_before", "row_count"], ["columns_before", "column_count"]]) {
    const a = summary[before];
    const b = analysis[count];
    if (isCount(a) && isCount(b) && a !== b) problems.push(`cleaning_report.summary.${before} (${a}) must equal ${count} (${b})`);
  }
  return problems;
}

/** @param {unknown} decisions */
function checkCleaningDecisions(decisions) {
  if (!Array.isArray(decisions)) return ["cleaning_decisions must be an array"];
  /** @type {string[]} */
  const problems = [];
  decisions.forEach((decision, i) => {
    const where = `cleaning_decisions[${i}]`;
    if (!isPlainObject(decision)) {
      problems.push(`${where} must be an object`);
      return;
    }
    if (!isStringOrNull(decision.column_name)) problems.push(`${where}.column_name must be a string or null`);
    for (const key of ["issue", "action", "reason"]) {
      if (typeof decision[key] !== "string") problems.push(`${where}.${key} must be a string`);
    }
  });
  return problems;
}

/** @param {unknown} report */
function checkAnalysisReport(report) {
  if (!isPlainObject(report)) return ["analysis_report must be an object"];
  const problems = missingKeys(report, keysOf(PUBLISHED.analysis_report), "analysis_report");
  if (!("correlation_matrix" in report)) return problems;
  const where = "analysis_report.correlation_matrix";
  const cm = report.correlation_matrix;
  if (!isPlainObject(cm)) return [...problems, `${where} must be an object`];
  if (!("matrix" in cm)) problems.push(`missing key "${where}.matrix"`);
  else if (!isMatrix(cm.matrix)) problems.push(`${where}.matrix must map column names to objects of numbers or null`);
  if ("strong_pairs" in cm) {
    const pairs = cm.strong_pairs;
    if (!Array.isArray(pairs)) problems.push(`${where}.strong_pairs must be an array`);
    else {
      pairs.forEach((pair, i) => {
        if (!isPlainObject(pair)) {
          problems.push(`${where}.strong_pairs[${i}] must be an object`);
          return;
        }
        for (const key of ["col1", "col2"]) {
          if (typeof pair[key] !== "string") problems.push(`${where}.strong_pairs[${i}].${key} must be a string`);
        }
      });
    }
  }
  return problems;
}

/** @param {unknown} report */
function checkInsightReport(report) {
  if (!isPlainObject(report)) return ["insight_report must be an object"];
  const problems = missingKeys(report, keysOf(PUBLISHED.insight_report), "insight_report");
  if ("analyst_layer" in report) {
    const where = "insight_report.analyst_layer";
    const layer = report.analyst_layer;
    if (!isPlainObject(layer)) problems.push(`${where} must be an object`);
    else {
      optionalString(layer, "narrative", where, problems);
      optionalStringArray(layer, "chart_references", where, problems);
    }
  }
  if ("open_questions" in report) {
    const where = "insight_report.open_questions";
    const questions = report.open_questions;
    if (!Array.isArray(questions)) problems.push(`${where} must be an array`);
    else {
      questions.forEach((question, i) => {
        if (!isPlainObject(question)) {
          problems.push(`${where}[${i}] must be an object`);
          return;
        }
        for (const key of ["question", "why_unanswerable", "what_data_would_answer"]) {
          optionalString(question, key, `${where}[${i}]`, problems);
        }
      });
    }
  }
  if ("technical_layer" in report) {
    const where = "insight_report.technical_layer";
    const layer = report.technical_layer;
    if (!isPlainObject(layer)) problems.push(`${where} must be an object`);
    else {
      for (const key of ["statistical_methodology", "limitations", "sophistication_suggestions", "self_evaluation_notes"]) {
        optionalString(layer, key, where, problems);
      }
      optionalStringArray(layer, "code_blocks", where, problems);
      if ("lead_override_note" in layer && !isStringOrNull(layer.lead_override_note)) {
        problems.push(`${where}.lead_override_note must be a string or null`);
      }
    }
  }
  if ("user_question_addressed" in report && !isStringOrNull(report.user_question_addressed)) {
    problems.push("insight_report.user_question_addressed must be a string or null");
  }
  return problems;
}

/** @param {unknown} summary */
function checkExecutiveSummary(summary) {
  if (!isPlainObject(summary)) return ["executive_summary must be an object"];
  const problems = missingKeys(summary, keysOf(PUBLISHED.executive_summary), "executive_summary");
  if (!("bullets" in summary)) return problems;
  const bullets = summary.bullets;
  if (!Array.isArray(bullets)) return [...problems, "executive_summary.bullets must be an array"];
  bullets.forEach((bullet, i) => {
    const where = `executive_summary.bullets[${i}]`;
    if (!isPlainObject(bullet)) {
      problems.push(`${where} must be an object`);
      return;
    }
    for (const key of ["finding", "context", "recommended_action"]) optionalString(bullet, key, where, problems);
  });
  return problems;
}

/** @param {unknown} chartPaths */
function checkChartPaths(chartPaths) {
  if (!Array.isArray(chartPaths)) return ["chart_paths must be an array"];
  /** @type {string[]} */
  const problems = [];
  const seen = new Set();
  chartPaths.forEach((name, i) => {
    if (!isChartName(name)) {
      problems.push(`chart_paths[${i}] ${JSON.stringify(name)} is not a chart file name (a plain name ending in .png or .html, with no other dot)`);
    } else if (seen.has(name)) {
      problems.push(`chart_paths[${i}] duplicates ${JSON.stringify(name)}`);
    } else {
      seen.add(name);
    }
  });
  return problems;
}

// ---------------------------------------------------------------------------
// Forbidden keys and foreign UUIDs
// ---------------------------------------------------------------------------

/**
 * Lower-cased, non-alphanumerics dropped: sessionId, session-id and
 * SESSION_ID all become "sessionid".
 * @param {string} key
 * @returns {string}
 */
export function normalizeKey(key) {
  return key.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/**
 * Every key, at any depth, whose normalized name is forbidden (session_id,
 * stored_filename, file_size, pause_data, user_pause_response,
 * error_message, updated_at, original_filename). Keys only, never values.
 * @param {unknown} value
 * @param {string} [where]
 * @returns {string[]}
 */
export function findForbiddenKeys(value, where = "") {
  if (Array.isArray(value)) return value.flatMap((item, i) => findForbiddenKeys(item, `${where}[${i}]`));
  if (!isPlainObject(value)) return [];
  return Object.entries(value).flatMap(([key, child]) => {
    const at = where === "" ? key : `${where}.${key}`;
    const own = FORBIDDEN_KEYS.has(normalizeKey(key)) ? [`forbidden key ${JSON.stringify(key)} at ${at}`] : [];
    return [...own, ...findForbiddenKeys(child, at)];
  });
}

/**
 * Every UUID-shaped string (any case), lower-cased and listed once, other
 * than ownId. With no ownId, every UUID is foreign.
 * @param {string} text
 * @param {string | null} ownId
 * @returns {string[]}
 */
export function findForeignUuids(text, ownId) {
  const uuids = Array.from(text.matchAll(UUID_SHAPED), (match) => match[0].toLowerCase());
  return Array.from(new Set(uuids.filter((uuid) => uuid !== ownId)));
}

/**
 * plotly.min.js must begin with plotly's header comment
 * ("/**\n* plotly.js v2.30.0 …").
 * @param {string} text
 * @returns {boolean}
 */
export function isPlotlyBundle(text) {
  return PLOTLY_HEADER.test(text);
}

// ---------------------------------------------------------------------------
// The exact scan
// ---------------------------------------------------------------------------

// The exact scan, applied to every key and string of the export's published
// projection and to each manifest note. Each pattern is tested both ways in
// lib/snapshot-rules.test.mjs. The regexes are global and shared, so never
// call .test() or .exec() on them (lastIndex state). Use scanText, which uses
// matchAll on a fresh copy of each.
export const SCAN_PATTERNS = Object.freeze({
  "absolute path": /(?<![\w.:/~-])\/(?:[\w.-]+\/)+[\w.-]*/g,
  "home path": /(?<![\w.-])~\/[\w.-]/g,
  "Windows path": /\b[A-Za-z]:\\[\w.-]/g,
  URL: /\b[a-z][a-z0-9+.-]*:\/\//gi,
  "mailto, javascript or file URI": /\b(?:mailto:|javascript:|file:\/)/gi,
  "data URI": /\bdata:[a-z]+\/[a-z0-9.+-]+[;,]/gi,
  email: /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g,
  "key-like string": /(?:\b(?:sk-ant-|sk-proj-|sb_secret_|sb_publishable_|lsv2_|ghp_|gho_|ghs_|github_pat_)|\bxox[abprs]-|\bAKIA[0-9A-Z]{16}\b|\beyJ[\w-]{10,}\.[\w-]{10,}|-----BEGIN [A-Z ]+-----)/g,
  "service host": /\b[a-z0-9-]+\.supabase\.(?:co|com|in)\b|\bproject_ref\b|\bsmith\.langchain\.com\b|\bapi\.anthropic\.com\b/gi,
  "local host": /\blocalhost\b|\b127\.0\.0\.1\b|\b0\.0\.0\.0\b|\[::1\]/gi,
  "IPv4 address": /\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b/g,
});

/**
 * Every hit of the exact scan patterns in a text.
 * @param {string} text
 * @returns {{ pattern: string, match: string, index: number }[]}
 */
export function scanText(text) {
  return Object.entries(SCAN_PATTERNS).flatMap(([pattern, re]) =>
    Array.from(text.matchAll(new RegExp(re.source, re.flags)), (m) => ({ pattern, match: m[0], index: m.index ?? 0 })),
  );
}

// ---------------------------------------------------------------------------
// File accounting
// ---------------------------------------------------------------------------

/**
 * Problems with a snapshot directory's files against what the manifest
 * accounts for. `.DS_Store` is ignored by name everywhere.
 * @param {{ top: Entry[], analyses: Entry[] | null, charts: Entry[] | null }} listing
 *   each directory's entries; null when it is missing or not a directory
 * @param {{ ids: string[], charts: ListedChart[] | null }} expected
 *   charts: every chart_paths entry with its analysis id; null when an
 *   analysis could not be read, so its charts are unknown (not checked)
 * @returns {string[]}
 */
export function checkFileAccounting(listing, expected) {
  /** @type {string[]} */
  const problems = [];
  for (const entry of visible(listing.top)) {
    if (entry.name === "manifest.json") {
      if (entry.kind !== "file") problems.push("manifest.json must be a regular file");
    } else if (entry.name === "analyses" || entry.name === "charts") {
      if (entry.kind !== "dir") problems.push(`${entry.name} must be a directory`);
    } else {
      problems.push(`unaccounted entry ${JSON.stringify(entry.name)} in the snapshot dir`);
    }
  }

  const analyses = visible(listing.analyses);
  for (const id of expected.ids) {
    const entry = analyses.find((e) => e.name === `${id}.json`);
    if (!entry) problems.push(`analysis ${id} has no file analyses/${id}.json`);
    else if (entry.kind !== "file") problems.push(`analyses/${id}.json must be a regular file`);
  }
  const analysisFiles = new Set(expected.ids.map((id) => `${id}.json`));
  for (const entry of analyses) {
    if (!analysisFiles.has(entry.name)) problems.push(`unaccounted entry ${JSON.stringify(`analyses/${entry.name}`)}`);
  }

  if (expected.charts === null) return problems;
  const charts = visible(listing.charts);
  const listed = new Set();
  for (const { name, id } of expected.charts) {
    if (listed.has(name)) continue;
    listed.add(name);
    const entry = charts.find((e) => e.name === name);
    if (!entry) problems.push(`chart ${JSON.stringify(name)} listed by ${id} has no file in charts/`);
    else if (entry.kind !== "file") problems.push(`charts/${name} must be a regular file`);
  }
  const htmlChart = Array.from(listed).some((name) => name.endsWith(".html"));
  for (const entry of charts) {
    if (listed.has(entry.name)) continue;
    if (entry.name !== PLOTLY) problems.push(`unaccounted entry ${JSON.stringify(`charts/${entry.name}`)}`);
    else if (!htmlChart) problems.push(`charts/${PLOTLY} is allowed only when an analysis lists an HTML chart`);
    else if (entry.kind !== "file") problems.push(`charts/${PLOTLY} must be a regular file`);
  }
  // Every HTML chart loads the shared bundle from its own folder (M2b.2):
  // without it the chart renders blank (M2b.2 Code Review #2).
  if (htmlChart && !charts.some((entry) => entry.name === PLOTLY)) {
    problems.push(`charts/${PLOTLY} is required when an analysis lists an HTML chart`);
  }
  return problems;
}

// ---------------------------------------------------------------------------
// Reading a snapshot directory (the only I/O here; it applies every rule)
// ---------------------------------------------------------------------------

/**
 * @typedef {object} Snapshot
 * @property {string} dir absolute path of the snapshot directory
 * @property {string} label the directory relative to frontend/, for messages
 * @property {string[]} ids the manifest ids, in order
 * @property {Record<string, string>} notes the manifest notes, by id
 * @property {boolean} fixture the manifest is a test fixture
 * @property {SnapshotAnalysis[]} analyses validated, in manifest order
 * @property {string[]} charts every listed chart file once, in manifest order
 * @property {boolean} plotly charts/plotly.min.js is present (and allowed)
 */

/**
 * Reads the snapshot directory and applies every rule. Throws a SnapshotError
 * naming each problem found.
 * @param {string} frontendDir absolute path of frontend/
 * @param {Env} env
 * @returns {Snapshot}
 */
export function readSnapshot(frontendDir, env) {
  const dir = resolveSnapshotDir(frontendDir, env);
  const label = path.relative(frontendDir, dir).split(path.sep).join("/");
  const dirKind = kindOf(dir);
  if (dirKind === null) throw new SnapshotError(`no manifest at ${label}/manifest.json`);
  if (dirKind !== "dir") throw new SnapshotError(`${label} must be a directory (not a symlink)`);

  const manifestPath = path.join(dir, "manifest.json");
  const manifestKind = kindOf(manifestPath);
  if (manifestKind === null) throw new SnapshotError(`no manifest at ${label}/manifest.json`);
  if (manifestKind !== "file") throw new SnapshotError(`${label}/manifest.json must be a regular file`);
  const manifestJson = parseJson(fs.readFileSync(manifestPath, "utf8"));
  if (!manifestJson.ok) throw new SnapshotError(`${label}/manifest.json is not valid JSON`);
  const manifest = checkManifest(manifestJson.value);
  if (manifest.problems.length > 0) throw new SnapshotError(listProblems(`${label}/manifest.json`, manifest.problems));
  checkFixtureGuard(manifest.fixture, env, `${label}/manifest.json`);

  /** @type {string[]} */
  const problems = [];
  /** @type {SnapshotAnalysis[]} */
  const analyses = [];
  /** @type {ListedChart[] | null} */
  let listedCharts = [];
  for (const id of manifest.ids) {
    const rel = `analyses/${id}.json`;
    const file = path.join(dir, "analyses", `${id}.json`);
    if (kindOf(file) !== "file") {
      listedCharts = null; // its charts are unknown; the accounting reports the file
      continue;
    }
    const text = fs.readFileSync(file, "utf8");
    const json = parseJson(text);
    if (!json.ok) {
      problems.push(`${rel} is not valid JSON`);
      listedCharts = null;
      continue;
    }
    problems.push(...checkAnalysis(json.value, id).map((p) => `${rel}: ${p}`));
    problems.push(...findForbiddenKeys(json.value).map((p) => `${rel}: ${p}`));
    problems.push(...findForeignUuids(text, id).map((uuid) => `${rel} contains a UUID other than its own id: ${uuid}`));
    const chartPaths = isPlainObject(json.value) ? json.value.chart_paths : undefined;
    if (!Array.isArray(chartPaths)) listedCharts = null;
    else if (listedCharts !== null) {
      for (const name of Array.from(new Set(chartPaths.filter(isChartName)))) listedCharts.push({ name, id });
    }
    analyses.push(/** @type {SnapshotAnalysis} */ (json.value));
  }

  const listing = {
    top: listEntries(dir) ?? [],
    analyses: listEntries(path.join(dir, "analyses")),
    charts: listEntries(path.join(dir, "charts")),
  };
  problems.push(...checkFileAccounting(listing, { ids: manifest.ids, charts: listedCharts }));

  const chartKinds = new Map((listing.charts ?? []).map((e) => [e.name, e.kind]));
  for (const { name, id } of listedCharts ?? []) {
    if (chartKinds.get(name) !== "file") continue;
    const text = fs.readFileSync(path.join(dir, "charts", name), "latin1");
    problems.push(
      ...findForeignUuids(text, id).map((uuid) => `charts/${name} contains a UUID other than its analysis id ${id}: ${uuid}`),
    );
  }
  const htmlChart = (listedCharts ?? []).some((c) => c.name.endsWith(".html"));
  const plotly = htmlChart && chartKinds.get(PLOTLY) === "file";
  if (plotly) {
    const text = fs.readFileSync(path.join(dir, "charts", PLOTLY), "latin1");
    if (!isPlotlyBundle(text)) problems.push(`charts/${PLOTLY} does not begin with plotly's header comment ("plotly.js v")`);
    problems.push(...findForeignUuids(text, null).map((uuid) => `charts/${PLOTLY} contains a UUID: ${uuid}`));
  }

  if (problems.length > 0) throw new SnapshotError(listProblems(label, problems));
  return {
    dir,
    label,
    ids: manifest.ids,
    notes: manifest.notes,
    fixture: manifest.fixture,
    analyses,
    charts: Array.from(new Set((listedCharts ?? []).map((c) => c.name))),
    plotly,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** @param {unknown} value */
function isCount(value) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/** @param {unknown} value */
function isStringOrNull(value) {
  return typeof value === "string" || value === null;
}

/**
 * @param {unknown} value
 * @returns {value is string}
 */
function isChartName(value) {
  return typeof value === "string" && CHART_NAME.test(value);
}

/** @param {unknown} value */
function isMatrix(value) {
  return (
    isPlainObject(value) &&
    Object.values(value).every(
      (row) => isPlainObject(row) && Object.values(row).every((r) => r === null || (typeof r === "number" && Number.isFinite(r))),
    )
  );
}

/**
 * @param {Record<string, unknown>} object
 * @param {string} key
 * @param {string} where
 * @param {string[]} problems
 */
function optionalString(object, key, where, problems) {
  if (key in object && typeof object[key] !== "string") problems.push(`${where}.${key} must be a string`);
}

/**
 * @param {Record<string, unknown>} object
 * @param {string} key
 * @param {string} where
 * @param {string[]} problems
 */
function optionalStringArray(object, key, where, problems) {
  const value = object[key];
  if (key in object && !(Array.isArray(value) && value.every((item) => typeof item === "string"))) {
    problems.push(`${where}.${key} must be an array of strings`);
  }
}

/**
 * @param {Record<string, unknown>} object
 * @param {string[]} allowed
 * @param {string} where
 * @returns {string[]}
 */
function unknownKeys(object, allowed, where) {
  return Object.keys(object)
    .filter((key) => !allowed.includes(key))
    .map((key) => `unknown key ${JSON.stringify(where === "" ? key : `${where}.${key}`)}`);
}

/**
 * Required keys that are missing. (Unknown keys are reported once, at every
 * level, by findUnpublishedKeys.)
 * @param {Record<string, unknown>} object
 * @param {string[]} keys
 * @param {string} where
 * @returns {string[]}
 */
function missingKeys(object, keys, where) {
  return keys
    .filter((key) => !(key in object))
    .map((key) => `missing key ${JSON.stringify(where === "" ? key : `${where}.${key}`)}`);
}

/**
 * An own key, never an inherited one (a JSON key named "constructor" or
 * "__proto__" is data, not the prototype's).
 * @param {object} object
 * @param {string} key
 * @returns {boolean}
 */
function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key);
}

/**
 * Freezes a value and everything inside it.
 * @template T
 * @param {T} value
 * @returns {T}
 */
function deepFreeze(value) {
  if (typeof value === "object" && value !== null) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/**
 * @param {Entry[] | null} entries
 * @returns {Entry[]}
 */
function visible(entries) {
  return (entries ?? []).filter((entry) => !IGNORED.has(entry.name));
}

/**
 * The kind of a path, never following a symlink; null when it is missing.
 * @param {string} target
 * @returns {EntryKind | null}
 */
function kindOf(target) {
  let stat;
  try {
    stat = fs.lstatSync(target);
  } catch {
    return null;
  }
  if (stat.isFile()) return "file";
  if (stat.isDirectory()) return "dir";
  return "other";
}

/**
 * A directory's entries, sorted by name; null when it is missing or not a
 * directory.
 * @param {string} dir
 * @returns {Entry[] | null}
 */
function listEntries(dir) {
  if (kindOf(dir) !== "dir") return null;
  return fs
    .readdirSync(dir)
    .sort()
    .map((name) => ({ name, kind: kindOf(path.join(dir, name)) ?? "other" }));
}

/**
 * @param {string} text
 * @returns {{ ok: true, value: unknown } | { ok: false }}
 */
function parseJson(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}

/**
 * @param {string} where
 * @param {string[]} problems
 */
function listProblems(where, problems) {
  const count = `${problems.length} problem${problems.length === 1 ? "" : "s"}`;
  return `${count} in ${where}:\n${problems.map((p) => `  - ${p}`).join("\n")}`;
}
