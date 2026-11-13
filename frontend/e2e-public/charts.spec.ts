// The public snapshot build's charts: served by the site itself from
// /demo/charts/ (an HTML chart's URL has no .html, as on Vercel), HTML charts
// in a scripts-only sandboxed iframe, everything lazy-loaded. Since M2b.4c an
// image renders without waiting for JavaScript (its card clears the
// placeholder even when it loaded before the page hydrated), a PNG card links
// to its image at full size, and a card takes the keyboard focus from a link
// to it. Every test runs at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { chartCardId, FIXTURE_ID, HTML_CHART, PNG_CHART, PNG_LABEL } from "./fixture";
import { expectSameOriginOnly, logRequests, saveRequestLog } from "./helpers";
import { CHART_NOJS_LINE, FULL_SIZE } from "./site";

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

test("the PNG card offers its image at full size through a plain link named for the chart; the HTML chart's card has none", async ({ page }) => {
  await page.goto(PAGE);
  const link = page.locator(`#${chartCardId(PNG_CHART)}`).getByRole("link");
  await expect(link).toHaveCount(1);
  await expect(link).toHaveAccessibleName(`${FULL_SIZE} (${PNG_LABEL})`);
  await expect(link).toHaveAttribute("href", PNG_CHART_URL);
  expect(await link.evaluate((a) => a.getAttributeNames().sort()), "a plain link").toEqual(["class", "href"]);
  expect((await link.boundingBox())?.height ?? 0, "a tap target").toBeGreaterThanOrEqual(44);
  await expect(page.locator(`#${chartCardId(HTML_CHART)}`).getByRole("link")).toHaveCount(0);
  // The link adds neither an image nor a frame.
  await expect(page.locator("img")).toHaveCount(1);
  await expect(page.locator("iframe")).toHaveCount(1);
});

test("with JavaScript the interactive chart's no-JavaScript line is in its card, hidden", async ({ page }) => {
  await page.goto(PAGE);
  const line = page.locator(`#${chartCardId(HTML_CHART)}`).getByText(CHART_NOJS_LINE, { exact: true });
  await expect(line).toHaveCount(1);
  await expect(line).toBeHidden();
});

test("an image that loads before the page hydrates still clears its placeholder", async ({ page }) => {
  // Next's scripts are held until the image has loaded, so its load event
  // fires before React listens; only the card's own check after mounting can
  // clear the placeholder then.
  let release = (): void => undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/_next/static/chunks/**", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto(PAGE, { waitUntil: "commit" });
  const card = page.locator(`#${chartCardId(PNG_CHART)}`);
  const img = card.locator("img");
  await expect(img, "the image is in the static HTML").toHaveCount(1);
  await img.scrollIntoViewIfNeeded();
  await expect.poll(() => img.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth)).toBe(48);
  release();
  // Hydration is over once the HTML chart's frame mounts (still gated).
  await expect(page.locator(`#${chartCardId(HTML_CHART)} iframe`)).toHaveCount(1);
  await expect(card.locator(".animate-pulse"), "the placeholder clears").toHaveCount(0);
});

test("Enter on a Referenced charts pill moves the keyboard focus to its chart card, which draws a focus ring", async ({ page }) => {
  await page.goto(PAGE);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  const pill = page.getByRole("region", { name: /Analyst Report/ }).locator(`a[href="#${chartCardId(PNG_CHART)}"]`);
  await expect(pill).toHaveCount(1);
  await pill.focus();
  await page.keyboard.press("Enter");
  const card = page.locator(`#${chartCardId(PNG_CHART)}`);
  await expect(card).toBeFocused();
  expect(await card.evaluate((element) => element.matches(":focus-visible")), "keyboard focus").toBe(true);
  expect(await card.evaluate((element) => getComputedStyle(element).boxShadow), "a focus ring").not.toBe("none");
});
