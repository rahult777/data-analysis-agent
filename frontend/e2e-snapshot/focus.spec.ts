// The keyboard focus indicator on the build Vercel deploys (M3a.2): a Tab walk
// through "/", the 404 and the analysis page with every panel open, at 320 and
// 1280 px. Every stop's indicator must change at least its 1 px perimeter by a
// contrast of 3:1 or more, on every side, with no ancestor cutting it
// (e2e-public/focus.ts), and no stop may be a chart's frame: a keyboard focus
// inside the sandboxed frame shows no ring, and plotly offers a keyboard
// nothing. Also every correlation-matrix cell, focused with the arrow keys,
// and a panel link's hover colour (1280).

import { expect, test, type Page } from "@playwright/test";

import { expectFocusVisible, expectKinds, matrixWalk, measureFocus, saveFocusReport, tabWalk, type FocusStop } from "../e2e-public/focus";
import { REAL_ID } from "./snapshot";

test.use({ contextOptions: { reducedMotion: "reduce" } });

const ANALYSIS = `/analysis/${REAL_ID}`;

// Every chart loaded (each scrolled into view: they are lazy), back at the top,
// the mouse parked.
async function settle(page: Page): Promise<void> {
  for (const media of await page.locator("img, iframe").all()) await media.scrollIntoViewIfNeeded();
  await expect(page.locator("[data-chart-placeholder]")).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.mouse.move(0, 0);
}

async function openEveryPanel(page: Page): Promise<void> {
  const triggers = page.locator('[data-slot="accordion-trigger"]');
  await expect(triggers).toHaveCount(3);
  for (const trigger of await triggers.all()) {
    if ((await trigger.getAttribute("aria-expanded")) !== "true") await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  }
}

async function walk(page: Page, first: FocusStop[] = []): Promise<FocusStop[]> {
  const { stops, frames, complete } = await tabWalk(page);
  // Soft, so one run also measures every stop.
  expect.soft(complete, "the walk came back round").toBe(true);
  expect.soft(frames, "no focus stop is a chart's frame").toBe(0);
  return [...first, ...stops];
}

test("every focus stop on the landing page shows a visible indicator", async ({ page }, info) => {
  await page.goto("/");
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "landing");
  expectKinds(stops, ["skip link", "header link", "page link", "footer link"], "landing");
  await expectFocusVisible(stops, info, "landing");
});

test("every focus stop on the 404 page shows a visible indicator", async ({ page }, info) => {
  await page.goto("/no-such-page");
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "notfound");
  expectKinds(stops, ["skip link", "header link", "page link", "footer link"], "notfound");
  await expectFocusVisible(stops, info, "notfound");
});

test("every focus stop on the analysis page, every panel open, shows a visible indicator; a chart card reached from the narrative too", async ({ page }, info) => {
  test.setTimeout(120_000);
  await page.goto(ANALYSIS);
  await openEveryPanel(page);
  await settle(page);
  // A chart card is a focus target, not a stop: Enter on the narrative's first
  // chart link moves the focus to it (a key down first, so the link's focus
  // counts as a keyboard focus).
  const link = page.locator('[data-slot="accordion-content"] p a').first();
  await page.keyboard.press("Shift");
  await link.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(":focus")).toHaveAttribute("id", /^chart-/);
  const card = await measureFocus(page);
  expect(card, "the chart card has the focus").not.toBeNull();
  const stops = await walk(page, card === null ? [] : [card]);
  saveFocusReport(stops, info, "analysis");
  expectKinds(
    stops,
    [
      "chart card",
      "skip link",
      "header link",
      "card expand button",
      "card full-size link",
      "accordion trigger",
      "narrative chart link",
      "panel link (heatmap)",
      "matrix cell",
      "chart pill link",
      "code copy button",
      "code scroller (pre)",
      "footer link",
    ],
    "analysis",
  );
  await expectFocusVisible(stops, info, "analysis");
});

test("every correlation-matrix cell, focused with the arrow keys, shows a visible indicator", async ({ page }, info) => {
  await page.goto(ANALYSIS);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await settle(page);
  const cells = await matrixWalk(page);
  saveFocusReport(cells, info, "matrix-demo");
  expect(cells, "the demo's matrix: 4 columns, 16 cells").toHaveLength(16);
  await expectFocusVisible(cells, info, "matrix-demo");
});

test("a panel's link takes the foreground colour on its own hover, not on the panel's", async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1280, "hover: 1280 only");
  await page.goto(ANALYSIS);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await page.mouse.move(0, 0);
  const link = page.locator('[data-slot="accordion-content"] p a').first();
  await link.scrollIntoViewIfNeeded();
  const colour = (): Promise<string> => link.evaluate((element): string => getComputedStyle(element).color);
  const foreground = await page.evaluate(() => getComputedStyle(document.body).color);
  const rest = await colour();
  expect(rest, "at rest the link is dimmer than the foreground").not.toBe(foreground);
  // A point on the paragraph, away from the link: its first line's left end,
  // or its right end when the link starts the line.
  const paragraph = await link.locator("xpath=ancestor::p[1]").boundingBox();
  const box = await link.boundingBox();
  if (paragraph === null || box === null) throw new Error("The paragraph or its link has no box.");
  const x = box.x > paragraph.x + 40 ? paragraph.x + 5 : paragraph.x + paragraph.width - 5;
  const y = paragraph.y + 8;
  await page.mouse.move(x, y);
  const under = await page.evaluate(
    ([px, py]): string => {
      const element = document.elementFromPoint(px, py);
      if (element === null) return "nothing";
      return element.closest("a") === null ? "paragraph" : "link";
    },
    [x, y],
  );
  expect(under, "the pointer is on the paragraph, not on a link").toBe("paragraph");
  expect(await colour(), "hovering the paragraph leaves its link's colour").toBe(rest);
  await link.hover();
  expect(await colour(), "hovering the link gives it the foreground colour").toBe(foreground);
});

// The measure's own control (as the clipping rule's in results.spec.ts), on a
// synthetic table with a correlation-matrix cell's first-column geometry: 44 px
// buttons with a 2 px outline at an offset of 2 px, 2 px of border spacing, and
// in each row a header with an opaque background. Sticky (positioned, so
// painted above an in-flow outline), the headers cover the left stroke of the
// middle row's first button while the ends of its top and bottom strokes still
// show in the gap beside it: that ring must fail, with its left side named. Not
// positioned, the headers paint under the outline, and the same ring passes.
// Both again with the table 0.234375 px lower (the local fixture's cells sit at
// that fraction): Chromium paints each box on the whole pixel rows it rounds
// to, so a side's span still ends inside the gap row below the cell, where the
// left stroke shows; only pixels wholly inside the span may count.
function controlPage(position: "sticky" | "static", top: number): string {
  const row = (name: string, id: string): string =>
    `<tr><th>${name}</th><td><button type="button" ${id}>.10</button></td><td><button type="button">.20</button></td></tr>`;
  return `<style>
    body { margin: 0; padding: ${top}px 40px 40px; background: #fff; font: 14px sans-serif }
    table { border-collapse: separate; border-spacing: 2px }
    th { position: ${position}; left: 0; z-index: 10; padding: 0 8px 0 0; background: #fff; font-weight: normal }
    td { padding: 0 }
    button { display: block; width: 44px; height: 44px; border: 0; border-radius: 2px; background: #c8d4e8; outline-offset: 2px }
    button:focus-visible { outline: 2px solid #000 }
  </style><table>${row("a", "")}${row("b", 'id="target"')}${row("c", "")}</table>`;
}

test("the measure's control: a ring whose left side lies under a positioned sibling fails, with that side named", async ({ page }) => {
  const cases = [
    { position: "sticky", top: 40, sidesMissing: ["left"], pass: false },
    { position: "static", top: 40, sidesMissing: [], pass: true },
    { position: "sticky", top: 40.234375, sidesMissing: ["left"], pass: false },
    { position: "static", top: 40.234375, sidesMissing: [], pass: true },
  ] as const;
  for (const { position, top, sidesMissing, pass } of cases) {
    const label = `${position} headers, the table at ${top} px`;
    await page.setContent(controlPage(position, top));
    await page.keyboard.press("Shift");
    await page.locator("#target").focus();
    const y = await page.locator("#target").evaluate((button): number => button.getBoundingClientRect().y);
    expect(y % 1, `${label}: the button's fraction of a pixel`).toBe(top % 1);
    const stop = await measureFocus(page);
    expect(stop, `${label}: the control's button has the focus`).not.toBeNull();
    expect.soft(stop?.sidesMissing, `${label}: the sides with no strong pixels`).toEqual(sidesMissing);
    expect.soft(stop?.pass, `${label}: the verdict`).toBe(pass);
  }
});
