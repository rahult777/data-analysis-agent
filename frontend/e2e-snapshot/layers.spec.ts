// DoD item 14 on the real data: the intelligence layers render from the
// committed snapshot. The domain hypothesis is stated; each finding in the
// narrative carries its confidence label; the narrative leads with its finding
// and builds to the synthesis and the open questions (progressive revelation);
// and the executive, analyst and technical layers are all on the page. The
// header, the chart labels in the narrative and the note are M2b.3b. Every
// test runs at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, shot } from "../e2e-public/helpers";
import { ANALYSIS, REAL_ID } from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;
const INSIGHT = ANALYSIS.insight_report;
const TECHNICAL = INSIGHT.technical_layer;
// InsightReport.tsx splits the narrative into paragraphs the same way.
const PARAGRAPHS = (INSIGHT.analyst_layer.narrative ?? "").split(/\n\n+/).filter(Boolean);

function confidenceLabels(text: string): string[] {
  return Array.from(text.matchAll(/Confidence: (High|Moderate|Low)\b/g), (match) => match[1]);
}

test("the intelligence layers render from the real data: domain hypothesis, confidence labels, a lead-first narrative and all three layers", async ({ page }, info) => {
  await page.goto(PAGE);

  // Executive layer: five bullets, each with its finding, context and action.
  const bullets = ANALYSIS.executive_summary.bullets;
  expect(bullets).toHaveLength(5);
  const executive = page.locator("section").filter({ has: page.getByRole("heading", { name: "Executive Summary" }) });
  await expect(executive.locator("li")).toHaveCount(5);
  for (const bullet of bullets) {
    for (const text of [bullet.finding, bullet.context, bullet.recommended_action]) {
      await expect(executive.getByText(text ?? "", { exact: true })).toBeVisible();
    }
  }

  // Analyst layer: every paragraph of the narrative, in order.
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  const analyst = page.getByRole("region", { name: /Analyst Report/ });
  await expect(analyst.getByText(PARAGRAPHS[0], { exact: true })).toBeVisible();
  const paragraphs = (await analyst.locator("p").allTextContents()).filter((text) => PARAGRAPHS.includes(text));
  expect(paragraphs).toHaveLength(16);
  expect(paragraphs).toEqual(PARAGRAPHS);

  // Lead first: the narrative opens with the executive lead's finding (the
  // 37.8% of revenue values filled in), then builds to the synthesis and
  // ends with the six open questions.
  expect(paragraphs[0]).toMatch(/^Every revenue aggregate in this dataset is analytically compromised/);
  expect(paragraphs[0]).toContain("37.8%");
  expect(bullets[0].finding).toContain("37.8%");
  const synthesis = paragraphs.findIndex((text) => text.startsWith("Synthesis observation:"));
  const openQuestions = paragraphs.findIndex((text) => text.startsWith("Open Questions:"));
  expect(synthesis).toBeGreaterThan(0);
  expect(openQuestions).toBe(synthesis + 1);
  expect(paragraphs.slice(openQuestions + 1).map((text) => text.split(":")[0])).toEqual(["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]);

  // Calibrated confidence: the findings carry their labels, as written.
  expect(confidenceLabels(paragraphs.join("\n\n"))).toEqual(["High", "Low", "Low", "High", "Low", "Moderate", "Moderate", "Low"]);
  // The narrative reasons in the Profiler's domain.
  expect(paragraphs.filter((text) => /\bretail\b/i.test(text)).length).toBeGreaterThan(0);

  // Open questions: all six.
  await page.getByRole("button", { name: /Open Questions/ }).click();
  const questions = page.getByRole("region", { name: /Open Questions/ });
  expect(INSIGHT.open_questions).toHaveLength(6);
  await expect(questions.locator("li")).toHaveCount(6);
  for (const question of INSIGHT.open_questions) {
    await expect(questions.getByText(question.question ?? "", { exact: true })).toBeVisible();
  }

  // Technical layer: every cleaning decision, the methodology, every code
  // block and the callouts.
  await page.getByRole("button", { name: /Technical Detail/ }).click();
  const technical = page.getByRole("region", { name: /Technical Detail/ });
  expect(ANALYSIS.cleaning_decisions).toHaveLength(16);
  await expect(technical.locator("li")).toHaveCount(16);
  for (const decision of ANALYSIS.cleaning_decisions) {
    await expect(technical.getByText(decision.action, { exact: true })).toBeVisible();
    await expect(technical.getByText(decision.reason, { exact: true })).toBeVisible();
  }
  // The domain hypothesis, stated in the system's own question at a pause.
  await expect(technical.getByText("The Profiler's domain hypothesis is 'Retail and E-commerce'.")).toBeVisible();
  await expect(technical.getByText(TECHNICAL.statistical_methodology ?? "", { exact: true })).toBeVisible();
  expect(TECHNICAL.code_blocks).toHaveLength(26);
  expect(await technical.locator("pre code").allTextContents()).toEqual(TECHNICAL.code_blocks);
  for (const text of [TECHNICAL.limitations, TECHNICAL.sophistication_suggestions, TECHNICAL.self_evaluation_notes, TECHNICAL.lead_override_note]) {
    await expect(technical.getByText(text ?? "", { exact: true })).toBeVisible();
  }

  await expectNoHorizontalOverflow(page);
  await shot(page, info, "snapshot-layers");
});
