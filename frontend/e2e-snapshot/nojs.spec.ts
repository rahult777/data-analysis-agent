// The real analysis page without JavaScript, and its reading width (M2b.4b).
// No entry animation in the public build (F1): nothing in the served HTML
// starts at opacity 0. The three layers are in the static HTML and a
// <noscript> style rule shows them (F2). Every text on the page is displayed
// at full opacity. On a wide screen the note, the executive bullets and the
// narrative (F6), and the open questions, the cleaning decisions, the
// methodology and the callouts (owner ruling R4), keep to one reading width.
// The chart cards' loading placeholders stay up without JavaScript: M2b.4c
// (F3). Every test runs at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, expectTextVisible, lineStats, shot } from "../e2e-public/helpers";
import { ANALYSIS, KEPT_CHARTS, NOTE, REAL_ID } from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;
const PANELS = '[data-slot="accordion-content"]';
const INSIGHT = ANALYSIS.insight_report;
// InsightReport.tsx splits the narrative into paragraphs the same way.
const PARAGRAPHS = (INSIGHT.analyst_layer.narrative ?? "").split(/\n\n+/).filter(Boolean);

// The reading width (owner rulings B6 and R4): about 65 to 75 characters a
// line. The blocks are 29rem of text wide, which in the page's 14 px DM Sans
// gives median lines of 64 to 72 characters (120 to 138 before); a line of
// narrow letters and digits can hold more, 83 at most in this analysis. So
// the median line of each named block lies in MEDIAN, and no line runs past
// LONGEST.
const LONGEST = 85;
const MEDIAN = { min: 62, max: 76 };

test("the served HTML holds no entry animation's start: nothing at opacity 0", async ({ request }) => {
  const html = await (await request.get(PAGE)).text();
  expect(html).toContain("Analysis complete");
  expect(html.split("opacity:0").length - 1, "inline opacity:0 in the served HTML").toBe(0);
  expect(html.split("translateY(").length - 1, "inline translateY in the served HTML").toBe(0);
});

test("on a wide screen the note, the bullets, the narrative, the open questions, the cleaning decisions, the methodology and the callouts keep to a reading width; on a phone nothing changes", async ({ page }, info) => {
  await page.goto(PAGE);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  const analyst = page.getByRole("region", { name: /Analyst Report/ });
  const note = page.getByRole("region", { name: "About this example", exact: true }).locator("p");
  const executive = page.locator("section").filter({ has: page.getByRole("heading", { name: "Executive Summary" }) });
  const contexts = ANALYSIS.executive_summary.bullets.map((bullet) => executive.getByText(bullet.context ?? "", { exact: true }));
  // The first paragraph names no chart, so it renders as written.
  const firstParagraph = analyst.getByText(PARAGRAPHS[0], { exact: true });
  await expect(firstParagraph).toBeVisible();
  const narrative = analyst.locator("p").filter({ hasText: /\S/ });

  const wide = (page.viewportSize()?.width ?? 0) >= 1280;
  const noteStats = await lineStats(note);
  if (!wide) {
    // Owner ruling Q8: the note keeps its 13 lines at 320 px.
    expect(noteStats.lines, "the note's lines at 320 px").toBe(13);
    await expectNoHorizontalOverflow(page);
    return;
  }
  const named = { note: noteStats, "first bullet's context": await lineStats(contexts[0]), "first narrative paragraph": await lineStats(firstParagraph) };
  for (const [name, stats] of Object.entries(named)) {
    expect.soft(stats.longest, `${name}: longest line`).toBeLessThanOrEqual(LONGEST);
    expect.soft(stats.median, `${name}: median line`).toBeGreaterThanOrEqual(MEDIAN.min);
    expect.soft(stats.median, `${name}: median line`).toBeLessThanOrEqual(MEDIAN.max);
  }
  // Every bullet's texts and every narrative paragraph stay under the cap.
  const bulletTexts = executive.locator("ol > li p");
  await expect(bulletTexts).toHaveCount(15);
  for (const text of await bulletTexts.all()) expect.soft((await lineStats(text)).longest, "a bullet's longest line").toBeLessThanOrEqual(LONGEST);
  const paragraphs = (await narrative.all()).slice(0, PARAGRAPHS.length);
  expect(paragraphs).toHaveLength(16);
  for (const paragraph of paragraphs) expect.soft((await lineStats(paragraph)).longest, "a narrative paragraph's longest line").toBeLessThanOrEqual(LONGEST);

  // The same measure for the open questions, the cleaning decisions, the
  // methodology and the callouts (owner ruling R4): the first text of each
  // kind lies in the window, and no line of any of them runs past the cap.
  for (const name of [/Open Questions/, /Technical Detail/]) await page.getByRole("button", { name }).click();
  const questions = page.getByRole("region", { name: /Open Questions/ });
  const technical = page.getByRole("region", { name: /Technical Detail/ });
  const TECHNICAL = INSIGHT.technical_layer;
  const more = {
    "first open question's why": questions.getByText(INSIGHT.open_questions[0].why_unanswerable ?? "", { exact: true }),
    "first reason the Cleaner wrote": technical.getByText(ANALYSIS.cleaning_decisions[1].reason, { exact: true }),
    methodology: technical.getByText(TECHNICAL.statistical_methodology ?? "", { exact: true }),
    "limitations callout": technical.getByText(TECHNICAL.limitations ?? "", { exact: true }),
  };
  for (const [name, text] of Object.entries(more)) {
    const stats = await lineStats(text);
    expect.soft(stats.longest, `${name}: longest line`).toBeLessThanOrEqual(LONGEST);
    expect.soft(stats.median, `${name}: median line`).toBeGreaterThanOrEqual(MEDIAN.min);
    expect.soft(stats.median, `${name}: median line`).toBeLessThanOrEqual(MEDIAN.max);
  }
  const questionTexts = questions.locator("li p");
  await expect(questionTexts).toHaveCount(18);
  // The methodology and the four callouts: limitations, suggestions, self-evaluation, lead override.
  const longTexts = [TECHNICAL.statistical_methodology, TECHNICAL.limitations, TECHNICAL.sophistication_suggestions, TECHNICAL.self_evaluation_notes, TECHNICAL.lead_override_note].filter(
    (value): value is string => typeof value === "string" && value.trim() !== "",
  );
  expect(longTexts).toHaveLength(5);
  const texts = [...(await questionTexts.all()), ...(await technical.locator("ul > li").locator("p, span").all()), ...longTexts.map((value) => technical.getByText(value, { exact: true }))];
  for (const text of texts) expect.soft((await lineStats(text)).longest, "a line of the open questions, the decisions, the methodology or a callout").toBeLessThanOrEqual(LONGEST);
  await expectNoHorizontalOverflow(page);
  await shot(page, info, "snapshot-reading-width");
});

test.describe("the prerendered HTML (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("every text on the page is displayed at full opacity, and nothing has faded or moved", async ({ page }) => {
    await page.goto(PAGE);
    await expectTextVisible(page);
    const faded = await page.evaluate(() => {
      const heading = Array.from(document.querySelectorAll("h2")).find((h2) => h2.textContent === "Analysis complete");
      const executive = Array.from(document.querySelectorAll("section")).find((section) => section.querySelector("h3")?.textContent === "Executive Summary");
      const elements = [heading?.closest("header"), ...Array.from(executive?.querySelectorAll("ol > li") ?? []), ...Array.from(document.querySelectorAll('[id^="chart-"]'))];
      const found = elements.filter((element) => {
        if (!element) return true;
        const style = getComputedStyle(element);
        return style.opacity !== "1" || style.transform !== "none";
      });
      return { count: elements.length, faded: found.length };
    });
    // The header, the five bullets and the fourteen chart cards.
    expect(faded).toEqual({ count: 1 + 5 + KEPT_CHARTS.length, faded: 0 });
    expect(await page.locator("section[aria-labelledby='about-this-example'] p").textContent()).toBe(NOTE);
  });

  test("the three layers are shown in full: the narrative, the open questions and the technical detail", async ({ page }, info) => {
    await page.goto(PAGE);
    const panels = page.locator(PANELS);
    await expect(panels).toHaveCount(3);
    expect(await panels.evaluateAll((elements) => elements.map((panel) => getComputedStyle(panel).display))).toEqual(["block", "block", "block"]);
    const [analyst, questions, technical] = [panels.nth(0), panels.nth(1), panels.nth(2)];
    await expect(analyst.getByText(PARAGRAPHS[0], { exact: true })).toBeVisible();
    await expect(analyst.locator("table")).toBeVisible();
    expect(INSIGHT.open_questions).toHaveLength(6);
    await expect(questions.locator("li")).toHaveCount(6);
    await expect(questions.getByText(INSIGHT.open_questions[0].question ?? "", { exact: true })).toBeVisible();
    expect(ANALYSIS.cleaning_decisions).toHaveLength(16);
    await expect(technical.locator("li")).toHaveCount(16);
    for (const decision of ANALYSIS.cleaning_decisions) await expect(technical.getByText(decision.reason, { exact: true })).toBeVisible();
    await expect(technical.locator("pre code")).toHaveCount(26);
    await expectNoHorizontalOverflow(page);
    await shot(page, info, "snapshot-layers-js-off");
  });
});
