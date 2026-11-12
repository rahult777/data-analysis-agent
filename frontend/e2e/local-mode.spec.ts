// What M2b.4b changed for the public build only stays as it was in local mode:
// local pages carry no site header, footer or skip link; the results still
// fade in; and a closed layer's content is not in the page until its panel is
// opened. The reading width belongs to the results view itself, so local mode
// has it too (owner ruling R5); the last test checks it. Route-mocked like the
// other local specs (e2e/mockApi.ts). Every test runs at 320 px and at 1280 px.

import { expect, test, type Locator } from "@playwright/test";

import { expectReadingWidth } from "../e2e-public/helpers";
import type { AnalysisResponse } from "../lib/types";
import { ANALYSIS_ID, MockApi, openAsVisitor, statusBody } from "./mockApi";

const NARRATIVE = "A local narrative paragraph, in the page only while its panel is open.";

const ANALYSIS: AnalysisResponse = {
  id: ANALYSIS_ID,
  filename: "local.csv",
  status: "complete",
  created_at: "2026-11-12T12:00:00+00:00",
  row_count: 12,
  column_count: 3,
  data_quality_score: 0.9,
  profile_report: null,
  cleaning_report: null,
  cleaning_decisions: null,
  analysis_report: null,
  insight_report: { analyst_layer: { narrative: NARRATIVE } },
  executive_summary: { bullets: [{ finding: "A local finding.", context: "Its context.", recommended_action: "Its action." }] },
  chart_paths: [],
};

// The same results with every block of long text the reading width covers.
const WHY = "Why the local data cannot answer the question.";
const REASON = "A local reason for the cleaning decision.";
const METHODOLOGY = "A local methodology note.";
const LIMITATIONS = "A local limitation.";
const FULL: AnalysisResponse = {
  ...ANALYSIS,
  cleaning_decisions: [{ column_name: "value", issue: "A local issue.", action: "A local action.", reason: REASON }],
  insight_report: {
    analyst_layer: { narrative: NARRATIVE },
    open_questions: [{ question: "A local open question?", why_unanswerable: WHY, what_data_would_answer: "A local answer." }],
    technical_layer: { statistical_methodology: METHODOLOGY, limitations: LIMITATIONS },
  },
};

declare global {
  interface Window {
    __entryOpacity?: string[];
  }
}

let api: MockApi;

test.beforeEach(async ({ page }) => {
  api = new MockApi(page);
  await api.install();
  api.setStatus(statusBody("complete"));
  api.setAnalysis(ANALYSIS);
});

test.afterEach(() => {
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

test("local pages carry no site header, footer or skip link", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Omnalynt", exact: true })).toBeVisible();
  for (const absent of [page.getByRole("banner"), page.getByRole("contentinfo"), page.locator('a[href="#main"]'), page.locator("body > header, body > footer")]) {
    await expect(absent).toHaveCount(0);
  }
  await openAsVisitor(page);
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
  for (const absent of [page.getByRole("banner"), page.getByRole("contentinfo"), page.locator('a[href="#main"]'), page.locator("body > header, body > footer")]) {
    await expect(absent).toHaveCount(0);
  }
});

test("the results still fade in: the results header enters the page transparent", async ({ page }) => {
  // Records the inline opacity each results header has when it enters the DOM.
  await page.addInitScript(() => {
    window.__entryOpacity = [];
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of Array.from(record.addedNodes)) {
          if (!(node instanceof HTMLElement)) continue;
          const headers = node.matches("header") ? [node] : Array.from(node.querySelectorAll<HTMLElement>("header"));
          for (const header of headers) {
            if (header.querySelector("h2")?.textContent === "Analysis complete") window.__entryOpacity?.push(header.style.opacity);
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
  await openAsVisitor(page);
  const header = page.locator("header").filter({ has: page.getByRole("heading", { name: "Analysis complete" }) });
  await expect(header).toBeVisible();
  expect(await page.evaluate(() => window.__entryOpacity)).toEqual(["0"]);
  // And it ends fully drawn.
  await expect.poll(() => header.evaluate((element) => getComputedStyle(element).opacity)).toBe("1");
});

test("a closed layer's content is not in the page until its panel is opened", async ({ page }) => {
  await openAsVisitor(page);
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
  await expect(page.locator('[data-slot="accordion-content"]')).toHaveCount(0);
  await expect(page.getByText(NARRATIVE, { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await expect(page.getByText(NARRATIVE, { exact: true })).toBeVisible();
});

test("the results keep the public build's reading width: the bullets, the narrative, the open questions, the cleaning decisions, the methodology and the callouts", async ({ page }) => {
  api.setAnalysis(FULL);
  await openAsVisitor(page);
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
  for (const name of [/Analyst Report/, /Open Questions/, /Technical Detail/]) await page.getByRole("button", { name }).click();
  const wide = (page.viewportSize()?.width ?? 0) >= 1280;
  // The column widens when the results arrive (a 500 ms transition): wait for it.
  const columnBox = page.getByRole("main").locator("> div");
  await expect.poll(() => columnBox.evaluate((div) => div.getBoundingClientRect().width)).toBe(wide ? 896 : 272);
  const column = await columnBox.evaluate((div) => div.getBoundingClientRect().width);
  const bullets = page.locator("section").filter({ has: page.getByRole("heading", { name: "Executive Summary" }) }).locator("ol");
  const narrative = page.getByText(NARRATIVE, { exact: true });
  const why = page.getByText(WHY, { exact: true });
  const reason = page.getByText(REASON, { exact: true });
  const methodology = page.getByText(METHODOLOGY, { exact: true });
  const limitations = page.getByText(LIMITATIONS, { exact: true });
  // Each block, and a text in it as wide as the block's measure. Under next
  // dev the panels have no accessible name (errors.md 2026-10-18), so each
  // block is found by its text.
  const blocks: ReadonlyArray<readonly [string, Locator, Locator]> = [
    ["bullets", bullets, bullets.locator("li p").first()],
    ["narrative", narrative, narrative],
    ["open questions", page.locator("ol").filter({ has: why }), why],
    ["cleaning decisions", page.locator("ul").filter({ has: reason }), reason],
    ["methodology", methodology, methodology],
    ["callouts", limitations.locator(".."), limitations],
  ];
  for (const [name, block, text] of blocks) await expectReadingWidth(name, block, text, column, wide);
});
