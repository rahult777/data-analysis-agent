// The real site's front door (M2b.4b): the landing page built from the
// committed snapshot, and the header and footer on its pages. The landing
// page's sentences about the example are fixed copy, so the facts they state
// are pinned here against the snapshot's own JSON: a re-export that changes
// one fails this spec until the copy follows. The agents' texts state three of
// the backend's thresholds, pinned here against its own constants in the same
// way. Every test runs at 320 px and at 1280 px.

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { comesBefore, expectNoHorizontalOverflow, expectTextVisible, shot } from "../e2e-public/helpers";
import {
  EXAMPLE_LINK,
  LANDING_AGENTS,
  LANDING_EXAMPLE,
  LANDING_EXAMPLE_HEADING,
  LANDING_HOW,
  LANDING_KEY,
  LANDING_LEAD,
  LANDING_READ_ONLY,
  SITE_NAME,
  TAGLINE,
  exampleCounts,
  expectChrome,
} from "../e2e-public/site";
import { ANALYSIS, NOTE, REAL_ID } from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;

test("'/' is the landing page: the name and tagline, what it is, the four agents, the example and the read-only line, in order", async ({ page }, info) => {
  await page.goto("/");
  const main = page.getByRole("main");
  // Two links to the analysis (owner ruling R2): under the lead, and in the example.
  const links = main.locator(`a[href="${PAGE}"]`);
  await expect(links, "two links to the example analysis").toHaveCount(2);
  const parts = [
    main.getByRole("heading", { level: 1, name: SITE_NAME, exact: true }),
    main.getByText(TAGLINE, { exact: true }),
    main.getByText(LANDING_LEAD, { exact: true }),
    links.nth(0),
    main.getByRole("heading", { level: 2, name: LANDING_HOW, exact: true }),
    main.getByText(LANDING_KEY, { exact: true }),
    ...LANDING_AGENTS.flatMap(([name, text]) => [main.getByRole("heading", { level: 3, name, exact: true }), main.getByText(text, { exact: true })]),
    main.getByRole("heading", { level: 2, name: LANDING_EXAMPLE_HEADING, exact: true }),
    main.getByText(LANDING_EXAMPLE, { exact: true }),
    links.nth(1),
    main.getByText(LANDING_READ_ONLY, { exact: true }),
  ];
  for (const part of parts) await expect(part).toBeVisible();
  for (let i = 1; i < parts.length; i += 1) expect(await comesBefore(parts[i - 1], parts[i]), `part ${i} follows part ${i - 1}`).toBe(true);

  expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/upload/i);
  expect(await main.innerText()).not.toMatch(/\byou(r|rs)?\b/i);
  await expectNoHorizontalOverflow(page);
  await shot(page, info, "snapshot-landing");
});

test("the example is the demo: its file, its size before cleaning and two links to its analysis", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(`a[href="${PAGE}"]`)).toHaveCount(2);
  const links = page.getByRole("main").getByRole("link", { name: EXAMPLE_LINK, exact: true });
  await expect(links).toHaveCount(2);
  for (const link of await links.all()) await expect(link).toHaveAttribute("href", PAGE);
  // The second is in the example's card; the first, under the lead, is in none.
  // (`has` takes a locator relative to the item, so not `links`, which starts at <main>.)
  const item = page.getByRole("main").getByRole("listitem").filter({ has: page.getByRole("link", { name: EXAMPLE_LINK, exact: true }) });
  await expect(item).toHaveCount(1);
  await expect(item.getByRole("link")).toHaveCount(1);
  await expect(item.getByText("messy_data.csv", { exact: true })).toBeVisible();
  await expect(item.getByText(exampleCounts(200, 9), { exact: true })).toBeVisible();
  // The one under the lead opens the analysis.
  await links.first().click();
  await expect(page).toHaveURL(PAGE);
  await expect(page.getByRole("heading", { level: 1, name: "Example analysis", exact: true })).toBeVisible();
});

// No browser: the snapshot's own JSON against what the landing page says.
test("the landing page's sentences about the example match the snapshot", () => {
  expect(ANALYSIS.filename).toBe("messy_data.csv");
  expect([ANALYSIS.row_count, ANALYSIS.column_count]).toEqual([200, 9]);
  expect(exampleCounts(ANALYSIS.row_count, ANALYSIS.column_count)).toBe("200 rows and 9 columns before cleaning");
  // "One saved run on a small synthetic sales file": the owner's note says so.
  expect(NOTE).toContain("One saved run on a small synthetic sales dataset.");
  // "Three of its cleaning decisions were made by the person running it, at
  // pauses in the run, and are marked as theirs": exactly three decisions are
  // the user's, each made at a pause, each action marked as the user's. (The
  // JSON records no pause itself, so the copy states no count of pauses.)
  expect(LANDING_EXAMPLE).toContain("Three of its cleaning decisions were made by the person running it, at pauses in the run, and are marked as theirs.");
  const users = ANALYSIS.cleaning_decisions
    .map((decision, index) => ({ index, ...decision }))
    .filter((decision) => decision.reason.startsWith("Chosen by the user at the "));
  expect(users.map((decision) => decision.index)).toEqual([13, 14, 15]);
  for (const decision of users) {
    expect(decision.reason, `decision ${decision.index}`).toMatch(/^Chosen by the user at the (missing-value|financial outlier) pause, not decided by the Cleaner\./);
    expect(decision.action, `decision ${decision.index}`).toMatch(/^User decision \((missing-value|financial outlier) pause\): /);
  }
  // "Nothing the agents wrote has been corrected, so known errors are left in;
  // a note at the top of the page says so and points out the clearest one":
  // the note says so in its own words, and the one error it names, the
  // invented $31,738, is in the run's own decision [13].
  expect(LANDING_EXAMPLE).toContain("Nothing the agents wrote has been corrected, so known errors are left in; a note at the top of the page says so");
  expect(NOTE).toContain("Nothing the agents wrote has been corrected, so several known errors are left in rather than hidden.");
  expect(NOTE).toContain("fabricates $31,738");
  expect(ANALYSIS.cleaning_decisions[13].reason).toContain("fabricates $31,738 in revenue");
});

// A module-level number in one of the backend's agents, read from its one
// definition (`NAME = 80`, `NAME = 30.0`) and written as the copy writes it
// ("30"). A renamed, moved or second definition fails here, for a person to
// check the copy against.
function backendNumber(file: string, name: string): string {
  const source = readFileSync(path.join(__dirname, "..", "..", "backend", "agents", file), "utf8");
  const values = Array.from(source.matchAll(new RegExp(`^${name} *= *([0-9]+(?:\\.[0-9]+)?)\\b`, "gm")), (match) => match[1]);
  expect(values, `one definition of ${name} in backend/agents/${file}`).toHaveLength(1);
  return String(Number(values[0]));
}

// No browser: the backend's own thresholds against what the landing page says
// (owner ruling at STOP 2, Code Review #3). The browser tests hold the page to
// these literals, so a changed constant fails here until the copy follows.
test("the landing page's thresholds match the backend's constants", () => {
  const text = (agent: string) => LANDING_AGENTS.find(([name]) => name === agent)?.[1] ?? "";
  // The Profiler asks the person running it when its confidence is below this.
  expect(text("Profiler"), "the Profiler's text against profiler.py's DOMAIN_CONFIDENCE_THRESHOLD").toContain(
    `Below ${backendNumber("profiler.py", "DOMAIN_CONFIDENCE_THRESHOLD")} out of 100`,
  );
  // The Cleaner pauses on a column that is more than this share empty.
  expect(text("Cleaner"), "the Cleaner's text against cleaner.py's _MISSING_PAUSE_THRESHOLD_PCT").toContain(
    `more than ${backendNumber("cleaner.py", "_MISSING_PAUSE_THRESHOLD_PCT")}% empty`,
  );
  // The Analyzer labels a correlation on fewer complete pairs "Cannot Determine".
  expect(text("Analyzer"), "the Analyzer's text against analyzer.py's CORRELATION_MIN_PAIRS").toContain(
    `fewer than ${backendNumber("analyzer.py", "CORRELATION_MIN_PAIRS")} complete pairs`,
  );
});

for (const [name, url] of [["landing", "/"], ["analysis", PAGE], ["not-found", "/no-such-page"]] as const) {
  test(`${url} carries the header and footer`, async ({ page }, info) => {
    await page.goto(url);
    await expectChrome(page);
    await expectNoHorizontalOverflow(page);
    await shot(page, info, `snapshot-chrome-${name}`);
  });
}

test.describe("the prerendered HTML (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("the landing page reads in full, with nothing hiding it", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(LANDING_LEAD, { exact: true })).toBeVisible();
    await expect(page.getByText(LANDING_READ_ONLY, { exact: true })).toBeVisible();
    const links = page.getByRole("link", { name: EXAMPLE_LINK, exact: true });
    await expect(links).toHaveCount(2);
    for (const link of await links.all()) await expect(link).toBeVisible();
    await expectTextVisible(page);
    await expectNoHorizontalOverflow(page);
  });
});
