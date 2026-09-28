// A long uploaded filename must never widen the page at 320 px (errors.md
// 2026-09-28: D3's 37-character upload name overflowed the results header by
// 29 px). Route-mocked like pause.spec.ts; runs at both viewport widths.

import { expect, test, type Page } from "@playwright/test";

import { ANALYSIS_ID, MockApi, openAsOwner, statusBody } from "./mockApi";

// 60 characters, no spaces: nowhere a browser would break it by default.
const LONG_NAME = "customer_transactions_by_region_and_channel_2024q3_final.csv";

let api: MockApi;

test.beforeEach(async ({ page }) => {
  api = new MockApi(page);
  await api.install();
});

test.afterEach(() => {
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

async function pageOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

test("the results header wraps a 60-character filename: no page overflow, the whole name shown", async ({ page }) => {
  expect(LONG_NAME).toHaveLength(60);
  api.setStatus(statusBody("complete"));
  api.setAnalysis({
    id: ANALYSIS_ID,
    filename: LONG_NAME,
    status: "complete",
    created_at: "2026-09-28T12:00:00+00:00",
    row_count: 200,
    column_count: 9,
    data_quality_score: 0.6,
    profile_report: null,
    cleaning_report: null,
    cleaning_decisions: null,
    analysis_report: null,
    insight_report: null,
    executive_summary: null,
    chart_paths: [],
  });
  await openAsOwner(page);
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();

  const name = page.getByText(LONG_NAME, { exact: true });
  await expect(name).toHaveCount(1);
  expect(await pageOverflow(page), "no horizontal page overflow").toBe(0);
  // Wrapped, not clipped: the name's box ends inside the viewport.
  const box = await name.boundingBox();
  const viewport = page.viewportSize();
  expect(box && viewport && box.x + box.width <= viewport.width).toBe(true);
});

test("the upload preview keeps a 60-character filename inside the page (truncated by design, full name in the DOM)", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: LONG_NAME,
    mimeType: "text/csv",
    buffer: Buffer.from("region,revenue\nnorth,10\nsouth,20\n"),
  });
  const name = page.getByText(LONG_NAME, { exact: true });
  await expect(name).toHaveCount(1);
  await expect(name).toBeVisible();
  expect(await pageOverflow(page), "no horizontal page overflow").toBe(0);
});
