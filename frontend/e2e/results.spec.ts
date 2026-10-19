// The results view in local mode (M2b.3b.2), route-mocked like pause.spec.ts
// (e2e/mockApi.ts): the header's counts and its second line, chart file names
// in the narrative as links to their cards, a long file name in an executive
// bullet (it wraps, so the page does not overflow at 320 px), the Code
// section's label (and none on a custom question's answer), and the
// correlation matrix's column order under a Danish locale. Runs at both
// viewport widths.

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import type { AnalysisResponse } from "../lib/types";
import { comesBefore, expectNoHorizontalOverflow, shot } from "../e2e-public/helpers";
import { ANALYSIS_ID, MockApi, openAsOwner, openAsVisitor, SESSION_ID, statusBody } from "./mockApi";

const CODE_LABEL = "Written by the Explainer agent to illustrate each step. It is not the code that ran.";
// The public snapshot fixture's two chart files (e2e/charts.spec.ts serves
// them the same way); the HTML one loads no plotly.min.js.
const CHARTS = path.join(__dirname, "fixtures", "snapshot", "charts");
const PNG = "00000000-0000-4000-a000-000000000001_histogram_fixture_value.png";
const HTML = "00000000-0000-4000-a000-000000000001_scatter_fixture_x_fixture_y.html";
// The backend's cleaning_report.summary (backend/agents/cleaner.py): six
// counts; columns_removed is -1 because cleaning added a column.
const BACKEND_SUMMARY = {
  rows_before: 200,
  rows_after: 185,
  rows_removed: 15,
  columns_before: 9,
  columns_after: 10,
  columns_removed: -1,
};

function analysis(fields: Partial<AnalysisResponse>): AnalysisResponse {
  return {
    id: ANALYSIS_ID,
    filename: "results.csv",
    status: "complete",
    created_at: "2026-10-18T12:00:00+00:00",
    row_count: 200,
    column_count: 9,
    data_quality_score: 0.7,
    profile_report: null,
    cleaning_report: null,
    cleaning_decisions: null,
    analysis_report: null,
    insight_report: null,
    executive_summary: null,
    chart_paths: [],
    ...fields,
  };
}

// The results header's stats, and the line right after them.
function header(page: Page): { dd: Locator; line: Locator } {
  return { dd: page.locator("dl dd"), line: page.locator("dl + p") };
}

// Opens an accordion panel and returns it. Under next dev (React's StrictMode)
// Base UI 1.4.1 drops the panel's aria-labelledby, so its region has no name
// there (the static build keeps it): find the panel through the trigger's
// aria-controls instead.
async function openPanel(page: Page, name: RegExp): Promise<Locator> {
  const trigger = page.getByRole("button", { name });
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const id = await trigger.getAttribute("aria-controls");
  expect(id, "the trigger names its panel").toBeTruthy();
  return page.locator(`[id="${id}"]`);
}

let api: MockApi;

test.beforeEach(async ({ page }) => {
  api = new MockApi(page);
  await api.install();
  api.setStatus(statusBody("complete"));
});

test.afterEach(() => {
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

test("the header shows the cleaned counts from the backend's summary, then the original file's on a second line", async ({ page }, info) => {
  api.setAnalysis(analysis({ cleaning_report: { summary: BACKEND_SUMMARY } }));
  await openAsVisitor(page);
  const { dd, line } = header(page);
  await expect.soft(dd).toHaveText(["185", "10", "70%"]);
  await expect(line, "the second line, after the stats").toHaveCount(1);
  await expect.soft(line.locator('[aria-hidden="true"]')).toHaveText("after cleaning \u00b7 200 \u00d7 9 in the original file");
  await expect.soft(line.locator(".sr-only")).toHaveText("After cleaning. The original file had 200 rows and 9 columns.");
  // What a screen reader reads: the sentence, not the visible shorthand.
  await expect.soft(line).toMatchAriaSnapshot("- paragraph: After cleaning. The original file had 200 rows and 9 columns.");
  await shot(page, info, "local-header-summary");
});

test("with no cleaning summary the header keeps the stored counts, labelled as the original file's", async ({ page }, info) => {
  api.setAnalysis(analysis({ cleaning_report: null }));
  await openAsVisitor(page);
  const { dd, line } = header(page);
  await expect.soft(dd).toHaveText(["200", "9", "70%"]);
  await expect(line, "the second line, after the stats").toHaveCount(1);
  await expect.soft(line).toHaveText("as in the original file");
  await expect.soft(line.locator("span"), "one text, no separate sentence").toHaveCount(0);
  await shot(page, info, "local-header-fallback");
});

test("when cleaning changed neither count, the second line says so", async ({ page }) => {
  const summary = { rows_before: 185, rows_after: 185, rows_removed: 0, columns_before: 10, columns_after: 10, columns_removed: 0 };
  api.setAnalysis(analysis({ row_count: 185, column_count: 10, cleaning_report: { summary } }));
  await openAsVisitor(page);
  const { dd, line } = header(page);
  await expect.soft(dd).toHaveText(["185", "10", "70%"]);
  await expect(line, "the second line, after the stats").toHaveCount(1);
  await expect.soft(line.locator('[aria-hidden="true"]')).toHaveText("after cleaning \u00b7 same as the original file");
  await expect.soft(line.locator(".sr-only")).toHaveText("After cleaning. The original file had the same 185 rows and 10 columns.");
});

test("a summary whose before-count differs from the analysis's row count is not used", async ({ page }) => {
  api.setAnalysis(analysis({ cleaning_report: { summary: { ...BACKEND_SUMMARY, rows_before: 201 } } }));
  await openAsVisitor(page);
  const { dd, line } = header(page);
  await expect.soft(dd).toHaveText(["200", "9", "70%"]);
  await expect(line, "the second line, after the stats").toHaveCount(1);
  await expect.soft(line).toHaveText("as in the original file");
});

test("the Code section carries its label once, and a custom question's answer carries none", async ({ page }) => {
  api.setAnalysis(analysis({ insight_report: { technical_layer: { code_blocks: ["df.describe()", "df.info()"] } } }));
  api.setQuestionAnswer({ answer: "Three regions.", pandas_code: "df['region'].nunique()" });
  await openAsOwner(page);

  const technical = await openPanel(page, /Technical Detail/);
  const label = technical.getByText(CODE_LABEL, { exact: true });
  await expect(label).toHaveCount(1);
  expect(await comesBefore(technical.getByText("Code", { exact: true }), label), "under the Code heading").toBe(true);
  expect(await comesBefore(label, technical.locator("pre").first()), "above the first block").toBe(true);

  // A custom question's code is the code that ran: no label on it.
  await page.getByLabel("Ask a question about this dataset").fill("How many regions?");
  await page.getByRole("button", { name: "Submit question" }).click();
  await expect(page.getByText("Three regions.", { exact: true })).toBeVisible();
  await expect(page.locator("pre code").filter({ hasText: "df['region'].nunique()" })).toHaveCount(1);
  await expect(page.getByText(CODE_LABEL, { exact: true }), "only the Code section's label").toHaveCount(1);
  expect(api.questionCalls).toEqual([{ body: { question: "How many regions?" }, sessionHeader: SESSION_ID }]);
});

test("chart file names in the narrative become links to their cards, and an unlisted name stays text", async ({ page }) => {
  const unlisted = "00000000-0000-4000-a000-000000000001_boxplot_fixture_value.png";
  const narrative = `The values (${PNG}) are skewed.\n\nThe scatter (${HTML}) shows little; see also ${unlisted}.`;
  api.setAnalysis(analysis({ chart_paths: [PNG, HTML], insight_report: { analyst_layer: { narrative } } }));
  api.setChart(PNG, readFileSync(path.join(CHARTS, PNG)), "image/png");
  api.setChart(HTML, readFileSync(path.join(CHARTS, HTML)), "text/html; charset=utf-8");
  await openAsVisitor(page);

  const analyst = await openPanel(page, /Analyst Report/);
  await expect(analyst.locator("p")).toHaveText([
    "The values (Distribution \u2014 fixture value) are skewed.",
    `The scatter (Scatter \u2014 fixture x fixture y) shows little; see also ${unlisted}.`,
  ]);
  const links = analyst.locator("p a");
  await expect(links).toHaveText(["Distribution \u2014 fixture value", "Scatter \u2014 fixture x fixture y"]);
  const hrefs = [
    "#chart-00000000-0000-4000-a000-000000000001-histogram-fixture-value-png",
    "#chart-00000000-0000-4000-a000-000000000001-scatter-fixture-x-fixture-y-html",
  ];
  expect(await links.evaluateAll((elements) => elements.map((a) => a.getAttribute("href")))).toEqual(hrefs);
  for (const href of hrefs) await expect(page.locator(href), `the card ${href}`).toHaveCount(1);
});

test("a long chart file name in an executive bullet wraps instead of widening the page", async ({ page }) => {
  // After its last hyphen the name has no break opportunity, and at 320 px
  // that part is wider than a bullet; 1280 px is the control.
  const name = `${ANALYSIS_ID}_histogram_revenue_outlier_flag.png`;
  const bullet = {
    finding: `The finding cites ${name}.`,
    context: `The context cites ${name}.`,
    recommended_action: `The action cites ${name}.`,
  };
  api.setAnalysis(analysis({ executive_summary: { bullets: [bullet] } }));
  await openAsVisitor(page);
  for (const [field, text] of Object.entries(bullet)) {
    const paragraph = page.getByText(text, { exact: true });
    await expect(paragraph, `the ${field} text`).toHaveCount(1);
    const fits = await paragraph.evaluate((p) => {
      const item = p.closest("li");
      return item !== null && p.scrollWidth <= p.clientWidth && p.getBoundingClientRect().right <= item.getBoundingClientRect().right;
    });
    expect.soft(fits, `the ${field} text fits its bullet`).toBe(true);
  }
  await expectNoHorizontalOverflow(page);
});

test.describe("under a Danish locale", () => {
  test.use({ locale: "da-DK" });

  test("the correlation matrix orders its columns in English, whatever the browser's locale", async ({ page }) => {
    // Danish collation sorts "aa" after "z" (it reads as the letter a-ring).
    const matrix = { z_units: { z_units: 1, aa_score: 0.5 }, aa_score: { z_units: 0.5, aa_score: 1 } };
    api.setAnalysis(analysis({ analysis_report: { correlation_matrix: { matrix } } }));
    await openAsVisitor(page);

    const analyst = await openPanel(page, /Analyst Report/);
    const columns = analyst.locator("table thead th[scope='col']");
    await expect(columns).toHaveCount(2);
    expect(await columns.evaluateAll((cells) => cells.map((cell) => cell.getAttribute("title")))).toEqual(["aa_score", "z_units"]);
  });
});
