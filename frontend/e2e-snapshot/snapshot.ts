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

// The ten chart file names the narrative mentions, in order, each with the
// label the page shows instead (M2b.3b.2): independent literals, the labels as
// the chart cards show them.
export const NARRATIVE_LABELS: ReadonlyArray<readonly [string, string]> = [
  [`${REAL_ID}_histogram_revenue.png`, "Distribution \u2014 revenue"],
  [`${REAL_ID}_boxplot_revenue.png`, "Box plot \u2014 revenue"],
  [`${REAL_ID}_histogram_revenue_outlier_flag.png`, "Distribution \u2014 revenue outlier flag"],
  [`${REAL_ID}_barchart_return_flag.png`, "Top values \u2014 return flag"],
  [`${REAL_ID}_barchart_region.png`, "Top values \u2014 region"],
  [`${REAL_ID}_histogram_discount_pct.png`, "Distribution \u2014 discount pct"],
  [`${REAL_ID}_scatter_units_sold_discount_pct.html`, "Scatter \u2014 units sold discount pct"],
  [`${REAL_ID}_barchart_sales_rep.png`, "Top values \u2014 sales rep"],
  [`${REAL_ID}_barchart_notes.png`, "Top values \u2014 notes"],
  [`${REAL_ID}_correlation_heatmap.png`, "Correlation heatmap"],
];

// The results header (M2b.3b.2): the cleaned counts, then the original file's
// on a second line, as shown and as a screen reader reads it.
export const HEADER = {
  dd: ["185", "10", "70%"],
  visible: "after cleaning \u00b7 200 \u00d7 9 in the original file",
  spoken: "After cleaning. The original file had 200 rows and 9 columns.",
};

// The site's URL for a chart, as lib/chart-url.ts chartUrl builds it in snapshot
// mode (an HTML chart's URL has no .html, as on Vercel).
export function chartUrl(name: string): string {
  return `/demo/charts/${name.replace(/\.html$/, "")}`;
}

// A chart card's element id, as ChartGrid.tsx chartAnchorId builds it.
export function chartCardId(name: string): string {
  return `chart-${name.replace(/[^a-zA-Z0-9]/g, "-")}`;
}
