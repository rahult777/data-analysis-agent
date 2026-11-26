// The desktop layout in local mode (M3a.2; owner rulings Q8, R2, R3 and R4),
// through the components the public page shares, route-mocked (e2e/mockApi.ts)
// with the public snapshot fixture's analysis and its two charts. From lg the
// results keep to a 32.5rem (520 px) spine centred on the page; the chart grid
// takes 896 px below xl and 1152 px from xl (the charts' media 224, then
// 320 px); the report's code blocks take 896 px; the question box and an
// answer, its code included, stay in the spine (R4). The loading skeleton and
// the error box keep to the spine too (R3). Run by the desktop project only,
// at 1180 and 1440 px.

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import type { AnalysisResponse } from "../lib/types";
import { ANALYSIS_ID, MOCK_API_URL, MockApi, openAsOwner, statusBody } from "./mockApi";

test.use({ contextOptions: { reducedMotion: "reduce" } });

const SNAPSHOT_FIXTURE = path.join(__dirname, "fixtures", "snapshot");
const FIXTURE_ID = "00000000-0000-4000-a000-000000000001";
const PNG = `${FIXTURE_ID}_histogram_fixture_value.png`;
const HTML = `${FIXTURE_ID}_scatter_fixture_x_fixture_y.html`;
const ANALYSIS: AnalysisResponse = {
  ...(JSON.parse(readFileSync(path.join(SNAPSHOT_FIXTURE, "analyses", `${FIXTURE_ID}.json`), "utf8")) as AnalysisResponse),
  id: ANALYSIS_ID,
  status: "complete",
  created_at: "2026-11-24T12:00:00+00:00",
  profile_report: null,
};
const ANSWER = {
  answer: "North has the highest mean revenue in the cleaned data.",
  pandas_code: 'by_region = df.groupby("region")["revenue"].agg(["mean", "median", "count"]).round(2)\nby_region.sort_values("mean", ascending=False)',
};
const RESULT_URL = `${MOCK_API_URL}/api/analysis/${ANALYSIS_ID}`;

const WIDTHS = [
  { width: 1180, height: 900, grid: 896, media: 224 },
  { width: 1440, height: 900, grid: 1152, media: 320 },
] as const;

let api: MockApi | null = null;

test.beforeEach(async ({ page }, info) => {
  api = null;
  test.skip(info.project.name !== "desktop-1280", "the desktop project only, at its own widths");
  api = new MockApi(page);
  await api.install();
  api.setStatus(statusBody("complete"));
});

test.afterEach(() => {
  if (api !== null) expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

function mock(): MockApi {
  if (api === null) throw new Error("The mock API is not installed.");
  return api;
}

interface Box {
  x: number;
  right: number;
  width: number;
  centre: number;
}

function near(value: number, target: number): boolean {
  return Math.abs(value - target) <= 1;
}

// The column widens once the analysis is complete (a 500 ms max-width
// transition, AnalysisPageClient.tsx): wait for it.
async function columnSettled(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() => document.querySelector("main > div")?.getBoundingClientRect().width)).toBe(896);
}

async function box(page: Page, selector: string): Promise<Box> {
  return page.locator(selector).first().evaluate((element) => {
    const r = element.getBoundingClientRect();
    return { x: r.x, right: r.right, width: r.width, centre: r.x + r.width / 2 };
  });
}

for (const { width, height, grid, media } of WIDTHS) {
  test(`at ${width} px the results keep to the spine with the question box and an answer in it; the grid is ${grid} px with ${media} px charts, the report's code 896 px`, async ({ page }) => {
    mock().setAnalysis(ANALYSIS);
    mock().setChart(PNG, readFileSync(path.join(SNAPSHOT_FIXTURE, "charts", PNG)), "image/png");
    mock().setChart(HTML, readFileSync(path.join(SNAPSHOT_FIXTURE, "charts", HTML)), "text/html; charset=utf-8");
    mock().setQuestionAnswer(ANSWER);
    await page.setViewportSize({ width, height });
    await openAsOwner(page);
    const triggers = page.locator('[data-slot="accordion-trigger"]');
    await expect(triggers).toHaveCount(3);
    for (const trigger of await triggers.all()) {
      if ((await trigger.getAttribute("aria-expanded")) !== "true") await trigger.click();
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
    }
    const input = page.getByLabel("Ask a question about this dataset");
    await input.fill("Which region has the highest mean revenue?");
    await page.getByRole("button", { name: "Submit question" }).click();
    await expect(page.getByText(ANSWER.answer)).toBeVisible();
    for (const element of await page.locator("img, iframe").all()) await element.scrollIntoViewIfNeeded();
    await expect(page.locator("[data-chart-placeholder]")).toHaveCount(0);
    await page.mouse.move(0, 0);
    await columnSettled(page);

    const middle = width / 2;
    const spine = await page.getByRole("heading", { name: "Analysis complete" }).evaluate((heading) => {
      const r = (heading.closest("header")?.parentElement ?? heading).getBoundingClientRect();
      return { x: r.x, right: r.right, width: r.width, centre: r.x + r.width / 2 };
    });
    expect.soft(spine.width, "the spine").toBe(520);
    expect.soft(near(spine.centre, middle), `the spine is centred (${spine.centre})`).toBe(true);
    const gridBox = await page.locator('[id^="chart-"]').first().evaluate((card) => {
      const r = (card.parentElement as HTMLElement).getBoundingClientRect();
      return { width: r.width, centre: r.x + r.width / 2 };
    });
    expect.soft(gridBox.width, "the chart grid").toBe(grid);
    expect.soft(near(gridBox.centre, middle), "the chart grid is centred").toBe(true);
    const mediaHeights = await page.locator('[id^="chart-"]').evaluateAll((cards) =>
      cards.map((card) => Math.round((card.querySelector("img, iframe")?.parentElement ?? card).getBoundingClientRect().height)),
    );
    expect.soft(mediaHeights, "both charts' media boxes").toEqual([media, media]);
    // The report's code (the Technical Detail panel) leaves the spine; the
    // answer's code stays in it.
    const report = await box(page, '[data-slot="accordion-content"] pre >> xpath=..');
    expect.soft(report.width, "the report's code block").toBe(896);
    expect.soft(near(report.centre, middle), "the report's code block is centred").toBe(true);
    const question = await page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Ask a question", exact: true }) })
      .evaluate((section) => {
        const r = section.getBoundingClientRect();
        const pre = section.querySelector("pre")?.parentElement?.getBoundingClientRect();
        return { x: r.x, right: r.right, codeX: pre?.x ?? null, codeRight: pre?.right ?? null };
      });
    expect.soft(question.x >= spine.x - 1 && question.right <= spine.right + 1, "the question box is in the spine").toBe(true);
    expect.soft(question.codeX !== null && question.codeRight !== null && question.codeX >= spine.x - 1 && question.codeRight <= spine.right + 1, "the answer's code is in the spine").toBe(true);
    expect.soft(await page.evaluate(() => document.documentElement.scrollWidth), "no sideways overflow").toBe(width);
  });

  test(`at ${width} px the loading skeleton and the error box keep to the spine`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    // The result never arrives: the skeleton stays up. (Routed after the mock,
    // so this handler answers this one URL.)
    await page.route(RESULT_URL, () => undefined);
    await openAsOwner(page);
    const skeleton = page.getByLabel("Loading results");
    await expect(skeleton).toBeVisible();
    await columnSettled(page);
    const s = await skeleton.evaluate((root) => {
      const r = root.getBoundingClientRect();
      const placeholders = Array.from(root.querySelectorAll(":scope > .grid > div"));
      const g = placeholders[0]?.parentElement?.getBoundingClientRect();
      return {
        width: r.width,
        centre: r.x + r.width / 2,
        grid: g ? g.width : null,
        gridCentre: g ? g.x + g.width / 2 : null,
        heights: placeholders.map((p) => Math.round(p.getBoundingClientRect().height)),
      };
    });
    expect.soft(s.width, "the skeleton's root").toBe(520);
    expect.soft(near(s.centre, width / 2), "the skeleton is centred").toBe(true);
    expect.soft(s.grid, "the skeleton's chart placeholders take the grid's width").toBe(grid);
    expect.soft(s.gridCentre !== null && near(s.gridCentre, width / 2), "and are centred").toBe(true);
    expect.soft(s.heights, "the placeholders are as high as the charts").toEqual([media, media]);

    await page.goto("about:blank");
    await page.unroute(RESULT_URL);
    // The result's request fails: the error box.
    await page.route(RESULT_URL, (route) => route.abort("failed"));
    await openAsOwner(page);
    const alert = page.getByRole("alert").filter({ hasText: "Something went wrong on our end" });
    await expect(alert).toBeVisible();
    await columnSettled(page);
    const e = await alert.evaluate((element) => {
      const r = element.getBoundingClientRect();
      return { width: r.width, centre: r.x + r.width / 2 };
    });
    expect.soft(e.width, "the error box").toBe(520);
    expect.soft(near(e.centre, width / 2), "the error box is centred").toBe(true);
  });
}
