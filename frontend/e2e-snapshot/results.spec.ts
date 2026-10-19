// The real analysis page's results header, chart labels and Code label
// (M2b.3b.2), on the committed snapshot: the header's counts and its second
// line; no raw chart file name outside the code blocks; nothing clipped
// sideways (the clipping rule, with its own controls on synthetic boxes); the
// Code section's label; and the page under locales whose digits are not
// Latin (no hydration error, Latin digits in the header). Every test runs at
// 320 px and at 1280 px.

import { expect, test, type Page } from "@playwright/test";

import { comesBefore, expectNoClipping, expectNoHorizontalOverflow, shot } from "../e2e-public/helpers";
import { ANALYSIS, chartCardId, HEADER, KEPT_CHARTS, REAL_ID } from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;
const CODE_LABEL = "Written by the Explainer agent to illustrate each step. It is not the code that ran.";
// Locales whose digits are not Latin: the old header's toLocaleString() broke
// hydration under both (errors.md 2026-10-14).
const LOCALES = ["fa-IR", "ar-SA"];
const DECIMAL_DIGIT = new RegExp("\\p{Nd}", "u");

async function openEveryPanel(page: Page): Promise<void> {
  for (const name of [/Analyst Report/, /Open Questions/, /Technical Detail/]) {
    await page.getByRole("button", { name }).click();
    await expect(page.getByRole("region", { name })).toBeVisible();
  }
}

test("the header shows the cleaned counts, then the original file's on a second line", async ({ page }, info) => {
  await page.goto(PAGE);
  await expect.soft(page.locator("dl dt")).toHaveText(["Rows", "Columns", "Data quality"]);
  await expect.soft(page.locator("dl dd")).toHaveText(HEADER.dd);
  const line = page.locator("dl + p");
  await expect(line, "the second line, after the stats").toHaveCount(1);
  await expect.soft(line.locator('[aria-hidden="true"]')).toHaveText(HEADER.visible);
  await expect.soft(line.locator(".sr-only")).toHaveText(HEADER.spoken);
  // What a screen reader reads: the sentence, not the visible shorthand.
  await expect.soft(line).toMatchAriaSnapshot(`- paragraph: ${HEADER.spoken}`);
  await expectNoHorizontalOverflow(page);
  await shot(page, info, "snapshot-header");
});

test("no raw chart file name is visible outside the code blocks, with every panel open", async ({ page }) => {
  await page.goto(PAGE);
  await openEveryPanel(page);
  const found = await page.evaluate(
    ({ names, prefix }) => {
      const main = document.querySelector("main");
      if (main === null) return { outside: ["no <main> on the page"], codeBlocksWithNames: 0 };
      const codeBlocksWithNames = Array.from(main.querySelectorAll("pre")).filter((pre) =>
        (pre.textContent ?? "").includes(prefix),
      ).length;
      // The whole text of <main> without its code blocks, so a name split
      // across two text nodes is still found.
      const copy = main.cloneNode(true) as HTMLElement;
      for (const pre of Array.from(copy.querySelectorAll("pre"))) pre.remove();
      const text = copy.textContent ?? "";
      const outside = names.filter((name) => text.includes(name));
      if (text.includes(prefix)) outside.push(`${prefix}...`);
      return { outside, codeBlocksWithNames };
    },
    { names: ANALYSIS.chart_paths, prefix: `${REAL_ID}_` },
  );
  expect(found.outside, "chart file names outside <pre>").toEqual([]);
  // The check sees the page: the code blocks do name the charts.
  expect(found.codeBlocksWithNames, "code blocks that name a chart").toBeGreaterThan(0);
});

test("nothing is clipped sideways, with every panel open", async ({ page }) => {
  await page.goto(PAGE);
  await openEveryPanel(page);
  await expectNoClipping(page);
  await expectNoHorizontalOverflow(page);
});

// The clipping rule's own controls, on synthetic boxes (300 px of content in
// a 100 px box). It decides by overflow-x alone: a hidden or clipped
// overflow-x is checked even when CSS computes the box's overflow-y to auto;
// only overflow-x auto or scroll makes a scroll container, which is skipped.
test("the clipping rule checks an element by its overflow-x alone", async ({ page }) => {
  const cases: { css: string; clips: boolean }[] = [
    { css: "overflow-x: hidden", clips: true },
    { css: "overflow-x: hidden; overflow-y: auto", clips: true },
    { css: "overflow: hidden", clips: true },
    { css: "overflow-x: clip", clips: true },
    { css: "overflow-x: auto", clips: false },
    { css: "overflow-x: scroll", clips: false },
  ];
  for (const { css, clips } of cases) {
    await page.setContent(`<main><div style="width: 100px; ${css}"><div style="width: 300px">wide content</div></div></main>`);
    if (clips) await expect.soft(expectNoClipping(page), css).rejects.toThrow("300/100: wide content");
    else await expect.soft(expectNoClipping(page), css).resolves.toBeUndefined();
  }
  await page.setContent('<main><div style="width: 100px; overflow-x: hidden"><div style="width: 50px">narrow</div></div></main>');
  await expect.soft(expectNoClipping(page), "content that fits").resolves.toBeUndefined();
});

test("the Code section carries its label once, under its heading and above the blocks", async ({ page }) => {
  await page.goto(PAGE);
  await page.getByRole("button", { name: /Technical Detail/ }).click();
  const technical = page.getByRole("region", { name: /Technical Detail/ });
  const label = technical.getByText(CODE_LABEL, { exact: true });
  await expect(label).toHaveCount(1);
  expect(await comesBefore(technical.getByText("Code", { exact: true }), label), "under the Code heading").toBe(true);
  expect(await comesBefore(label, technical.locator("pre").first()), "above the first block").toBe(true);
  await expect(page.getByText(CODE_LABEL, { exact: true })).toHaveCount(1);
});

for (const locale of LOCALES) {
  test.describe(`under ${locale}`, () => {
    test.use({ locale });

    test("the page hydrates without an error, and the header keeps Latin digits", async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(`console: ${message.text()}`);
      });
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
      await page.goto(PAGE);
      // Hydration is over once a chart card shows its image: the cards render
      // their media only after they mount (ChartGrid.tsx).
      await expect(page.locator(`#${chartCardId(KEPT_CHARTS[0])} img`)).toHaveCount(1);
      expect.soft(errors, "no hydration error").toEqual([]);
      await expect.soft(page.locator("dl dd")).toHaveText(HEADER.dd);
      await expect.soft(page.locator('dl + p [aria-hidden="true"]')).toHaveText(HEADER.visible);
      const header = page.locator("header").filter({ has: page.getByRole("heading", { name: "Analysis complete" }) });
      const digits = Array.from((await header.textContent()) ?? "").filter((ch) => DECIMAL_DIGIT.test(ch));
      expect.soft(digits.length, "the header has digits").toBeGreaterThan(0);
      expect.soft(digits.filter((ch) => ch < "0" || ch > "9"), "every digit in the header is Latin").toEqual([]);
    });
  });
}
