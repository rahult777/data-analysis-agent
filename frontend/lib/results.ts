// Client-safe helpers for the results view (components/AnalysisResults.tsx and
// components/InsightReport.tsx), in both modes. No imports and no Node API:
// `node --test` imports this file directly (lib/results.test.mjs). Browser
// code, so no regex lookbehind and no Unicode property escapes (Next 14's
// default targets include Safari 12 and Firefox 67), and nothing tsc's ES5
// check rejects.

// Counts in en-US whatever the visitor's locale, so the prerendered page and
// the browser draw the same digits (toLocaleString() broke hydration under
// fa-IR and ar-SA; errors.md 2026-10-14).
const countFormat = new Intl.NumberFormat("en-US");

export function formatCount(n: number): string {
  return countFormat.format(n);
}

// What the results header counts: the cleaned data, when the cleaning
// summary is valid and its before-counts are the analysis's own row_count and
// column_count; otherwise the original file's counts as stored.
export type HeaderShape =
  | { kind: "cleaned"; rows: number; columns: number; originalRows: number; originalColumns: number }
  | { kind: "original"; rows: number | null; columns: number | null };

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

export function readHeaderShape(
  cleaningReport: Record<string, unknown> | null,
  rowCount: number | null,
  columnCount: number | null,
): HeaderShape {
  const summary = cleaningReport?.summary;
  if (typeof summary === "object" && summary !== null && !Array.isArray(summary)) {
    // The backend's summary also has rows_removed and columns_removed, which
    // can be -1 (cleaning can add a column); only these four are read.
    const { rows_before, rows_after, columns_before, columns_after } = summary as Record<string, unknown>;
    if (
      isCount(rows_before) &&
      isCount(rows_after) &&
      isCount(columns_before) &&
      isCount(columns_after) &&
      rows_before === rowCount &&
      columns_before === columnCount
    ) {
      return {
        kind: "cleaned",
        rows: rows_after,
        columns: columns_after,
        originalRows: rows_before,
        originalColumns: columns_before,
      };
    }
  }
  return { kind: "original", rows: rowCount, columns: columnCount };
}

// The header's second line: one visible text, and a sentence for screen
// readers (spoken is null when the visible text reads well on its own).
export type HeaderLine = { visible: string; spoken: string | null };

function rowsAndColumns(rows: number, columns: number): string {
  return `${formatCount(rows)} ${rows === 1 ? "row" : "rows"} and ${formatCount(columns)} ${columns === 1 ? "column" : "columns"}`;
}

export function headerLine(shape: HeaderShape): HeaderLine | null {
  if (shape.kind === "original") {
    if (shape.rows === null || shape.columns === null) return null;
    return { visible: "as in the original file", spoken: null };
  }
  const { rows, columns, originalRows, originalColumns } = shape;
  if (rows === originalRows && columns === originalColumns) {
    return {
      visible: "after cleaning · same as the original file",
      spoken: `After cleaning. The original file had the same ${rowsAndColumns(originalRows, originalColumns)}.`,
    };
  }
  return {
    visible: `after cleaning · ${formatCount(originalRows)} × ${formatCount(originalColumns)} in the original file`,
    spoken: `After cleaning. The original file had ${rowsAndColumns(originalRows, originalColumns)}.`,
  };
}

// The narrative split around the chart file names it mentions: plain text,
// or a listed name (which the page shows as a link to that chart's card).
export type NarrativePart = string | { name: string };

// A character that can continue a chart file name. Any non-ASCII neighbour
// counts as one, so a name glued to it stays plain text.
function isNameChar(ch: string): boolean {
  return ch !== "" && (/[0-9A-Za-z_-]/.test(ch) || ch.charCodeAt(0) > 0x7f);
}

// Whole names only, the longest first at each position, with startsWith and
// a boundary check on each side instead of a lookaround regex.
export function splitChartNames(text: string, names: readonly string[]): NarrativePart[] {
  const candidates = names
    .filter((name, i) => name !== "" && names.indexOf(name) === i)
    .sort((a, b) => b.length - a.length);
  const parts: NarrativePart[] = [];
  let start = 0;
  let i = 0;
  while (i < text.length) {
    const name = isNameChar(text.charAt(i - 1))
      ? undefined
      : candidates.find((candidate) => text.startsWith(candidate, i) && !isNameChar(text.charAt(i + candidate.length)));
    if (name === undefined) {
      i += 1;
      continue;
    }
    if (i > start) parts.push(text.slice(start, i));
    parts.push({ name });
    i += name.length;
    start = i;
  }
  if (start < text.length) parts.push(text.slice(start));
  return parts;
}
