// The public analysis page without JavaScript, and what makes it readable
// there (M2b.4b): no entry animation in the public build (F1), the three
// layers in the static HTML and shown by a <noscript> style rule (F2), and a
// reading width for long text (F6). The whole-page check (expectTextVisible)
// requires every text displayed at full opacity on each public page. Without
// JavaScript a chart image is drawn, no loading placeholder pulses, and the
// interactive chart's card says it needs JavaScript (M2b.4c, F3). Every test
// runs at 320 px and at 1280 px.

import { expect, test, type Locator, type Page } from "@playwright/test";

import { chartCardId, FIXTURE, FIXTURE_ID, HTML_CHART, PNG_CHART } from "./fixture";
import { expectNoHorizontalOverflow, expectReadingWidth, expectTextVisible, shot } from "./helpers";
import { CHART_NOJS_LINE } from "./site";

const PAGE = `/analysis/${FIXTURE_ID}`;
const PANELS = '[data-slot="accordion-content"]';
const NARRATIVE = FIXTURE.insight_report.analyst_layer.narrative ?? "";
const QUESTION = FIXTURE.insight_report.open_questions[0].question ?? "";
const WHY = FIXTURE.insight_report.open_questions[0].why_unanswerable ?? "";
const REASON = FIXTURE.cleaning_decisions[0].reason;
const METHODOLOGY = FIXTURE.insight_report.technical_layer.statistical_methodology ?? "";
const LIMITATIONS = FIXTURE.insight_report.technical_layer.limitations ?? "";

// The elements that faded in before M2b.4b: the results header, each
// executive bullet and each chart card.
async function entryStyles(page: Page): Promise<{ count: number; faded: string[] }> {
  return page.evaluate(() => {
    const heading = Array.from(document.querySelectorAll("h2")).find((h2) => h2.textContent === "Analysis complete");
    const executive = Array.from(document.querySelectorAll("section")).find((section) => section.querySelector("h3")?.textContent === "Executive Summary");
    const elements = [heading?.closest("header"), ...Array.from(executive?.querySelectorAll("ol > li") ?? []), ...Array.from(document.querySelectorAll('[id^="chart-"]'))];
    const faded: string[] = [];
    for (const element of elements) {
      if (!element) {
        faded.push("missing element");
        continue;
      }
      const style = getComputedStyle(element);
      if (style.opacity !== "1" || style.transform !== "none") faded.push(`<${element.tagName.toLowerCase()}> opacity ${style.opacity}, transform ${style.transform}`);
    }
    return { count: elements.length, faded };
  });
}

test("the served HTML holds no entry animation's start: nothing at opacity 0", async ({ request }) => {
  const html = await (await request.get(PAGE)).text();
  expect(html).toContain("Analysis complete");
  expect(html.split("opacity:0").length - 1, "inline opacity:0 in the served HTML").toBe(0);
  expect(html.split("translateY(").length - 1, "inline translateY in the served HTML").toBe(0);
});

test("with JavaScript on, the three layers are in the page, hidden until found, and still open", async ({ page }) => {
  await page.goto(PAGE);
  const panels = page.locator(PANELS);
  await expect(panels).toHaveCount(3);
  // Base UI sets hidden="until-found" once the page has hydrated.
  await expect(page.locator(`${PANELS}[hidden="until-found"]`)).toHaveCount(3);
  const narrative = page.getByText(NARRATIVE, { exact: true });
  await expect(narrative, "in the page while its panel is closed").toHaveCount(1);
  await expect(narrative).toBeHidden();
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await expect(narrative).toBeVisible();
  await expect(page.locator(`${PANELS}[hidden]`), "the other two stay closed").toHaveCount(2);
});

// One measure for every block of long text (owner rulings B6 and R4): the
// note, the executive bullets and the narrative, and the open questions, the
// cleaning decisions, the methodology and the callouts.
test("long text keeps to one reading width: the note, the bullets, the narrative, the open questions, the cleaning decisions, the methodology and the callouts", async ({ page }) => {
  await page.goto(PAGE);
  for (const name of [/Analyst Report/, /Open Questions/, /Technical Detail/]) await page.getByRole("button", { name }).click();
  const note = page.getByRole("region", { name: "About this example", exact: true });
  const bullets = page.locator("section").filter({ has: page.getByRole("heading", { name: "Executive Summary" }) }).locator("ol");
  const narrative = page.getByText(NARRATIVE, { exact: true });
  const questions = page.getByRole("region", { name: /Open Questions/ });
  const technical = page.getByRole("region", { name: /Technical Detail/ });
  const methodology = technical.getByText(METHODOLOGY, { exact: true });
  const limitations = technical.getByText(LIMITATIONS, { exact: true });
  // Each block, and a text in it as wide as the block's measure.
  const blocks: ReadonlyArray<readonly [string, Locator, Locator]> = [
    ["note", note, note.locator("p")],
    ["bullets", bullets, bullets.locator("li p").first()],
    ["narrative", narrative, narrative],
    ["open questions", questions.locator("ol"), questions.getByText(WHY, { exact: true })],
    ["cleaning decisions", technical.locator("ul"), technical.getByText(REASON, { exact: true })],
    ["methodology", methodology, methodology],
    ["callouts", limitations.locator(".."), limitations],
  ];
  const column = await page.getByRole("main").locator("> div").evaluate((div) => div.getBoundingClientRect().width);
  const wide = (page.viewportSize()?.width ?? 0) >= 1280;
  for (const [name, block, text] of blocks) await expectReadingWidth(name, block, text, column, wide);
  await expectNoHorizontalOverflow(page);
});

test.describe("the prerendered HTML (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("the results header, the bullets and the chart cards are drawn at once: no fade, no offset", async ({ page }) => {
    await page.goto(PAGE);
    const { count, faded } = await entryStyles(page);
    // The header, the fixture's two bullets and its two chart cards.
    expect(count).toBe(5);
    expect(faded).toEqual([]);
  });

  test("the three layers are shown, with their content", async ({ page }, info) => {
    await page.goto(PAGE);
    const panels = page.locator(PANELS);
    await expect(panels).toHaveCount(3);
    expect(await panels.evaluateAll((elements) => elements.map((panel) => getComputedStyle(panel).display))).toEqual(["block", "block", "block"]);
    for (const text of [NARRATIVE, QUESTION, REASON]) await expect(page.getByText(text, { exact: true })).toBeVisible();
    // The interactive matrix's table and the code block are there too.
    await expect(panels.nth(0).locator("table")).toBeVisible();
    await expect(panels.nth(2).locator("pre code")).toBeVisible();
    // The <noscript> rule takes no room of its own: the note and the results
    // header stay one gap of the page's column apart, as with JavaScript on.
    const spacing = await page.evaluate(() => {
      const note = document.querySelector('section[aria-labelledby="about-this-example"]');
      const heading = Array.from(document.querySelectorAll("h2")).find((h2) => h2.textContent === "Analysis complete");
      const header = heading?.closest("header");
      const column = document.querySelector("main > div");
      if (!note || !header || !column) return null;
      return { between: Math.round(header.getBoundingClientRect().top - note.getBoundingClientRect().bottom), gap: Math.round(Number.parseFloat(getComputedStyle(column).rowGap)) };
    });
    expect(spacing).not.toBeNull();
    expect(spacing?.gap).toBeGreaterThan(0);
    expect(spacing?.between, "one gap between the note and the results header").toBe(spacing?.gap);
    await expectNoHorizontalOverflow(page);
    await shot(page, info, "analysis-js-off");
  });

  test("the chart cards: the image is drawn, nothing pulses, and the interactive chart says it needs JavaScript", async ({ page }, info) => {
    await page.goto(PAGE);
    const img = page.locator(`#${chartCardId(PNG_CHART)} img`);
    await expect(img, "the image, without JavaScript").toHaveCount(1);
    await img.scrollIntoViewIfNeeded();
    await expect.poll(() => img.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth)).toBe(48);
    const html = page.locator(`#${chartCardId(HTML_CHART)}`);
    await expect(html.getByText(CHART_NOJS_LINE, { exact: true })).toBeVisible();
    await expect(html.locator("iframe")).toHaveCount(0);
    const pulsing = await page.locator(".animate-pulse").evaluateAll((elements) => elements.filter((element) => getComputedStyle(element).display !== "none").length);
    expect(pulsing, "loading placeholders shown").toBe(0);
    await shot(page, info, "charts-js-off");
  });

  for (const [name, url] of [["the analysis page", PAGE], ["'/'", "/"], ["the 404 page", "/no-such-page"]] as const) {
    test(`every text on ${name} is displayed at full opacity`, async ({ page }) => {
      await page.goto(url);
      await expectTextVisible(page);
    });
  }
});
