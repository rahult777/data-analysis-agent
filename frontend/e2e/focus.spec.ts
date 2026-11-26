// The keyboard focus indicator in local mode (M3a.2), on the states the public
// build never shows, route-mocked (e2e/mockApi.ts): the upload page with a file
// chosen and its error state, the progress page's stall notice, a domain pause
// with "something else" chosen and a domain typed, a pause whose stored
// question can't be displayed, the owner's results with every panel open and
// one answered question, and a visitor's results (the public snapshot
// fixture's analysis and its two charts). The same Tab walk and measure as the
// public site's (e2e-public/focus.ts). Also a pause option's radio, which draws
// no outline of its own (its label's ring is the one indicator), every
// correlation-matrix cell of the fixture, and a wide matrix (ten long-named
// columns, so it scrolls sideways at every width): every keyboard focus keeps
// the cell and its outline clear of the sticky row header and inside the
// scroller (at 320 px; at 1024, 1280 and 1440 px in the desktop project), its
// first and last columns' cells show a visible indicator, and after a pointer
// focus, Home and the arrow keys still make a keyboard focus in a browser whose
// heuristic would not (emulated). Runs at both viewport widths.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import type { AnalysisResponse } from "../lib/types";
import { expectFocusVisible, expectKinds, matrixWalk, measureFocus, saveFocusReport, tabWalk, type FocusStop } from "../e2e-public/focus";
import { ANALYSIS_ID, fixture, MockApi, openAsOwner, openAsVisitor, statusBody } from "./mockApi";

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

let api: MockApi;

test.beforeEach(async ({ page }) => {
  api = new MockApi(page);
  await api.install();
});

test.afterEach(() => {
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

function withResults(answer: boolean, analysis: AnalysisResponse = ANALYSIS): void {
  api.setStatus(statusBody("complete"));
  api.setAnalysis(analysis);
  api.setChart(PNG, readFileSync(path.join(SNAPSHOT_FIXTURE, "charts", PNG)), "image/png");
  api.setChart(HTML, readFileSync(path.join(SNAPSHOT_FIXTURE, "charts", HTML)), "text/html; charset=utf-8");
  if (answer) api.setQuestionAnswer(ANSWER);
}

async function openEveryPanel(page: Page): Promise<void> {
  const triggers = page.locator('[data-slot="accordion-trigger"]');
  await expect(triggers).toHaveCount(3);
  for (const trigger of await triggers.all()) {
    if ((await trigger.getAttribute("aria-expanded")) !== "true") await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  }
}

// Every chart loaded (each scrolled into view: they are lazy), back at the top,
// the mouse parked.
async function settle(page: Page): Promise<void> {
  for (const media of await page.locator("img, iframe").all()) await media.scrollIntoViewIfNeeded();
  await expect(page.locator("[data-chart-placeholder]")).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.mouse.move(0, 0);
}

async function walk(page: Page): Promise<FocusStop[]> {
  const { stops, frames, complete } = await tabWalk(page);
  // Soft, so one run also measures every stop.
  expect.soft(complete, "the walk came back round").toBe(true);
  expect.soft(frames, "no focus stop is a chart's frame").toBe(0);
  return stops;
}

test("every focus stop on the upload page with a file chosen shows a visible indicator", async ({ page }, info) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n3,4\n") });
  await expect(page.getByRole("button", { name: "Start Analysis" })).toBeEnabled();
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "upload-file");
  expectKinds(stops, ["role=button (div)", "Textarea (ui)", "button (plain)", "Button (ui)"], "upload-file");
  await expectFocusVisible(stops, info, "upload-file");
});

test("every focus stop on the upload page's error state shows a visible indicator", async ({ page }, info) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not a table\n") });
  await expect(page.getByRole("button", { name: "Try Again" })).toBeVisible();
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "upload-error");
  expectKinds(stops, ["role=button (div)", "Textarea (ui)", "button (plain)", "Button (ui)"], "upload-error");
  await expectFocusVisible(stops, info, "upload-error");
});

test("the progress page's stall notice: its link shows a visible indicator", async ({ page }, info) => {
  // setSystemTime moves Date only (as pause.spec.ts's stall test).
  const start = Date.now();
  await page.clock.setSystemTime(start);
  api.setStatus(statusBody("analyzing"));
  await openAsOwner(page);
  await expect(page.getByTestId("status-line")).toHaveText("The Analyzer is working.");
  await page.clock.setSystemTime(start + 10 * 60 * 1000 + 5_000);
  await expect(page.getByTestId("stall-notice")).toBeVisible();
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "progress-stall");
  expectKinds(stops, ["stall link"], "progress-stall");
  await expectFocusVisible(stops, info, "progress-stall");
});

test("a domain pause with \"something else\" chosen and a domain typed: every focus stop shows a visible indicator, and the radio draws no outline of its own", async ({ page }, info) => {
  api.setStatus(statusBody("domain_pause", fixture("synthetic_domain_retail.json")));
  await openAsOwner(page);
  const other = page.getByRole("radio", { name: "No, it's something else" });
  await other.check();
  await page.getByLabel("What is this data?").fill("school assessment records");
  await expect(page.getByRole("button", { name: "Continue with this choice" })).toBeEnabled();
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "pause-domain-else");
  expectKinds(stops, ["button (plain)", "pause option (radio)", "input", "Button (ui)"], "pause-domain-else");
  await expectFocusVisible(stops, info, "pause-domain-else");

  // The radio's own outline (the global :focus-visible outline would draw a
  // square around the round radio, inside its label's ring).
  await page.keyboard.press("Shift");
  await other.focus();
  await expect(other).toBeFocused();
  expect(await other.evaluate((element) => element.matches(":focus-visible")), "a keyboard focus").toBe(true);
  const outline = await other.evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor };
  });
  expect(
    outline.style === "none" || outline.width === "0px" || outline.color === "rgba(0, 0, 0, 0)",
    `the focused radio draws no outline (${outline.style} ${outline.width} ${outline.color})`,
  ).toBe(true);
});

test("a pause whose stored question can't be displayed: its link shows a visible indicator", async ({ page }, info) => {
  // pause.spec.ts's unrenderable state (the malformed payload).
  api.setStatus(statusBody("missing_value_pause", fixture("synthetic_unrenderable_missing_options.json")));
  await openAsOwner(page);
  await expect(page.getByRole("heading", { name: "This question can't be displayed" })).toBeVisible();
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "pause-unrenderable");
  expectKinds(stops, ["page link"], "pause-unrenderable");
  expect(stops.map((stop): string => stop.name), "the walk reaches the question's link").toContain("Start a new analysis");
  await expectFocusVisible(stops, info, "pause-unrenderable");
});

test("every focus stop on the owner's results, every panel open and one question answered, shows a visible indicator", async ({ page }, info) => {
  withResults(true);
  await openAsOwner(page);
  await openEveryPanel(page);
  const input = page.getByLabel("Ask a question about this dataset");
  await expect(input).toBeEnabled();
  await input.fill("Which region has the highest mean revenue?");
  await page.getByRole("button", { name: "Submit question" }).click();
  await expect(page.getByText(ANSWER.answer)).toBeVisible();
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "results-owner-answer");
  expectKinds(
    stops,
    ["card expand button", "card full-size link", "accordion trigger", "matrix cell", "chart pill link", "code copy button", "Input (ui)"],
    "results-owner-answer",
  );
  await expectFocusVisible(stops, info, "results-owner-answer");
});

test("every focus stop on a visitor's results, every panel open, shows a visible indicator", async ({ page }, info) => {
  withResults(false);
  await openAsVisitor(page);
  await openEveryPanel(page);
  await settle(page);
  const stops = await walk(page);
  saveFocusReport(stops, info, "results-visitor");
  expectKinds(
    stops,
    ["card expand button", "card full-size link", "accordion trigger", "matrix cell", "chart pill link", "code copy button", "page link"],
    "results-visitor",
  );
  await expectFocusVisible(stops, info, "results-visitor");
});

test("every correlation-matrix cell of the fixture, focused with the arrow keys, shows a visible indicator", async ({ page }, info) => {
  withResults(false);
  await openAsVisitor(page);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await settle(page);
  const cells = await matrixWalk(page);
  saveFocusReport(cells, info, "matrix-fixture");
  expect(cells, "the fixture's matrix: 2 columns, 4 cells").toHaveLength(4);
  await expectFocusVisible(cells, info, "matrix-fixture");
});

// The wide matrix: ten numeric columns, each name long enough to give the row
// header its widest box (the name is cut at 96 px, 160 px from 640 px up).
const WIDE_COLUMNS = [
  "quarterly_revenue_per_region_usd",
  "units_sold_per_store_per_week",
  "average_discount_percentage",
  "unit_price_after_promotions",
  "customer_age_at_first_purchase",
  "days_between_order_and_shipping",
  "returned_items_share_of_orders",
  "estimated_customer_lifetime_value",
  "marketing_spend_per_channel_usd",
  "post_purchase_satisfaction_score",
];

function wideAnalysis(): AnalysisResponse {
  const matrix: Record<string, Record<string, number>> = {};
  WIDE_COLUMNS.forEach((a, i): void => {
    matrix[a] = {};
    WIDE_COLUMNS.forEach((b, j): void => {
      matrix[a][b] = i === j ? 1 : Math.round((((i + 1) * (j + 1)) % 17) - 8) / 10;
    });
  });
  return { ...ANALYSIS, analysis_report: { ...(ANALYSIS.analysis_report ?? {}), correlation_matrix: { matrix, strong_pairs: [] } } };
}

async function openWideMatrix(page: Page): Promise<void> {
  withResults(false, wideAnalysis());
  await openAsVisitor(page);
  await page.getByRole("button", { name: /Analyst Report/ }).click();
  await settle(page);
}

interface Reveal {
  label: string;
  cell: string;
  // The focused cell's box plus 2 px on each side, the row header's right edge
  // and the scroller's right edge (its padding box), in viewport pixels.
  left: number;
  right: number;
  header: number;
  edge: number;
  scrollLeft: number;
  // Whether the cell matches :focus-visible, and its computed outline style.
  focusVisible: boolean;
  outline: string;
  clear: boolean;
}

// Read straight after a key, before anything else scrolls: measureFocus
// scrolls the element into view itself, which would hide a cell left under
// the header.
async function reveal(page: Page, label: string): Promise<Reveal> {
  const box = await page.evaluate((): Omit<Reveal, "label" | "clear"> | null => {
    const cell = document.activeElement;
    if (!(cell instanceof HTMLButtonElement) || cell.dataset.row === undefined) return null;
    const header = cell.closest("tr")?.querySelector("th");
    const scroller = cell.closest("table")?.parentElement;
    if (!header || !scroller) return null;
    const c = cell.getBoundingClientRect();
    const v = scroller.getBoundingClientRect();
    return {
      cell: `(${cell.dataset.row}, ${cell.dataset.col})`,
      left: c.left - 2,
      right: c.right + 2,
      header: header.getBoundingClientRect().right,
      edge: v.left + scroller.clientLeft + scroller.clientWidth,
      scrollLeft: scroller.scrollLeft,
      focusVisible: cell.matches(":focus-visible"),
      outline: getComputedStyle(cell).outlineStyle,
    };
  });
  if (box === null) throw new Error(`${label}: the focus is not on a matrix cell.`);
  return { label, ...box, clear: box.left >= box.header && box.right <= box.edge };
}

test("a wide correlation matrix: every keyboard focus keeps the cell and its outline clear of the row header and inside the scroller", async ({ page }, info) => {
  test.setTimeout(120_000);
  const viewport = page.viewportSize() ?? { width: 1280, height: 900 };
  const widths = viewport.width < 1280 ? [320] : [1024, 1280, 1440];
  await openWideMatrix(page);
  const first = page.locator('button[data-row="0"][data-col="0"]');
  const scroller = page.locator("table:has(button[data-row])").locator("xpath=..");
  const seen: Reveal[] = [];
  for (const width of widths) {
    await page.setViewportSize({ width, height: viewport.height });
    await scroller.evaluate((element): void => element.scrollTo({ left: 0, behavior: "instant" }));
    const sideways = await scroller.evaluate((element): number => element.scrollWidth - element.clientWidth);
    expect(sideways, `${width} px: the matrix scrolls sideways`).toBeGreaterThan(0);
    // A real focus at every width: the last width ends with (0, 0) focused.
    await page.evaluate((): void => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    });
    await expect(first).not.toBeFocused();
    await page.keyboard.press("Shift");
    await first.focus();
    seen.push(await reveal(page, `${width} px: (0, 0) focused`));
    for (let col = 1; col < WIDE_COLUMNS.length; col += 1) {
      await page.keyboard.press("ArrowRight");
      seen.push(await reveal(page, `${width} px: ArrowRight`));
    }
    for (let col = WIDE_COLUMNS.length - 2; col >= 0; col -= 1) {
      await page.keyboard.press("ArrowLeft");
      seen.push(await reveal(page, `${width} px: ArrowLeft`));
    }
    // Tab out, move the scroller until the roving cell, (0, 0), has half its
    // width under the row header, then Shift+Tab back in.
    await page.keyboard.press("Tab");
    await expect(first).not.toBeFocused();
    const under = await first.evaluate((cell): number | null => {
      const header = cell.closest("tr")?.querySelector("th");
      const scroller = cell.closest("table")?.parentElement;
      if (!header || !scroller) return null;
      const by = cell.getBoundingClientRect().left - header.getBoundingClientRect().right + cell.getBoundingClientRect().width / 2;
      scroller.scrollTo({ left: scroller.scrollLeft + by, behavior: "instant" });
      return header.getBoundingClientRect().right - cell.getBoundingClientRect().left;
    });
    expect(under, `${width} px: the roving cell's px under the row header before Shift+Tab`).toBeGreaterThan(10);
    await page.keyboard.press("Shift+Tab");
    await expect(first).toBeFocused();
    seen.push(await reveal(page, `${width} px: Shift+Tab back in`));
  }
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (dir) {
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, `matrix-reveal-${info.project.name}.json`), JSON.stringify(seen, null, 2) + "\n");
  }
  expect(seen.length, "every key was read").toBe(widths.length * (2 * WIDE_COLUMNS.length));
  expect(
    seen
      .filter((r): boolean => !r.clear)
      .map((r): string => `${r.label} ${r.cell}: ${r.left.toFixed(1)}..${r.right.toFixed(1)}, header ${r.header.toFixed(1)}, edge ${r.edge.toFixed(1)}`),
    "focused cells not clear of the row header and inside the scroller",
  ).toEqual([]);
});

// A browser whose heuristic leaves a scripted focus without :focus-visible
// after a pointer focus (WebKit, for a key handler that calls preventDefault()
// and focus() after a click), emulated in Chromium, which honours the option
// from 145: every focus() call that does not set focusVisible passes
// focusVisible: false.
function scriptedFocusNotVisible(): void {
  const focus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (this: HTMLElement, options?: FocusOptions): void {
    const forced: FocusOptions & { focusVisible?: boolean } = { focusVisible: false, ...options };
    focus.call(this, forced);
  };
}

test("after a pointer focus, Home and the arrow keys still make a keyboard focus: the cell's outline shows, clear of the row header and inside the scroller (a browser that would not, emulated)", async ({ page, browser }, info) => {
  const version = browser.version();
  expect(Number.parseInt(version, 10), `Chromium ${version} honours focus({ focusVisible }) (145 or later)`).toBeGreaterThanOrEqual(145);
  await page.addInitScript(scriptedFocusNotVisible);
  await openWideMatrix(page);
  const cell = (col: number): Locator => page.locator(`button[data-row="0"][data-col="${col}"]`);
  const scroller = page.locator("table:has(button[data-row])").locator("xpath=..");
  const pointerFocus = async (col: number): Promise<void> => {
    await cell(col).click();
    await expect(cell(col)).toBeFocused();
    expect(await cell(col).evaluate((element): boolean => element.matches(":focus-visible")), `(0, ${col}): a pointer focus`).toBe(false);
  };
  const seen: Reveal[] = [];

  // Home: a click on (0, 1), then the scroller moved until (0, 0) has half its
  // width under the row header.
  await scroller.evaluate((element): void => element.scrollTo({ left: 0, behavior: "instant" }));
  await pointerFocus(1);
  const under = await cell(0).evaluate((element): number | null => {
    const header = element.closest("tr")?.querySelector("th");
    const box = element.closest("table")?.parentElement;
    if (!header || !box) return null;
    const by = element.getBoundingClientRect().left - header.getBoundingClientRect().right + element.getBoundingClientRect().width / 2;
    box.scrollBy({ left: by, behavior: "instant" });
    return header.getBoundingClientRect().right - element.getBoundingClientRect().left;
  });
  expect(under, "(0, 0)'s px under the row header before Home").toBeGreaterThan(10);
  await page.keyboard.press("Home");
  seen.push(await reveal(page, "a click on (0, 1), then Home"));

  // ArrowRight: the scroller back at its start, a click on the cell before the
  // first one its right edge cuts, then ArrowRight onto that one.
  await scroller.evaluate((element): void => element.scrollTo({ left: 0, behavior: "instant" }));
  const cut = await scroller.evaluate((element): number => {
    const edge = element.getBoundingClientRect().left + element.clientLeft + element.clientWidth;
    const cells = Array.from(element.querySelectorAll<HTMLButtonElement>('button[data-row="0"]'));
    return cells.findIndex((c): boolean => c.getBoundingClientRect().right + 2 > edge && c.getBoundingClientRect().left < edge);
  });
  expect(cut, "a cell that the scroller's right edge cuts").toBeGreaterThan(0);
  await pointerFocus(cut - 1);
  expect(await scroller.evaluate((element): number => element.scrollLeft), "the click left the scroller at its start").toBe(0);
  await page.keyboard.press("ArrowRight");
  seen.push(await reveal(page, `a click on (0, ${cut - 1}), then ArrowRight`));

  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (dir) {
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, `matrix-after-pointer-${info.project.name}.json`), JSON.stringify({ version, seen }, null, 2) + "\n");
  }
  expect(seen.map((r): string => r.cell), "the cells the keys moved to").toEqual(["(0, 0)", `(0, ${cut})`]);
  expect(
    seen
      .filter((r): boolean => !r.focusVisible || r.outline !== "solid" || !r.clear)
      .map(
        (r): string =>
          `${r.label} ${r.cell}: :focus-visible ${r.focusVisible}, outline ${r.outline}, ${r.left.toFixed(1)}..${r.right.toFixed(1)}, header ${r.header.toFixed(1)}, edge ${r.edge.toFixed(1)}`,
      ),
    "keyboard focuses after a pointer focus that show no outline, or are not clear of the row header and inside the scroller",
  ).toEqual([]);
});

test("the wide matrix's first and last columns, focused with the arrow keys, show a visible indicator", async ({ page }, info) => {
  test.setTimeout(120_000);
  await openWideMatrix(page);
  await page.keyboard.press("Shift");
  await page.locator('button[data-row="0"][data-col="0"]').focus();
  const stops: FocusStop[] = [];
  const measure = async (label: string): Promise<void> => {
    const stop = await measureFocus(page);
    expect(stop, `${label}: a measured focus stop`).not.toBeNull();
    if (stop !== null) stops.push(stop);
  };
  for (let row = 0; row < WIDE_COLUMNS.length; row += 1) {
    if (row > 0) await page.keyboard.press("ArrowDown");
    await measure(`(${row}, 0)`);
  }
  await page.keyboard.press("End");
  for (let row = WIDE_COLUMNS.length - 1; row >= 0; row -= 1) {
    if (row < WIDE_COLUMNS.length - 1) await page.keyboard.press("ArrowUp");
    await measure(`(${row}, ${WIDE_COLUMNS.length - 1})`);
  }
  saveFocusReport(stops, info, "matrix-wide");
  expect(stops, "the wide matrix's first and last columns: 20 cells").toHaveLength(2 * WIDE_COLUMNS.length);
  await expectFocusVisible(stops, info, "matrix-wide");
});
