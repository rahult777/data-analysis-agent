// Chart iframes run scripts only, in an opaque origin (never
// allow-same-origin), and charts are lazy-loaded (M2b.1). Route-mocked like
// pause.spec.ts: the analysis and its chart files come from e2e/mockApi.ts;
// the two charts are the public snapshot fixture's. Runs at both viewport
// widths.

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { ANALYSIS_ID, MOCK_API_URL, MockApi, openAsVisitor, statusBody } from "./mockApi";

const CHARTS = path.join(__dirname, "fixtures", "snapshot", "charts");
const PNG = "00000000-0000-4000-a000-000000000001_histogram_fixture_value.png";
const HTML = "00000000-0000-4000-a000-000000000001_scatter_fixture_x_fixture_y.html";

test("a chart iframe is sandboxed (scripts only, opaque origin) and lazy; a chart image is lazy", async ({ page }) => {
  const api = new MockApi(page);
  await api.install();
  api.setStatus(statusBody("complete"));
  api.setAnalysis({
    id: ANALYSIS_ID,
    filename: "charts.csv",
    status: "complete",
    created_at: "2026-10-09T12:00:00+00:00",
    row_count: 3,
    column_count: 2,
    data_quality_score: 0.5,
    profile_report: null,
    cleaning_report: null,
    cleaning_decisions: null,
    analysis_report: null,
    insight_report: null,
    executive_summary: null,
    chart_paths: [PNG, HTML],
  });
  api.setChart(PNG, readFileSync(path.join(CHARTS, PNG)), "image/png");
  api.setChart(HTML, readFileSync(path.join(CHARTS, HTML)), "text/html; charset=utf-8");
  await openAsVisitor(page);

  const iframe = page.locator("iframe");
  await expect(iframe).toHaveAttribute("src", `${MOCK_API_URL}/charts/${HTML}`);
  await expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
  await expect(iframe).toHaveAttribute("loading", "lazy");
  await expect(iframe).toHaveAttribute("referrerpolicy", "no-referrer");
  const img = page.locator("img");
  await expect(img).toHaveAttribute("src", `${MOCK_API_URL}/charts/${PNG}`);
  await expect(img).toHaveAttribute("loading", "lazy");
  await expect(img).toHaveAttribute("decoding", "async");

  await iframe.scrollIntoViewIfNeeded();
  await expect(page.frameLocator("iframe").locator("#fixture-chart")).toHaveAttribute("data-rendered", "yes");
  const frame = page.frames().find((f) => f.url() === `${MOCK_API_URL}/charts/${HTML}`);
  expect(await frame?.evaluate(() => window.origin), "the chart's origin").toBe("null");
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});
