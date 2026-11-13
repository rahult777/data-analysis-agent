// The public build under frontend/vercel.json's headers (M2b.4c; owner rulings
// Q5, Q13 and Q14), as e2e-public/serve-static.mjs applies them, matched by
// lib/vercel-headers.mjs with next's bundled path-to-regexp, as Vercel matches
// them: every response carries exactly one header set, the page set or, under
// /demo/charts/, the chart set; no page and no chart frame reports a Content
// Security Policy violation, and a control proves the listener sees one; and a
// path that ends in a slash answers 308 to the path without it
// (trailingSlash: false). Every test runs at 320 px and at 1280 px.

import { expect, test, type Page } from "@playwright/test";

import { chartCardId, FIXTURE_ID, HTML_CHART, PNG_CHART } from "./fixture";
import { logResponses, recordCspViolations } from "./helpers";
import { expectOneHeaderSet } from "./site";

const PAGE = `/analysis/${FIXTURE_ID}`;
const CHART_URL = `/demo/charts/${HTML_CHART.slice(0, -".html".length)}`;

// The analysis page with every layer open and every chart card scrolled in,
// so each image, frame and panel has loaded under the headers.
async function openEverything(page: Page): Promise<void> {
  await page.goto(PAGE);
  for (const name of [/Analyst Report/, /Open Questions/, /Technical Detail/]) await page.getByRole("button", { name }).click();
  for (const name of [PNG_CHART, HTML_CHART]) await page.locator(`#${chartCardId(name)}`).scrollIntoViewIfNeeded();
  const img = page.locator(`#${chartCardId(PNG_CHART)} img`);
  await expect.poll(() => img.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth)).toBe(48);
  await expect(page.frameLocator("iframe").locator("#fixture-chart")).toHaveAttribute("data-rendered", "yes");
  await page.waitForLoadState("networkidle");
}

test("every response carries exactly one header set, and nothing reports a CSP violation", async ({ page }) => {
  const violations = await recordCspViolations(page);
  const responses = logResponses(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await openEverything(page);
  await page.goto("/no-such-page");
  await page.waitForLoadState("networkidle");
  // The chart opened directly: the chart set, and its inline script still runs.
  await page.goto(CHART_URL);
  await expect(page.locator("#fixture-chart")).toHaveAttribute("data-rendered", "yes");

  expect(violations, "CSP violations").toEqual([]);
  const paths = responses.map((response) => new URL(response.url).pathname);
  expect(paths.filter((path) => path.startsWith("/demo/charts/")).length, "responses under /demo/charts/").toBeGreaterThan(0);
  expect(paths.filter((path) => !path.startsWith("/demo/charts/")).length, "page and file responses").toBeGreaterThan(0);
  for (const response of responses) expectOneHeaderSet(response.url, response.headers);
});

test("the violation listener works: a data: image on the page and a data: script in the chart frame are blocked and reported", async ({ page }) => {
  const violations = await recordCspViolations(page);
  await openEverything(page);
  await page.evaluate(() => {
    const image = document.createElement("img");
    image.src = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
    document.body.append(image);
  });
  const frame = page.frames().find((candidate) => new URL(candidate.url()).pathname === CHART_URL);
  expect(frame, "the chart's frame").toBeDefined();
  await frame?.evaluate(() => {
    const script = document.createElement("script");
    script.src = "data:text/javascript,void 0";
    document.body.append(script);
  });
  await expect.poll(() => violations.length).toBe(2);
  expect(violations).toEqual(
    expect.arrayContaining([
      expect.stringMatching(new RegExp(`^img-src data\\S* on ${PAGE}$`)),
      expect.stringMatching(new RegExp(`^script-src-elem data\\S* on ${CHART_URL}$`)),
    ]),
  );
});

test("a path that ends in a slash answers 308 to the path without it, keeping its query", async ({ request }) => {
  const cases: ReadonlyArray<readonly [string, string]> = [
    [`${PAGE}/`, PAGE],
    [`${PAGE}/?a=1`, `${PAGE}?a=1`],
    ["/no-such-page/", "/no-such-page"],
  ];
  for (const [from, to] of cases) {
    const response = await request.get(from, { maxRedirects: 0 });
    expect(response.status(), from).toBe(308);
    expect(response.headers()["location"], from).toBe(to);
  }
  expect((await request.get("/", { maxRedirects: 0 })).status(), "the root").toBe(200);
});
