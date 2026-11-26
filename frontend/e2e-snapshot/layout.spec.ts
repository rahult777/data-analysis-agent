// The desktop layout of the analysis page (M3a.2; owner rulings Q8 and R2), on
// the build Vercel deploys, every panel open. From lg (1024 px) the results
// keep to a 32.5rem (520 px) spine centred on the page, with the note's box on
// its left edge, and the figures leave it: the chart grid takes the page
// column's 56rem (896 px) below xl and 72rem (1152 px) from xl, where the
// charts' media grows from 224 to 320 px; the report's code blocks take 56rem.
// The page column stays 56rem. No sideways overflow. Run by the desktop
// project only, at its own widths; 320 px is covered by the overflow and
// reading-width tests and by the 22-shot comparison.

import { expect, test, type Page } from "@playwright/test";

import { REAL_ID } from "./snapshot";

test.use({ contextOptions: { reducedMotion: "reduce" } });

const ANALYSIS = `/analysis/${REAL_ID}`;

interface Box {
  x: number;
  width: number;
  centre: number;
}

interface Layout {
  viewport: number;
  scrollWidth: number;
  column: Box;
  spine: Box;
  note: Box;
  grid: Box;
  // Each chart card's media box height, each image's drawn height (object-contain
  // from its natural size) and each frame's height.
  media: number[];
  drawn: number[];
  frames: number[];
  code: Box[];
}

// Runs in the page.
function measureLayout(): Layout {
  const box = (element: Element | null): Box => {
    if (element === null) throw new Error("An element to measure is missing.");
    const r = element.getBoundingClientRect();
    return { x: r.x, width: r.width, centre: r.x + r.width / 2 };
  };
  const heading = Array.from(document.querySelectorAll("h2")).find((h) => (h.textContent ?? "").trim() === "Analysis complete");
  const cards = Array.from(document.querySelectorAll('[id^="chart-"]'));
  return {
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    column: box(document.querySelector("main > div")),
    spine: box(heading?.closest("header")?.parentElement ?? null),
    note: box(document.querySelector('section[aria-labelledby="about-this-example"]')),
    grid: box(cards[0]?.parentElement ?? null),
    media: cards.map((card) => Math.round((card.querySelector("img, iframe")?.parentElement ?? card).getBoundingClientRect().height)),
    drawn: Array.from(document.querySelectorAll<HTMLImageElement>('[id^="chart-"] img')).map((img) => {
      const r = img.getBoundingClientRect();
      return Math.round(img.naturalHeight * Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight));
    }),
    frames: Array.from(document.querySelectorAll('[id^="chart-"] iframe')).map((frame) => Math.round(frame.getBoundingClientRect().height)),
    code: Array.from(document.querySelectorAll('[data-slot="accordion-content"] pre')).map((pre) => box(pre.parentElement)),
  };
}

async function openAndSettle(page: Page): Promise<void> {
  await page.goto(ANALYSIS);
  const triggers = page.locator('[data-slot="accordion-trigger"]');
  await expect(triggers).toHaveCount(3);
  for (const trigger of await triggers.all()) {
    if ((await trigger.getAttribute("aria-expanded")) !== "true") await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  }
  // Every chart loaded (each scrolled into view: they are lazy).
  for (const media of await page.locator("img, iframe").all()) await media.scrollIntoViewIfNeeded();
  await expect(page.locator("[data-chart-placeholder]")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => Array.from(document.images).every((img) => img.complete && img.naturalWidth > 0))).toBe(true);
  await page.mouse.move(0, 0);
}

// The widths and what each one gets: below xl the figures keep the page
// column's 896 px and the charts 224 px; from xl the grid is 1152 px and the
// charts 320 px.
const WIDTHS = [
  { width: 1024, height: 900, grid: 896, media: 224 },
  { width: 1180, height: 900, grid: 896, media: 224 },
  { width: 1280, height: 900, grid: 1152, media: 320 },
  { width: 1440, height: 900, grid: 1152, media: 320 },
  { width: 1920, height: 1080, grid: 1152, media: 320 },
] as const;

for (const { width, height, grid, media } of WIDTHS) {
  test(`at ${width} px the results keep to a centred 520 px spine; the chart grid is ${grid} px with ${media} px charts, the code 896 px; no sideways overflow`, async ({ page }, info) => {
    test.skip(info.project.name !== "desktop-1280", "the desktop project only, at its own widths");
    await page.setViewportSize({ width, height });
    await openAndSettle(page);
    const m = await page.evaluate(measureLayout);
    const middle = m.viewport / 2;
    expect.soft(m.viewport, "the viewport").toBe(width);
    expect.soft(m.scrollWidth, "no sideways overflow").toBe(width);
    expect.soft(m.column.width, "the page column").toBe(896);
    expect.soft(Math.abs(m.column.centre - middle), "the page column is centred").toBeLessThanOrEqual(1);
    expect.soft(m.spine.width, "the spine").toBe(520);
    expect.soft(Math.abs(m.spine.centre - middle), "the spine is centred").toBeLessThanOrEqual(1);
    expect.soft(Math.abs(m.note.x - m.spine.x), "the note's box starts on the spine's left edge").toBeLessThanOrEqual(1);
    expect.soft(m.grid.width, "the chart grid").toBe(grid);
    expect.soft(Math.abs(m.grid.centre - middle), "the chart grid is centred").toBeLessThanOrEqual(1);
    expect.soft(m.media.length, "every chart card").toBe(14);
    expect.soft(Array.from(new Set(m.media)), "every chart's media box").toEqual([media]);
    expect.soft(Array.from(new Set(m.drawn)), "every image drawn at the media box's height").toEqual([media]);
    expect.soft(m.frames, "the interactive chart's frame").toEqual([media]);
    expect.soft(m.code.length, "the report's code blocks").toBe(26);
    expect.soft(Array.from(new Set(m.code.map((c) => c.width))), "every code block").toEqual([896]);
    expect.soft(Math.max(...m.code.map((c) => Math.abs(c.centre - middle))), "every code block is centred").toBeLessThanOrEqual(1);
  });
}

for (const { width, height, grid } of WIDTHS) {
  test(`at ${width} px an expanded chart card spans the ${grid} px grid, its media 70% of the viewport's height, with no sideways overflow`, async ({ page }, info) => {
    test.skip(info.project.name !== "desktop-1280", "the desktop project only, at its own widths");
    await page.setViewportSize({ width, height });
    await openAndSettle(page);
    const card = page.locator('[id^="chart-"]').filter({ has: page.locator("img") }).first();
    await card.getByRole("button", { name: "Expand chart" }).click();
    await expect(card.getByRole("button", { name: "Collapse chart" })).toBeVisible();
    await page.mouse.move(0, 0);
    await expect.poll(() => card.evaluate((element) => Math.round(element.getBoundingClientRect().width)), "the card spans the grid").toBe(grid);
    const m = await card.evaluate((element) => ({
      media: Math.round((element.querySelector("img")?.parentElement ?? element).getBoundingClientRect().height),
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect.soft(m.media, "the media is 70% of the viewport's height").toBe(Math.round(height * 0.7));
    expect.soft(m.scrollWidth, "no sideways overflow").toBe(width);
  });
}
