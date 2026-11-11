// Local mode's identity (M2b.4a), under next dev with every API call mocked:
// the name on "/" and the page titles, and robots.txt and sitemap.xml, which
// disallow everything and list nothing (local mode is never public and has no
// site address). Local mode ignores the public build's site settings, even the
// invalid values playwright.config.ts sets. Every test runs at 320 px and at
// 1280 px.

import { expect, test } from "@playwright/test";

import { shot } from "../e2e-public/helpers";
import { LOCAL_ROBOTS_TXT, OLD_NAME, SITE_DESCRIPTION, SITE_NAME, TITLE_LOCAL_ANALYSIS, sitemapXml } from "../e2e-public/site";
import { ANALYSIS_ID, MockApi, openAsOwner, statusBody } from "./mockApi";

let api: MockApi;

test.beforeEach(async ({ page }) => {
  api = new MockApi(page);
  await api.install();
});

test.afterEach(() => {
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

test("'/' is Omnalynt's upload page", async ({ page }, info) => {
  await page.goto("/");
  await expect(page).toHaveTitle(SITE_NAME);
  await expect(page.getByRole("heading", { level: 1, name: SITE_NAME, exact: true })).toBeVisible();
  await expect(page.getByText("Upload your data. Get intelligent analysis.", { exact: true })).toBeVisible();
  expect(await page.locator('head meta[name="description"]').getAttribute("content")).toBe(SITE_DESCRIPTION);
  expect(await page.evaluate(() => document.body.innerText)).not.toContain(OLD_NAME);
  await shot(page, info, "local-home");
});

test("'/' has no canonical link: local mode has no site address", async ({ page }) => {
  await page.goto("/");
  expect(await page.locator('head link[rel="canonical"]').count(), "no canonical link").toBe(0);
});

test("an analysis page is titled 'Analysis', not 'Example analysis'", async ({ page }) => {
  api.setStatus(statusBody("complete"));
  api.setAnalysis({
    id: ANALYSIS_ID,
    filename: "sales.csv",
    status: "complete",
    created_at: "2026-10-24T12:00:00+00:00",
    row_count: 12,
    column_count: 3,
    data_quality_score: 0.9,
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
  await expect(page).toHaveTitle(TITLE_LOCAL_ANALYSIS);
});

test("robots.txt disallows everything and sitemap.xml lists nothing", async ({ request }) => {
  const robots = await request.get("/robots.txt");
  expect(robots.status()).toBe(200);
  expect(robots.headers()["content-type"]).toMatch(/^text\/plain/);
  expect(await robots.text()).toBe(LOCAL_ROBOTS_TXT);
  const sitemap = await request.get("/sitemap.xml");
  expect(sitemap.status()).toBe(200);
  expect(sitemap.headers()["content-type"]).toMatch(/^application\/xml/);
  expect(await sitemap.text()).toBe(sitemapXml([]));
});
