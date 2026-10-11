// The public snapshot build's charts: served by the site itself from
// /demo/charts/ (an HTML chart's URL has no .html, as on Vercel), HTML charts
// in a scripts-only sandboxed iframe, everything lazy-loaded. Every test runs
// at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { FIXTURE_ID, HTML_CHART, PNG_CHART } from "./fixture";
import { expectSameOriginOnly, logRequests, saveRequestLog } from "./helpers";

const PAGE = `/analysis/${FIXTURE_ID}`;
const HTML_CHART_URL = `/demo/charts/${HTML_CHART.slice(0, -".html".length)}`;
const PNG_CHART_URL = `/demo/charts/${PNG_CHART}`;

test("chart iframes and images carry exactly the expected attributes", async ({ page }) => {
  await page.goto(PAGE);
  const iframe = page.locator("iframe");
  await expect(iframe).toHaveCount(1);
  expect(await iframe.evaluate((el) => el.getAttributeNames().sort())).toEqual(
    ["class", "loading", "referrerpolicy", "sandbox", "src", "title"],
  );
  await expect(iframe).toHaveAttribute("src", HTML_CHART_URL);
  await expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
  await expect(iframe).toHaveAttribute("loading", "lazy");
  await expect(iframe).toHaveAttribute("referrerpolicy", "no-referrer");

  const img = page.locator("img");
  await expect(img).toHaveCount(1);
  expect(await img.evaluate((el) => el.getAttributeNames().sort())).toEqual(["alt", "class", "decoding", "loading", "src"]);
  await expect(img).toHaveAttribute("src", PNG_CHART_URL);
  await expect(img).toHaveAttribute("loading", "lazy");
  await expect(img).toHaveAttribute("decoding", "async");
});

test("the HTML chart's inline script runs in the sandboxed iframe once in view, with an opaque origin; the PNG loads", async ({ page, baseURL }, info) => {
  const requests = logRequests(page);
  await page.goto(PAGE);

  const img = page.locator("img");
  await img.scrollIntoViewIfNeeded();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBe(48);

  const iframe = page.locator("iframe");
  await iframe.scrollIntoViewIfNeeded();
  const chart = page.frameLocator("iframe").locator("#fixture-chart");
  await expect(chart).toHaveText("Synthetic fixture chart: drawn by its inline script.");
  await expect(chart).toHaveAttribute("data-rendered", "yes");
  const frame = page.frames().find((f) => new URL(f.url()).pathname === HTML_CHART_URL);
  expect(frame, "the chart's frame").toBeDefined();
  expect(await frame?.evaluate(() => window.origin)).toBe("null");

  // Each card's loading placeholder clears once its chart has loaded.
  await expect(page.locator("#chart-" + PNG_CHART.replace(/[^a-zA-Z0-9]/g, "-") + " .animate-pulse")).toHaveCount(0);
  await expect(page.locator("#chart-" + HTML_CHART.replace(/[^a-zA-Z0-9]/g, "-") + " .animate-pulse")).toHaveCount(0);

  await page.waitForLoadState("networkidle");
  const chartRequests = requests.filter((r) => new URL(r.url).pathname.startsWith("/demo/charts/"));
  expect(chartRequests.map((r) => [new URL(r.url).pathname, r.status])).toEqual(
    expect.arrayContaining([[PNG_CHART_URL, 200], [HTML_CHART_URL, 200]]),
  );
  expectSameOriginOnly(requests, baseURL);
  saveRequestLog(requests, info, "analysis-charts");
});
