// The committed snapshot (frontend/snapshot/: the demo analysis of 2026-10-03,
// exported in M2b.3a) that the snapshot e2e builds the site from, and the
// values the tests expect from it. The literals pin what must not drift.

import { readFileSync } from "node:fs";
import path from "node:path";

import type { SnapshotAnalysis } from "../lib/types";

export const SNAPSHOT_ABS = path.join(__dirname, "..", "snapshot");
export const REAL_ID = "77faa166-668b-4001-92e0-94e037de7e3b";
// The owner's "About this example" note for the demo (ruled 2026-10-14): an
// independent literal, never read from the manifest. Its two curly quotation
// marks are written as escapes (\u201c, \u201d).
export const NOTE =
  "One saved run on a small synthetic sales dataset. Nothing the agents wrote has been corrected, so several known errors are left in rather than hidden. The interactive scatter plot shows almost no relationship (r=0.08): it demonstrates the chart, not a finding. One cleaning decision says imputing the median \u201cfabricates $31,738\u201d per transaction; the model invented that number, and the median actually used was $25,536.";

export const MANIFEST: unknown = JSON.parse(readFileSync(path.join(SNAPSHOT_ABS, "manifest.json"), "utf8"));
export const ANALYSIS = JSON.parse(
  readFileSync(path.join(SNAPSHOT_ABS, "analyses", `${REAL_ID}.json`), "utf8"),
) as SnapshotAnalysis;

// The charts the page shows, and the shared bundle its HTML chart loads.
export const KEPT_CHARTS: string[] = ANALYSIS.chart_paths;
export const SCATTER_CHART = `${REAL_ID}_scatter_units_sold_discount_pct.html`;
export const PLOTLY = "plotly.min.js";
// The scatter plots every cleaned row: both of its columns were imputed, so
// no row drops out.
export const SCATTER_POINTS = 185;

// The two identifier charts the export left out (--hide). Nothing published
// may name them, with or without the analysis id.
export const HIDDEN_CHARTS = [`${REAL_ID}_barchart_customer_id.png`, `${REAL_ID}_barchart_product_code.png`];
export const HIDDEN_STEMS = ["barchart_customer_id", "barchart_product_code"];

// The site's URL for a chart, as lib/api.ts chartUrl builds it in snapshot
// mode (an HTML chart's URL has no .html, as on Vercel).
export function chartUrl(name: string): string {
  return `/demo/charts/${name.replace(/\.html$/, "")}`;
}

// A chart card's element id, as ChartGrid.tsx chartAnchorId builds it.
export function chartCardId(name: string): string {
  return `chart-${name.replace(/[^a-zA-Z0-9]/g, "-")}`;
}
