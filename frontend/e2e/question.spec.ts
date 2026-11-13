// The question box in local mode (M2b.4c; owner ruling Q15). Its copy says
// what the Explainer does with a question: it writes pandas code, runs it on
// the cleaned data and describes the result, and the code that ran is shown
// with each answer (backend/agents/explainer.py answer_question). A question
// is cut at 2,000 characters, the box's maxlength, and the owner's view says
// so in a hint tied to the box; a visitor's read-only box keeps its note.
// Route-mocked (e2e/mockApi.ts). Runs at both viewport widths.

import { expect, test, type Locator, type Page } from "@playwright/test";

import type { AnalysisResponse } from "../lib/types";
import { shot } from "../e2e-public/helpers";
import { ANALYSIS_ID, MockApi, openAsOwner, openAsVisitor, statusBody } from "./mockApi";

const DESCRIPTION =
  "Ask about the cleaned data. The Explainer writes pandas code for your question, runs it on the data and describes the result. The code that ran is shown with each answer: check it before relying on the answer.";
const HINT = "Questions can be up to 2,000 characters.";
// The copy it replaces, which claimed more than the code does.
const OLD_COPY = "every answer is computed with pandas";
const INPUT = "Ask a question about this dataset";

const ANALYSIS: AnalysisResponse = {
  id: ANALYSIS_ID,
  filename: "question.csv",
  status: "complete",
  created_at: "2026-11-12T12:00:00+00:00",
  row_count: 10,
  column_count: 2,
  data_quality_score: 0.9,
  profile_report: null,
  cleaning_report: null,
  cleaning_decisions: null,
  analysis_report: null,
  insight_report: null,
  executive_summary: null,
  chart_paths: [],
};

function questionBox(page: Page): Locator {
  return page.locator("section").filter({ has: page.getByRole("heading", { name: "Ask a question", exact: true }) });
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

test("the owner's box says what the Explainer does with a question, and holds 2,000 characters with a hint that says so", async ({ page }, info) => {
  await openAsOwner(page);
  const box = questionBox(page);
  // Soft, so one run names each missing piece.
  await expect.soft(box.getByText(DESCRIPTION, { exact: true }), "the copy").toBeVisible();
  await expect.soft(page.getByText(OLD_COPY), "the old copy is gone").toHaveCount(0);
  const input = page.getByLabel(INPUT);
  await expect(input).toBeEnabled();
  await expect.soft(input, "the limit").toHaveAttribute("maxlength", "2000");
  const hint = box.getByText(HINT, { exact: true });
  await expect(hint).toBeVisible();
  const id = await hint.getAttribute("id");
  expect(id, "the hint has an id").toBeTruthy();
  await expect(input).toHaveAttribute("aria-describedby", id ?? "");
  await expect(input).toHaveAccessibleDescription(HINT);
  await shot(page, info, "local-question-owner");
});

test("a visitor's read-only box has the same copy and limit, its note, and no hint", async ({ page }, info) => {
  await openAsVisitor(page);
  const box = questionBox(page);
  await expect.soft(box.getByText(DESCRIPTION, { exact: true }), "the copy").toBeVisible();
  const input = page.getByLabel(INPUT);
  await expect(input).toBeDisabled();
  await expect.soft(input, "the limit").toHaveAttribute("maxlength", "2000");
  await expect.soft(box.getByText(HINT, { exact: true }), "no hint for a visitor").toHaveCount(0);
  await expect.soft(input, "the read-only note describes the box").toHaveAttribute("aria-describedby", "question-readonly-note");
  await shot(page, info, "local-question-visitor");
});
