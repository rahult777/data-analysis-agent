// The public snapshot build's analysis page: the finished results, rendered
// from the built-in fixture, with no progress view, no status call, no
// localStorage and no API request. Any other id is a 404. Every test runs at
// 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { FIXTURE, FIXTURE_ID, UNLISTED_ID } from "./fixture";
import {
  expectNoHorizontalOverflow,
  expectSameOriginOnly,
  localStorageCalls,
  logRequests,
  saveRequestLog,
  shot,
  spyOnLocalStorage,
  statusCalls,
} from "./helpers";

const PAGE = `/analysis/${FIXTURE_ID}`;
const FIRST_FINDING = FIXTURE.executive_summary.bullets[0].finding ?? "";
// Draft copy; the owner approves it at STOP 2 (components/AnalysisResults.tsx).
const READ_ONLY_COPY = "This is a read-only copy of a finished analysis, so you can't ask questions about its data here.";

test("renders the finished results from the snapshot, with no progress view, status call, localStorage or API request", async ({ page, baseURL }, info) => {
  const requests = logRequests(page);
  await spyOnLocalStorage(page);
  const response = await page.goto(PAGE);
  expect(response?.status()).toBe(200);

  await expect(page.getByRole("heading", { level: 1, name: "Analysis" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
  await expect(page.getByText(FIXTURE.filename, { exact: true })).toBeVisible();
  const stats = page.locator("dl");
  for (const text of ["Rows", String(FIXTURE.row_count), "Columns", String(FIXTURE.column_count), "Data quality", "90%"]) {
    await expect(stats).toContainText(text);
  }
  for (const bullet of FIXTURE.executive_summary.bullets) {
    await expect(page.getByText(bullet.finding ?? "", { exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await expect(page.getByText(FIXTURE.insight_report.analyst_layer.narrative ?? "", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Technical Detail/ }).click();
  await expect(page.getByText(FIXTURE.cleaning_decisions[0].reason, { exact: true })).toBeVisible();

  // No progress view: none of its pipeline stages.
  for (const stage of ["Profiler", "Cleaner", "Analyzer", "Explainer"]) {
    await expect(page.getByText(stage, { exact: true })).toHaveCount(0);
  }
  await expectNoHorizontalOverflow(page);
  await page.waitForLoadState("networkidle");
  expect(await localStorageCalls(page), "no localStorage call").toEqual([]);
  expect(statusCalls(requests), "zero status calls").toEqual([]);
  expectSameOriginOnly(requests, baseURL);
  saveRequestLog(requests, info, "analysis");
  await shot(page, info, "analysis");
});

test("no question UI: one line of read-only copy in its place, and no upload wording", async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask a question" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Submit question" })).toHaveCount(0);
  await expect(page.locator("input, textarea, form")).toHaveCount(0);

  const note = page.getByText(READ_ONLY_COPY, { exact: true });
  await expect(note).toBeVisible();
  // Where the question box was: after the detail layers, last in the results.
  const technical = page.getByRole("button", { name: /Technical Detail/ });
  expect(
    await technical.evaluate(
      (el, other) => Boolean(other && el.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING),
      await note.elementHandle(),
    ),
  ).toBe(true);
  expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/upload/i);
});

test.describe("the prerendered HTML (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("holds the results, not the loading skeleton, and no question box", async ({ page }) => {
    await page.goto(PAGE);
    await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
    await expect(page.getByText(FIRST_FINDING, { exact: true })).toBeVisible();
    await expect(page.getByLabel("Loading results")).toHaveCount(0);
    await expect(page.locator("input, textarea, form")).toHaveCount(0);
    await expect(page.getByText(READ_ONLY_COPY, { exact: true })).toBeVisible();
  });
});

test("another canonical id is a 404", async ({ page }) => {
  const response = await page.goto(`/analysis/${UNLISTED_ID}`);
  expect(response?.status()).toBe(404);
});

test("the .html URL of a listed analysis is a 404, as on Vercel", async ({ page }) => {
  const response = await page.goto(`${PAGE}.html`);
  expect(response?.status()).toBe(404);
});

test("the page's RSC payload is served as text/plain, as Next's exported router needs", async ({ request }) => {
  const response = await request.get(`${PAGE}.txt?_rsc=e2e`);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("text/plain; charset=utf-8");
});
