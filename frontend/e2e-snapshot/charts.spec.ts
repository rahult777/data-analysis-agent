// The real analysis page's charts: every kept chart loads from the site's own
// /demo/charts/, a hidden chart never appears or loads, nothing leaves the
// site's origin, and the real scatter renders in its scripts-only sandbox.
// Every test runs at 320 px and at 1280 px.

import { expect, test, type Page } from "@playwright/test";

import { expectSameOriginOnly, logRequests, saveRequestLog, shot, statusCalls } from "../e2e-public/helpers";
import {
  chartCardId,
  chartUrl,
  HIDDEN_CHARTS,
  HIDDEN_STEMS,
  KEPT_CHARTS,
  PLOTLY,
  REAL_ID,
  SCATTER_CHART,
  SCATTER_POINTS,
} from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;
const PLOTLY_URL = `/demo/charts/${PLOTLY}`;

// Console errors and uncaught errors from the page and its chart frames.
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`${message.location().url}: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`uncaught: ${error.message}`));
  return errors;
}

test("every kept chart loads from /demo/charts/, a hidden chart never appears or loads, and every request stays on the site", async ({ page, baseURL }, info) => {
  const requests = logRequests(page);
  const errors = collectErrors(page);
  await page.goto(PAGE);

  await expect(page.locator('[id^="chart-"]')).toHaveCount(KEPT_CHARTS.length);
  for (const name of KEPT_CHARTS) {
    const card = page.locator(`#${chartCardId(name)}`);
    await card.scrollIntoViewIfNeeded();
    // The placeholder clears once the chart has loaded.
    await expect(card.locator(".animate-pulse"), name).toHaveCount(0);
  }
  for (const name of HIDDEN_CHARTS) await expect(page.locator(`#${chartCardId(name)}`)).toHaveCount(0);
  const html = await page.evaluate(() => document.documentElement.outerHTML);
  for (const stem of HIDDEN_STEMS) expect(html.includes(stem), `${stem} in the page`).toBe(false);

  // Each kept chart and the bundle, once each, with 200; never a hidden chart.
  const chartRequests = requests.filter((r) => new URL(r.url).pathname.startsWith("/demo/charts/"));
  expect(chartRequests.map((r) => `${r.status} ${new URL(r.url).pathname}`).sort()).toEqual(
    [...KEPT_CHARTS.map((name) => `200 ${chartUrl(name)}`), `200 ${PLOTLY_URL}`].sort(),
  );
  expect(requests.filter((r) => HIDDEN_STEMS.some((stem) => r.url.includes(stem))).map((r) => r.url)).toEqual([]);

  expect(requests.filter((r) => r.status === "failed" || (typeof r.status === "number" && r.status >= 400)).map((r) => r.url)).toEqual([]);
  expect(statusCalls(requests), "zero status calls").toEqual([]);
  expect(requests.filter((r) => new URL(r.url).searchParams.has("_rsc")).map((r) => r.url), "no RSC fetch").toEqual([]);
  expectSameOriginOnly(requests, baseURL);
  expect(errors).toEqual([]);
  saveRequestLog(requests, info, "snapshot-charts");
});

test("the real scatter renders in its sandbox: 185 points, an opaque origin, plotly.min.js fetched once, no console error", async ({ page }, info) => {
  const requests = logRequests(page);
  const errors = collectErrors(page);
  await page.goto(PAGE);

  const iframe = page.locator(`iframe[src="${chartUrl(SCATTER_CHART)}"]`);
  await expect(iframe).toHaveCount(1);
  await expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
  await iframe.scrollIntoViewIfNeeded();
  await expect(page.frameLocator(`iframe[src="${chartUrl(SCATTER_CHART)}"]`).locator(".scatterlayer .point")).toHaveCount(SCATTER_POINTS);

  const frame = page.frames().find((f) => new URL(f.url()).pathname === chartUrl(SCATTER_CHART));
  expect(frame, "the scatter's frame").toBeDefined();
  expect(await frame?.evaluate(() => window.origin)).toBe("null");

  const bundle = requests.filter((r) => new URL(r.url).pathname === PLOTLY_URL);
  expect(bundle.map((r) => [r.status, r.frame])).toEqual([[200, "iframe"]]);
  expect(errors).toEqual([]);
  saveRequestLog(requests, info, "snapshot-scatter");
  await shot(page, info, "snapshot-scatter");
});
