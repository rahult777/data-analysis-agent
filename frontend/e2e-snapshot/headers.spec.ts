// The real site under frontend/vercel.json's headers (M2b.4c; owner rulings
// Q5, Q13 and Q14), as e2e-public/serve-static.mjs applies them: every response
// carries exactly one header set, the page set or, under /demo/charts/, the
// chart set; no page and no chart frame reports a Content Security Policy
// violation, and a control proves the listener sees one; the real scatter
// still draws its 185 points, in its frame and opened directly; and a path
// that ends in a slash answers 308. Every test runs at 320 px and at 1280 px.

import { expect, test, type Page } from "@playwright/test";

import { logResponses, recordCspViolations } from "../e2e-public/helpers";
import { expectOneHeaderSet } from "../e2e-public/site";
import { chartCardId, chartUrl, KEPT_CHARTS, REAL_ID, SCATTER_CHART, SCATTER_POINTS } from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;
const SCATTER_URL = chartUrl(SCATTER_CHART);

// The analysis page with every layer open and every chart card scrolled in:
// each image decoded and the scatter drawn, all under the headers.
async function openEverything(page: Page): Promise<void> {
  await page.goto(PAGE);
  for (const name of [/Analyst Report/, /Open Questions/, /Technical Detail/]) await page.getByRole("button", { name }).click();
  for (const name of KEPT_CHARTS) {
    const card = page.locator(`#${chartCardId(name)}`);
    await card.scrollIntoViewIfNeeded();
    if (name === SCATTER_CHART) continue;
    await expect
      .poll(() => card.locator("img").evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0), { message: name })
      .toBe(true);
  }
  await expect(page.frameLocator(`iframe[src="${SCATTER_URL}"]`).locator(".scatterlayer .point")).toHaveCount(SCATTER_POINTS);
  await page.waitForLoadState("networkidle");
}

test("every response carries exactly one header set, nothing reports a CSP violation, and the scatter draws its 185 points", async ({ page }) => {
  const violations = await recordCspViolations(page);
  const responses = logResponses(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await openEverything(page);
  await page.goto("/no-such-page");
  await page.waitForLoadState("networkidle");
  // The scatter opened directly: the chart set, and plotly still draws.
  await page.goto(SCATTER_URL);
  await expect(page.locator(".scatterlayer .point")).toHaveCount(SCATTER_POINTS);

  expect(violations, "CSP violations").toEqual([]);
  const paths = responses.map((response) => new URL(response.url).pathname);
  expect(paths.filter((path) => path.startsWith("/demo/charts/")).length, "responses under /demo/charts/").toBeGreaterThan(0);
  expect(paths.filter((path) => !path.startsWith("/demo/charts/")).length, "page and file responses").toBeGreaterThan(0);
  for (const response of responses) expectOneHeaderSet(response.url, response.headers);
});

test("the violation listener works: a data: image on the page and a data: script in the scatter's frame are blocked and reported", async ({ page }) => {
  const violations = await recordCspViolations(page);
  await openEverything(page);
  await page.evaluate(() => {
    const image = document.createElement("img");
    image.src = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
    document.body.append(image);
  });
  const frame = page.frames().find((candidate) => new URL(candidate.url()).pathname === SCATTER_URL);
  expect(frame, "the scatter's frame").toBeDefined();
  await frame?.evaluate(() => {
    const script = document.createElement("script");
    script.src = "data:text/javascript,void 0";
    document.body.append(script);
  });
  await expect.poll(() => violations.length).toBe(2);
  expect(violations).toEqual(
    expect.arrayContaining([
      expect.stringMatching(new RegExp(`^img-src data\\S* on ${PAGE}$`)),
      expect.stringMatching(new RegExp(`^script-src-elem data\\S* on ${SCATTER_URL}$`)),
    ]),
  );
});

test("a path that ends in a slash answers 308 to the path without it", async ({ request }) => {
  const response = await request.get(`${PAGE}/`, { maxRedirects: 0 });
  expect(response.status()).toBe(308);
  expect(response.headers()["location"]).toBe(PAGE);
});
