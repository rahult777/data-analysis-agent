// The real analysis page's charts: every kept chart loads from the site's own
// /demo/charts/, a hidden chart never appears or loads, nothing leaves the
// site's origin, and the real scatter renders in its scripts-only sandbox.
// Since M2b.4c every card's title shows its whole label (it wraps, never an
// ellipsis) and every PNG card links to its image at full size. Every test
// runs at 320 px and at 1280 px.

import { expect, test, type Page } from "@playwright/test";

import { expectSameOriginOnly, logRequests, saveRequestLog, shot, statusCalls } from "../e2e-public/helpers";
import { FULL_SIZE } from "../e2e-public/site";
import {
  chartCardId,
  chartUrl,
  HIDDEN_CHARTS,
  HIDDEN_STEMS,
  KEPT_CHARTS,
  NARRATIVE_LABELS,
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

// A card's title: the first element of its first row (ChartGrid.tsx).
test("every card's title shows its whole label: it wraps instead of ending in an ellipsis", async ({ page }, info) => {
  await page.goto(PAGE);
  const titles = await page.locator('[id^="chart-"]').evaluateAll((cards) =>
    cards.map((card) => {
      const title = card.firstElementChild?.firstElementChild ?? null;
      if (!(title instanceof HTMLElement)) return { text: "", ellipsis: true, clipped: true, lines: 0 };
      const style = getComputedStyle(title);
      return {
        text: title.textContent ?? "",
        ellipsis: style.textOverflow === "ellipsis",
        clipped: title.scrollWidth > title.clientWidth,
        lines: Math.round(title.getBoundingClientRect().height / Number.parseFloat(style.lineHeight)),
      };
    }),
  );
  expect(titles).toHaveLength(KEPT_CHARTS.length);
  for (const title of titles) {
    expect.soft(title.ellipsis, `${title.text}: no ellipsis`).toBe(false);
    expect.soft(title.clipped, `${title.text}: nothing cut off`).toBe(false);
  }
  // The labels the narrative names, whole (independent literals).
  const shown = titles.map((title) => title.text);
  for (const [, label] of NARRATIVE_LABELS) expect.soft(shown, label).toContain(label);
  // On a phone the three longest labels take a second line (they ended in an
  // ellipsis before M2b.4c).
  if ((page.viewportSize()?.width ?? 0) <= 320) expect(titles.filter((title) => title.lines > 1).length, "titles on two lines at 320 px").toBeGreaterThanOrEqual(3);
  await shot(page, info, "snapshot-chart-titles");
});

test("every PNG card offers its image at full size through a plain link named for its chart; the scatter's card has none", async ({ page }) => {
  await page.goto(PAGE);
  const labels = new Map(NARRATIVE_LABELS);
  for (const name of KEPT_CHARTS) {
    const card = page.locator(`#${chartCardId(name)}`);
    const links = card.getByRole("link");
    if (name === SCATTER_CHART) {
      await expect(links, name).toHaveCount(0);
      continue;
    }
    await expect(links, name).toHaveCount(1);
    await expect(links, name).toHaveAttribute("href", chartUrl(name));
    await expect(card.locator("img"), name).toHaveAttribute("src", chartUrl(name));
    expect(await links.evaluate((a) => a.getAttributeNames().sort()), `${name}: a plain link`).toEqual(["class", "href"]);
    const title = await card.evaluate((element) => element.firstElementChild?.firstElementChild?.textContent ?? "");
    const label = labels.get(name);
    if (label !== undefined) expect(title, name).toBe(label);
    await expect(links, name).toHaveAccessibleName(`${FULL_SIZE} (${title})`);
    expect((await links.boundingBox())?.height ?? 0, `${name}: a tap target`).toBeGreaterThanOrEqual(44);
  }
  // The links add neither an image nor a frame: 13 images, 1 frame.
  await expect(page.locator("img")).toHaveCount(KEPT_CHARTS.length - 1);
  await expect(page.locator("iframe")).toHaveCount(1);
});
