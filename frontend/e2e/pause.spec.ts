import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

import {
  ANALYSIS_ID,
  MockApi,
  SESSION_ID,
  fixture,
  openAsOwner,
  openAsVisitor,
  statusBody,
  type HeldStatus,
  type ResumeReply,
  type StatusBody,
} from "./mockApi";

const DOMAIN_UNKNOWN = fixture("captured_domain_unknown.json");
const DOMAIN_RETAIL = fixture("synthetic_domain_retail.json");
const DOMAIN_HIGH = fixture("synthetic_domain_high_score.json");
const DOMAIN_BAD_IDS = fixture("synthetic_domain_nonstandard_ids.json");
const MV_REVENUE = fixture("captured_missing_value_revenue.json");
const MV_NOTES = fixture("captured_missing_value_notes.json");
const MV_TWO = fixture("synthetic_missing_value_two_options.json");
const OUTLIER_REVENUE = fixture("captured_outlier_revenue_financial.json");
const OUTLIER_MEDICAL = fixture("synthetic_outlier_medical.json");
const OUTLIER_NULLS = fixture("synthetic_outlier_null_stats.json");
const UNRENDERABLE = fixture("synthetic_unrenderable_missing_options.json");

const RECORDED_CLEANER =
  "Answer recorded — the Cleaner is re-running and may ask about another column (this can take a minute or two).";
const RECORDED_PROFILER =
  "Answer recorded — the Profiler is re-running with your answer, and the Cleaner may ask about a column next (this can take a minute or two).";
const MOVED_ON = "This question was already answered or has changed.";
const VISITOR_NOTE =
  "Only the browser that started this analysis can answer. If that's you, open this link in that browser — the analysis is waiting for this answer.";
const RAW_400_DETAIL = "response.option_id must be one of";
const NETWORK = "Couldn't reach the server, so your answer may not have been sent. Please try again.";

// Records, in the page, whether something ever happened — a transient wrong
// state that the next poll repairs would otherwise be waited out by the
// auto-retrying assertions.
async function watch(page: Page, name: string, condition: string): Promise<void> {
  await page.evaluate(
    ([key, source]) => {
      const w = window as unknown as Record<string, boolean>;
      w[key] = false;
      const check = new Function(`return (${source});`) as () => boolean;
      const observer = new MutationObserver(() => {
        if (check()) w[key] = true;
      });
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    },
    [name, condition],
  );
}

async function seen(page: Page, name: string): Promise<boolean> {
  return page.evaluate((key) => (window as unknown as Record<string, boolean>)[key] === true, name);
}

const QUESTION_GONE = `!document.querySelector('section[aria-label="Pipeline question"]')`;

let api: MockApi;

test.beforeEach(async ({ page }) => {
  api = new MockApi(page);
  await api.install();
});

test.afterEach(() => {
  expect(api.unmocked, "every API call must be mocked").toEqual([]);
});

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function question(page: Page): Locator {
  return page.getByRole("region", { name: "Pipeline question" });
}

function heading(page: Page): Locator {
  return question(page).getByRole("heading", { level: 2 });
}

function continueButton(page: Page): Locator {
  return page.getByRole("button", { name: "Continue with this choice" });
}

function statusLine(page: Page): Locator {
  return page.getByTestId("status-line");
}

async function expectLayout(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "no horizontal page overflow").toBe(0);
  // Layout height (offsetHeight), not the bounding box: entry animations
  // translate the card, which makes a measured box a sub-pixel off 44.
  const targets = question(page).locator("fieldset label");
  const count = await targets.count();
  for (let i = 0; i < count; i++) {
    const height = await targets.nth(i).evaluate((el) => (el as HTMLElement).offsetHeight);
    expect(height, "option tap target").toBeGreaterThanOrEqual(44);
  }
  if (await continueButton(page).isVisible()) {
    const height = await continueButton(page).evaluate((el) => (el as HTMLElement).offsetHeight);
    expect(height, "continue tap target").toBeGreaterThanOrEqual(44);
  }
}

// Screenshots for the build report, only when E2E_SCREENSHOT_DIR is set.
async function shot(page: Page, info: TestInfo, name: string): Promise<void> {
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(400); // let entry animations settle
  await page.screenshot({ path: path.join(dir, `${name}-${info.project.name}.png`), fullPage: true });
}

function ok(body: StatusBody): ResumeReply {
  return { status: 200, body };
}

// ---------------------------------------------------------------------------
// domain pause
// ---------------------------------------------------------------------------

test("domain pause: normal hypothesis, calibrated score and signals", async ({ page }, info) => {
  api.setStatus(statusBody("domain_pause", DOMAIN_RETAIL));
  await openAsOwner(page);

  await expect(heading(page)).toHaveText("Confirm what this data is");
  await expect(question(page)).toContainText("The Profiler's best guess is Retail and E-commerce.");
  await expect(question(page)).toContainText(
    "Confidence: 71 / 100 — below the 80 needed to continue without asking.",
  );
  await expect(question(page).getByRole("listitem")).toHaveCount(3);
  await expect(page.getByRole("radio", { name: "Yes, it's Retail and E-commerce" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "No, it's something else" })).toBeVisible();
  await expect(continueButton(page)).toBeDisabled();
  await expectLayout(page);
  await shot(page, info, "domain-normal");
});

test("domain pause: 'unknown' uses the decided wording and confirm sends exactly the contract", async ({ page }, info) => {
  api.setStatus(statusBody("domain_pause", DOMAIN_UNKNOWN));
  api.onResume(() => {
    api.setStatus(statusBody("profiling"));
    return ok(statusBody("profiling"));
  });
  await openAsOwner(page);

  await expect(heading(page)).toHaveText("The Profiler couldn't tell what kind of data this is.");
  await expect(question(page)).not.toContainText("best guess");
  await expect(question(page).getByRole("listitem")).toHaveCount(8);
  await expectLayout(page);
  await shot(page, info, "domain-unknown");

  await page.getByRole("radio", { name: "Continue without a specific domain" }).check();
  await expect(page.getByTestId("choice-details")).toContainText(
    "The analysis will use general, conservative interpretations.",
  );
  await continueButton(page).click();

  await expect(statusLine(page)).toHaveText(RECORDED_PROFILER);
  expect(api.resumeCalls).toEqual([
    { body: { response: { pause_type: "domain_pause", option_id: "confirm" } }, sessionHeader: SESSION_ID },
  ]);
  await expect(question(page)).toHaveCount(0);
});

test("domain pause: a score of 80 or more never claims to be below 80", async ({ page }) => {
  api.setStatus(statusBody("domain_pause", DOMAIN_HIGH));
  await openAsOwner(page);

  await expect(question(page)).toContainText("Confidence: 91 / 100.");
  await expect(question(page)).not.toContainText("below the 80");
});

test("domain pause: correct is trimmed, required and capped at 200 characters", async ({ page }) => {
  api.setStatus(statusBody("domain_pause", DOMAIN_RETAIL));
  api.onResume(() => {
    api.setStatus(statusBody("profiling"));
    return ok(statusBody("profiling"));
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: "No, it's something else" }).check();
  const input = page.getByLabel("What is this data?");
  await expect(input).toBeVisible();
  await expect(continueButton(page)).toBeDisabled();
  await input.fill("     ");
  await expect(continueButton(page)).toBeDisabled();
  await expect(input).toHaveAttribute("maxlength", "200");
  await input.fill("x".repeat(250));
  await expect(input).toHaveValue("x".repeat(200));

  await input.fill("  school assessment records  ");
  await expect(continueButton(page)).toBeEnabled();
  await expectLayout(page);
  await continueButton(page).click();

  await expect(statusLine(page)).toHaveText(RECORDED_PROFILER);
  expect(api.resumeCalls[0].body).toEqual({
    response: { pause_type: "domain_pause", option_id: "correct", corrected_domain: "school assessment records" },
  });
});

test("domain pause with option ids the pipeline cannot use is not answerable", async ({ page }) => {
  api.setStatus(statusBody("domain_pause", DOMAIN_BAD_IDS));
  await openAsOwner(page);

  await expect(heading(page)).toHaveText("This question can't be displayed");
  await expect(page.getByRole("radio")).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// missing-value pause
// ---------------------------------------------------------------------------

test("missing-value pause with 4 options: counts, context, select-then-confirm", async ({ page }, info) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("cleaning"));
    return ok(statusBody("cleaning"));
  });
  await openAsOwner(page);

  await expect(heading(page)).toHaveText("Missing values in revenue");
  await expect(heading(page).locator("code")).toHaveText("revenue");
  await expect(question(page)).toContainText("70 of 200 values (35%) are missing in the uploaded file.");
  await expect(question(page)).toContainText("Why this needs your decision");
  await expect(page.getByRole("radio")).toHaveCount(4);
  const keep = question(page).locator("label").filter({ hasText: "as it is" });
  await expect(keep.locator("code")).toHaveText("revenue");
  await expect(keep).not.toContainText("`");
  await expectLayout(page);
  await shot(page, info, "missing-value-4-options");

  // Selecting is not answering: the consequence shows first, nothing is sent.
  await page.getByRole("radio", { name: /Impute the 70 missing values/ }).check();
  const details = page.getByTestId("choice-details");
  await expect(details).toContainText("Method: median ($24,200).");
  await expect(details).toContainText("Assumption:");
  await page.getByRole("radio", { name: /Exclude the 70 rows/ }).check();
  await expect(details).toContainText("Preserves revenue as an unimputed column");
  expect(api.resumeCalls).toHaveLength(0);

  await page.getByRole("radio", { name: /Impute the 70 missing values/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(RECORDED_CLEANER);
  expect(api.resumeCalls[0].body).toEqual({
    response: { pause_type: "missing_value_pause", column_name: "revenue", option_id: "impute" },
  });
});

test("missing-value pause with 2 options (no recorded values) and a long column name", async ({ page }, info) => {
  api.setStatus(statusBody("missing_value_pause", MV_TWO));
  await openAsOwner(page);

  await expect(page.getByRole("radio")).toHaveCount(2);
  await expect(question(page)).toContainText("200 of 200 values (100%) are missing in the uploaded file.");
  await expectLayout(page);
  await shot(page, info, "missing-value-2-options");
});

// ---------------------------------------------------------------------------
// outlier pause
// ---------------------------------------------------------------------------

test("outlier pause, financial: Python's numbers and the exact resume body", async ({ page }, info) => {
  api.setStatus(statusBody("outlier_pause", OUTLIER_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("cleaning"));
    return ok(statusBody("cleaning"));
  });
  await openAsOwner(page);

  await expect(heading(page)).toHaveText("Unusual values in revenue");
  await expect(question(page)).toContainText("Financial data");
  await expect(question(page)).toContainText(
    "4 value(s) lie outside the typical range in the uploaded file. The most extreme, 750,000, is 6.79 SD from the column mean of 42,790.67.",
  );
  await expect(page.getByRole("radio")).toHaveCount(2);
  await expectLayout(page);
  await shot(page, info, "outlier-financial");

  await page.getByRole("radio", { name: /Flag the 4 outlier value/ }).check();
  await expect(page.getByTestId("choice-details")).toContainText(
    "The values are set to missing in revenue, so they drop out of every statistic",
  );
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(RECORDED_CLEANER);
  expect(api.resumeCalls[0].body).toEqual({
    response: { pause_type: "outlier_pause", column_name: "revenue", option_id: "flag_as_suspected_error" },
  });
});

test("outlier pause, medical", async ({ page }, info) => {
  api.setStatus(statusBody("outlier_pause", OUTLIER_MEDICAL));
  await openAsOwner(page);

  await expect(question(page)).toContainText("Medical data");
  await expect(question(page)).toContainText("A creatinine of 12.4 mg/dL likely indicates renal failure.");
  await expect(page.getByRole("radio", { name: /pending clinical review/ })).toBeVisible();
  await expectLayout(page);
  await shot(page, info, "outlier-medical");
});

test("outlier pause with null statistics omits the sentence instead of printing null", async ({ page }) => {
  api.setStatus(statusBody("outlier_pause", OUTLIER_NULLS));
  await openAsOwner(page);

  await expect(question(page)).toContainText("4 value(s) lie outside the typical range in the uploaded file.");
  // The UI's own sentence is omitted (the note is Python's text and keeps its numbers).
  await expect(question(page)).not.toContainText("The most extreme,");
  await expect(question(page)).not.toContainText(/null|NaN|undefined/);
});

// ---------------------------------------------------------------------------
// unrenderable, visitor
// ---------------------------------------------------------------------------

for (const [name, payload] of [
  ["malformed", UNRENDERABLE],
  ["null", null],
] as const) {
  test(`unrenderable pause_data (${name}) shows a fallback and polling continues`, async ({ page }, info) => {
    api.setStatus(statusBody("missing_value_pause", payload));
    await openAsOwner(page);

    await expect(heading(page)).toHaveText("This question can't be displayed");
    await expect(page.getByRole("radio")).toHaveCount(0);
    await expect(question(page).getByRole("link", { name: "Start a new analysis" })).toBeVisible();
    await expect(statusLine(page)).toHaveText("Paused: the Cleaner is waiting, but its question could not be loaded.");
    if (name === "malformed") await shot(page, info, "unrenderable");

    api.setStatus(statusBody("analyzing"));
    await expect(question(page)).toHaveCount(0);
    await expect(statusLine(page)).toHaveText("The Analyzer is working.");
  });
}

test("visitor sees the question read-only with the how-to-answer note", async ({ page }, info) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  await openAsVisitor(page);

  await expect(heading(page)).toHaveText("Missing values in revenue");
  await expect(question(page)).toContainText(VISITOR_NOTE);
  await expect(continueButton(page)).toHaveCount(0);
  for (const radio of await page.getByRole("radio").all()) await expect(radio).toBeDisabled();
  await expect(statusLine(page)).toContainText("waiting for an answer from the browser that started this analysis");
  await expectLayout(page);
  await shot(page, info, "visitor");
  expect(api.resumeCalls).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// submitting: sequences and failures
// ---------------------------------------------------------------------------

test("two pauses in sequence: each question replaces the last, focus moves to the new one", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume((call) => {
    const answered = (call.body as { response: { column_name: string } }).response.column_name;
    api.setStatus(statusBody("cleaning"));
    // The Cleaner re-runs, then asks about the next column.
    setTimeout(() => api.setStatus(statusBody("missing_value_pause", answered === "revenue" ? MV_NOTES : MV_REVENUE)), 1500);
    return ok(statusBody("cleaning"));
  });
  await openAsOwner(page);

  await expect(heading(page)).toBeFocused();
  await page.getByRole("radio", { name: /Impute the 70 missing values/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(RECORDED_CLEANER);

  await expect(heading(page)).toHaveText("Missing values in notes");
  await expect(heading(page)).toBeFocused();
  await expect(statusLine(page)).not.toHaveText(RECORDED_CLEANER);
  await page.getByRole("radio", { name: /Keep notes as it is/ }).check();
  api.onResume(() => {
    api.setStatus(statusBody("analyzing"));
    return ok(statusBody("analyzing"));
  });
  await continueButton(page).click();
  await expect(question(page)).toHaveCount(0);
  await expect(statusLine(page)).toHaveText(RECORDED_CLEANER);
  expect(api.resumeCalls.map((c) => c.body)).toEqual([
    { response: { pause_type: "missing_value_pause", column_name: "revenue", option_id: "impute" } },
    { response: { pause_type: "missing_value_pause", column_name: "notes", option_id: "preserve_missingness" } },
  ]);
});

test("400 after the pause moved on: says so, never shows the raw detail", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("cleaning")); // another tab already answered
    return { status: 400, body: { detail: "Analysis is not in a pause state." } };
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(MOVED_ON);
  await expect(statusLine(page)).toBeFocused();
  await expect(question(page)).toHaveCount(0);
  await expect(page.getByText("not in a pause state")).toHaveCount(0);
});

test("400 on the same pause: friendly retry text, question kept, raw detail hidden", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => ({ status: 400, body: { detail: `${RAW_400_DETAIL} ['impute']` } }));
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(question(page).getByRole("alert")).toHaveText(
    "Your answer couldn't be accepted. Check your choice and try again.",
  );
  await expect(heading(page)).toHaveText("Missing values in revenue");
  await expect(page.getByText(RAW_400_DETAIL)).toHaveCount(0);
  await expect(continueButton(page)).toBeEnabled();
});

test("409 with a new question: shows the new question and says the old one changed", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("missing_value_pause", MV_NOTES));
    return { status: 409, body: { detail: "The pause this response answers is no longer active. Refresh and try again." } };
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(heading(page)).toHaveText("Missing values in notes");
  await expect(heading(page)).toBeFocused();
  await expect(statusLine(page)).toHaveText(MOVED_ON);
  await expect(page.getByText("no longer active")).toHaveCount(0);
});

test("403 switches the question to read-only and marks nothing answered", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => ({ status: 403, body: { detail: "Invalid or missing session-id header." } }));
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(question(page)).toContainText(
    `This browser's saved session for this analysis was not accepted, so it can't answer here. ${VISITOR_NOTE}`,
  );
  await expect(continueButton(page)).toHaveCount(0);
  await expect(heading(page)).toHaveText("Missing values in revenue");
  await expect(page.getByText("session-id")).toHaveCount(0);
});

test("network error: refetch, same pause, retry text", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => ({ abort: true }));
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(question(page).getByRole("alert")).toHaveText(NETWORK);
  await expect(continueButton(page)).toBeEnabled();
});

test("timeout (15 s) on the same pause: refetch, retry text", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => ({ hang: true }));
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  const clicked = Date.now();
  await continueButton(page).click();
  await expect(page.getByRole("button", { name: "Sending…" })).toBeDisabled();
  await expect(question(page).getByRole("alert")).toHaveText(NETWORK, { timeout: 30_000 });
  expect(Date.now() - clicked).toBeGreaterThanOrEqual(14_000);
});

test("timeout where the server did apply the answer: refetch shows it moved on", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("cleaning")); // applied, but the response never arrives
    return { hang: true };
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(MOVED_ON, { timeout: 30_000 });
  await expect(question(page)).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// the stale-poll race (N5)
// ---------------------------------------------------------------------------

test("an older poll resolving late never overwrites a newer status", async ({ page }) => {
  api.setStatus(statusBody("cleaning"));
  await openAsOwner(page);
  await expect(statusLine(page)).toHaveText("The Cleaner is working.");

  const stale = api.holdNextStatus();
  await stale.arrived; // this poll is now in flight and held
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  await expect(heading(page)).toHaveText("Missing values in revenue"); // a newer poll applied

  await watch(page, "questionGone", QUESTION_GONE);
  await stale.release(statusBody("cleaning"));
  await page.waitForTimeout(1_000);
  expect(await seen(page, "questionGone"), "the stale 'cleaning' was never applied").toBe(false);
  await expect(heading(page)).toHaveText("Missing values in revenue");
});

test("a poll sent before the answer was accepted never re-shows the question", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  let stale: ReturnType<MockApi["holdNextStatus"]> | null = null;
  api.onResume(async () => {
    stale = api.holdNextStatus();
    await stale.arrived; // a poll is in flight while the answer is being applied
    api.setStatus(statusBody("cleaning"));
    return ok(statusBody("cleaning"));
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(RECORDED_CLEANER);
  expect(stale).not.toBeNull();
  await stale!.release(statusBody("missing_value_pause", MV_REVENUE));
  await page.waitForTimeout(500);
  await expect(question(page)).toHaveCount(0);
});

test("a lagging read of an answered question after a 200 is ignored", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => ok(statusBody("cleaning"))); // the next reads still lag behind
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(RECORDED_CLEANER);
  const polls = api.statusRequests.length;
  await expect.poll(() => api.statusRequests.length).toBeGreaterThanOrEqual(polls + 2);
  await expect(question(page)).toHaveCount(0);
});

test("a lagging read of a question that moved on (after a refetch) is ignored", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("cleaning"));
    return { status: 400, body: { detail: "Analysis is not in a pause state." } };
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(statusLine(page)).toHaveText(MOVED_ON);
  // Only the refetch marked the question answered; later reads now lag behind.
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  const polls = api.statusRequests.length;
  await expect.poll(() => api.statusRequests.length).toBeGreaterThanOrEqual(polls + 2);
  await expect(question(page)).toHaveCount(0);
});

test("a slow answer response never overwrites a newer read that already shows the next question", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(async () => {
    // The server applies the answer and the Cleaner re-pauses before the response gets back.
    api.setStatus(statusBody("missing_value_pause", MV_NOTES));
    await expect(heading(page)).toHaveText("Missing values in notes");
    // The new question is not the one being sent.
    await expect(page.getByRole("button", { name: "Sending…" })).toHaveCount(0);
    await expect(page.getByRole("radio").first()).toBeEnabled();
    await watch(page, "questionGone", QUESTION_GONE);
    await watch(page, "recorded", `document.body.innerText.includes(${JSON.stringify(RECORDED_CLEANER)})`);
    return ok(statusBody("cleaning")); // the state right after the write, now stale
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect.poll(() => api.resumeReplies).toBe(1);
  await page.waitForTimeout(1_000);
  expect(await seen(page, "questionGone"), "the next question stays").toBe(false);
  expect(await seen(page, "recorded"), "no stale 'Answer recorded' over the next question").toBe(false);
  await expect(heading(page)).toHaveText("Missing values in notes");
});

test("a refetch that loses the race to a newer poll still reports the moved-on state", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  let refetch: HeldStatus | null = null;
  api.onResume(async () => {
    // Reply just after an interval poll, so the next status request is the refetch.
    await api.nextStatusServed();
    api.setStatus(statusBody("cleaning"));
    refetch = api.holdNextStatus();
    return { status: 409, body: { detail: "The pause this response answers is no longer active." } };
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect.poll(() => refetch !== null).toBe(true);
  await refetch!.arrived;
  const requestsAtRefetch = api.statusRequests.length;
  await expect(question(page)).toHaveCount(0); // a newer interval poll was applied first
  expect(api.statusRequests.length).toBeGreaterThan(requestsAtRefetch);
  await refetch!.release(statusBody("cleaning"));
  await expect(statusLine(page)).toHaveText(MOVED_ON);
  await expect(page.getByText(NETWORK)).toHaveCount(0);
});

test("a refetch that fails after a newer poll moved on still reports the moved-on state", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("missing_value_pause", MV_NOTES)); // applied; the response is lost
    return { hang: true };
  });
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(heading(page)).toHaveText("Missing values in notes"); // a poll during the wait
  api.failStatusRequests(); // every later read fails, including the refetch after the 15 s timeout
  await expect(statusLine(page)).toHaveText(MOVED_ON, { timeout: 30_000 });
  await expect(page.getByText(NETWORK)).toHaveCount(0);
  await expect(heading(page)).toHaveText("Missing values in notes");
});

test("a server error (500) on the same pause is not blamed on the user's choice", async ({ page }) => {
  api.setStatus(statusBody("missing_value_pause", MV_REVENUE));
  api.onResume(() => ({ status: 500, body: { detail: "Internal Server Error" } }));
  await openAsOwner(page);

  await page.getByRole("radio", { name: /Impute/ }).check();
  await continueButton(page).click();
  await expect(question(page).getByRole("alert")).toHaveText(
    "Something went wrong on the server, so your answer wasn't recorded. Please try again.",
  );
});

// ---------------------------------------------------------------------------
// focus
// ---------------------------------------------------------------------------

test("focus moves to a new question once, never on a poll; after a submit it moves to the status line", async ({ page }) => {
  api.setStatus(statusBody("outlier_pause", OUTLIER_REVENUE));
  api.onResume(() => {
    api.setStatus(statusBody("cleaning"));
    return ok(statusBody("cleaning"));
  });
  await openAsOwner(page);

  await expect(heading(page)).toBeFocused();
  const radio = page.getByRole("radio", { name: /Treat the 4 outlier/ });
  await radio.check();
  await expect(radio).toBeFocused();
  const polls = api.statusRequests.length;
  await expect.poll(() => api.statusRequests.length).toBeGreaterThanOrEqual(polls + 2);
  await expect(radio).toBeFocused();

  await continueButton(page).click();
  await expect(statusLine(page)).toBeFocused();
});

// ---------------------------------------------------------------------------
// stall notice and the per-request timeout
// ---------------------------------------------------------------------------

test("stall notice after 10 minutes in the same non-pause status; clears on a change", async ({ page }, info) => {
  // setSystemTime moves Date only; timers and Framer Motion's animations keep
  // real time (a fully faked clock never lets an exit animation finish).
  const start = Date.now();
  await page.clock.setSystemTime(start);
  api.setStatus(statusBody("analyzing"));
  await openAsOwner(page);
  await expect(statusLine(page)).toHaveText("The Analyzer is working.");

  await page.clock.setSystemTime(start + 9.5 * 60 * 1000);
  const polls = api.statusRequests.length;
  await expect.poll(() => api.statusRequests.length).toBeGreaterThanOrEqual(polls + 2);
  await expect(page.getByTestId("stall-notice")).toHaveCount(0);

  await page.clock.setSystemTime(start + 10 * 60 * 1000 + 5_000);
  const notice = page.getByTestId("stall-notice");
  await expect(notice).toContainText("This step is taking longer than usual.");
  await expect(notice.getByRole("link", { name: "Start a new analysis" })).toHaveAttribute("href", "/");
  await expect(page.getByRole("listitem").filter({ hasText: "Analyzer" })).toBeVisible();
  await expectLayout(page);
  await shot(page, info, "stall-notice");

  api.setStatus(statusBody("explaining"));
  await expect(statusLine(page)).toHaveText("The Explainer is working.");
  await expect(page.getByTestId("stall-notice")).toHaveCount(0);
});

test("the 15 s timeout is on resume only: a slow status poll is not cut off", async ({ page }) => {
  api.setStatus(statusBody("analyzing"));
  await openAsOwner(page);
  await expect(statusLine(page)).toHaveText("The Analyzer is working.");

  await watch(page, "reconnecting", "document.body.innerText.includes('Reconnecting')");
  const failed: string[] = [];
  page.on("requestfailed", (request) => {
    if (request.url().endsWith("/status")) failed.push(request.failure()?.errorText ?? "failed");
  });
  const slow = api.holdNextStatus();
  await slow.arrived;
  await page.waitForTimeout(17_000);
  await slow.release(statusBody("analyzing"));
  await page.waitForTimeout(500);
  expect(await seen(page, "reconnecting"), "a slow poll never shows 'Reconnecting…'").toBe(false);
  expect(failed, "the slow poll was not cut off by a timeout").toEqual([]);
});

test("the 15 s timeout is on resume only: a slow upload (17 s) still succeeds", async ({ page }) => {
  api.setStatus(statusBody("profiling"));
  api.onUpload(async () => {
    await new Promise((resolve) => setTimeout(resolve, 17_000));
    return {
      status: 200,
      body: {
        analysis_id: ANALYSIS_ID,
        filename: "tiny.csv",
        status: "profiling",
        session_id: SESSION_ID,
        message: "Analysis started.",
      },
    };
  });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "tiny.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("a,b\n1,2\n3,4\n"),
  });
  await page.getByRole("button", { name: "Start Analysis" }).click();
  await expect(page).toHaveURL(new RegExp(`/analysis/${ANALYSIS_ID}$`), { timeout: 30_000 });
  await expect(statusLine(page)).toHaveText("The Profiler is working.");
});
