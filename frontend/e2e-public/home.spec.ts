// "/" in the public snapshot build: the landing page (M2b.4b, owner ruling
// B3). The name with the tagline under it, what Omnalynt is, how the four
// agents work with their pauses for a person, the example, and the read-only
// line. Two plain <a href> links lead to the example's analysis (owner rulings
// D7: no next/link; R2: one under the lead, one in the example). A static
// page: no upload UI, no "upload" in its copy, and all of it readable without
// JavaScript. Every test runs at 320 px and at 1280 px.

import { expect, test, type Locator, type Page } from "@playwright/test";

import { FIXTURE, FIXTURE_ID } from "./fixture";
import { comesBefore, expectNoHorizontalOverflow, expectSameOriginOnly, expectTextVisible, lineStats, logRequests, saveRequestLog, shot } from "./helpers";
import {
  EXAMPLE_LINK,
  LANDING_AGENTS,
  LANDING_EXAMPLE,
  LANDING_EXAMPLE_HEADING,
  LANDING_HOW,
  LANDING_KEY,
  LANDING_LEAD,
  LANDING_READ_ONLY,
  SITE_NAME,
  TAGLINE,
  exampleCounts,
} from "./site";

const ANALYSIS = `/analysis/${FIXTURE_ID}`;

// The landing page's parts, in reading order: each is on the page once, as
// exact text, inside <main>. The two links to the example analysis are parts
// too (owner ruling R2, M2b.4b STOP 1): one right under the lead, before the
// four agents, and one in the example's card.
async function landingParts(page: Page): Promise<Locator[]> {
  const main = page.getByRole("main");
  const links = main.locator(`a[href="${ANALYSIS}"]`);
  await expect(links, "two links to the example analysis").toHaveCount(2);
  const parts: Locator[] = [
    main.getByRole("heading", { level: 1, name: SITE_NAME, exact: true }),
    main.getByText(TAGLINE, { exact: true }),
    main.getByText(LANDING_LEAD, { exact: true }),
    links.nth(0),
    main.getByRole("heading", { level: 2, name: LANDING_HOW, exact: true }),
    main.getByText(LANDING_KEY, { exact: true }),
  ];
  for (const [name, text] of LANDING_AGENTS) {
    parts.push(main.getByRole("heading", { level: 3, name, exact: true }), main.getByText(text, { exact: true }));
  }
  parts.push(
    main.getByRole("heading", { level: 2, name: LANDING_EXAMPLE_HEADING, exact: true }),
    main.getByText(LANDING_EXAMPLE, { exact: true }),
    links.nth(1),
    main.getByText(LANDING_READ_ONLY, { exact: true }),
  );
  for (const part of parts) await expect(part).toHaveCount(1);
  return parts;
}

test("'/' is the landing page: the name and tagline, what it is, the four agents, the example and the read-only line, in order", async ({ page, baseURL }, info) => {
  const requests = logRequests(page);
  const response = await page.goto("/");
  expect(response?.status()).toBe(200);

  const parts = await landingParts(page);
  for (const part of parts) await expect(part).toBeVisible();
  for (let i = 1; i < parts.length; i += 1) expect(await comesBefore(parts[i - 1], parts[i]), `part ${i} follows part ${i - 1}`).toBe(true);
  // The four agents, and only they, are the page's h3s, one list item each;
  // a diamond stands on the two steps that can pause, and only on them.
  await expect(page.getByRole("heading", { level: 3 })).toHaveText(LANDING_AGENTS.map(([name]) => name));
  const steps = page.getByRole("main").locator("ol > li");
  await expect(steps).toHaveCount(4);
  expect(await steps.evaluateAll((items) => items.map((item) => item.querySelectorAll("[data-checkpoint]").length))).toEqual([1, 1, 0, 0]);

  await expect(page.locator("input, textarea, form")).toHaveCount(0);
  expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/upload/i);
  // The pauses ask the person running it: the copy never addresses the visitor.
  expect(await page.getByRole("main").innerText()).not.toMatch(/\byou(r|rs)?\b/i);
  await expectNoHorizontalOverflow(page);

  await page.waitForLoadState("networkidle");
  expectSameOriginOnly(requests, baseURL);
  saveRequestLog(requests, info, "home");
  await shot(page, info, "home");
});

// On a wide screen the column sets the measure; a phone's lines are short by
// themselves, and the same limit holds there.
test("the landing page's paragraphs keep to a reading width: no line runs past 80 characters", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const main = page.getByRole("main");
  const texts = [LANDING_LEAD, ...LANDING_AGENTS.map(([, text]) => text), LANDING_EXAMPLE, LANDING_READ_ONLY];
  for (const text of texts) {
    const stats = await lineStats(main.getByText(text, { exact: true }));
    expect.soft(stats.lines, `${text.slice(0, 30)}: wraps`).toBeGreaterThan(1);
    expect.soft(stats.longest, `${text.slice(0, 30)}: longest line`).toBeLessThanOrEqual(80);
  }
});

// Two links to the analysis, with the same text (owner ruling R2): the one
// under the lead spares a phone visitor the scroll past the four agents; the
// one in the example's card sits beside the file it opens.
test("the example names its file and its size, and exactly two links lead to the analysis", async ({ page }) => {
  await page.goto("/");
  // Exactly two links to the analysis on the whole page, both in <main>.
  await expect(page.locator(`a[href="${ANALYSIS}"]`)).toHaveCount(2);
  const links = page.getByRole("main").getByRole("link", { name: EXAMPLE_LINK, exact: true });
  await expect(links).toHaveCount(2);
  for (const link of await links.all()) {
    await expect(link).toHaveAttribute("href", ANALYSIS);
    expect(await link.evaluate((a) => Math.round(a.getBoundingClientRect().height)), "link tap target").toBeGreaterThanOrEqual(44);
  }
  // The second sits in the example's card, beside the file's name and its
  // original size, read from the snapshot; the first is in no card.
  // (`has` takes a locator relative to the item, so not `links`, which starts at <main>.)
  const item = page.getByRole("main").getByRole("listitem").filter({ has: page.getByRole("link", { name: EXAMPLE_LINK, exact: true }) });
  await expect(item).toHaveCount(1);
  await expect(item.getByRole("link")).toHaveCount(1);
  expect(await comesBefore(links.nth(0), item), "the first link comes before the card").toBe(true);
  await expect(item.getByText(FIXTURE.filename, { exact: true })).toBeVisible();
  await expect(item.getByText(exampleCounts(12, 3), { exact: true })).toBeVisible();
});

for (const [where, index] of [["under the lead", 0], ["in the example", 1]] as const) {
  test(`the link ${where} is a plain one: a full page load of the analysis, no client-side (RSC) navigation`, async ({ page }) => {
    const requests = logRequests(page);
    await page.goto("/");
    const links = page.getByRole("main").locator(`a[href="${ANALYSIS}"]`);
    await expect(links).toHaveCount(2);
    await links.nth(index).click();
    await expect(page).toHaveURL(ANALYSIS);
    await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
    const documents = requests.filter((r) => r.resourceType === "document" && r.frame === "main").map((r) => new URL(r.url).pathname);
    expect(documents).toEqual(["/", ANALYSIS]);
    expect(requests.filter((r) => new URL(r.url).searchParams.has("_rsc")).map((r) => r.url)).toEqual([]);
  });
}

test.describe("the prerendered HTML (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("holds the whole landing page, with nothing hiding it", async ({ page }, info) => {
    await page.goto("/");
    const parts = await landingParts(page);
    for (const part of parts) await expect(part).toBeVisible();
    await expectTextVisible(page);
    await expectNoHorizontalOverflow(page);
    await shot(page, info, "home-js-off");
  });
});
