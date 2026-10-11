// "/" in the public snapshot build: a minimal placeholder (the landing page
// comes in M2b.4) that links to each saved analysis with a plain <a href>
// (owner ruling D7: no next/link) and never renders the upload UI. Every test
// runs at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { FIXTURE, FIXTURE_ID } from "./fixture";
import { expectNoHorizontalOverflow, expectSameOriginOnly, logRequests, saveRequestLog, shot } from "./helpers";

test("'/' links to each saved analysis and renders no upload UI", async ({ page, baseURL }, info) => {
  const requests = logRequests(page);
  const response = await page.goto("/");
  expect(response?.status()).toBe(200);

  const link = page.locator(`a[href="/analysis/${FIXTURE_ID}"]`);
  await expect(link).toHaveCount(1);
  await expect(link).toContainText(FIXTURE.filename);
  expect(await link.evaluate((el) => (el as HTMLElement).offsetHeight), "link tap target").toBeGreaterThanOrEqual(44);
  await expect(page.locator("input, textarea, form")).toHaveCount(0);
  expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/upload/i);
  await expectNoHorizontalOverflow(page);
  // "read-only" never breaks at its hyphen: a nowrap span (DM Sans may lack a
  // non-breaking hyphen glyph), so it renders as one line box.
  const readOnly = page.locator("header p span", { hasText: "read-only" });
  await expect(readOnly).toHaveCount(1);
  expect(await readOnly.evaluate((el) => el.getClientRects().length), '"read-only" on one line').toBe(1);

  await page.waitForLoadState("networkidle");
  expectSameOriginOnly(requests, baseURL);
  saveRequestLog(requests, info, "home");
  await shot(page, info, "home");
});

test("its link is a plain one: a full page load of the analysis, no client-side (RSC) navigation", async ({ page }) => {
  const requests = logRequests(page);
  await page.goto("/");
  await page.locator(`a[href="/analysis/${FIXTURE_ID}"]`).click();
  await expect(page).toHaveURL(`/analysis/${FIXTURE_ID}`);
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible();
  const documents = requests.filter((r) => r.resourceType === "document" && r.frame === "main").map((r) => new URL(r.url).pathname);
  expect(documents).toEqual(["/", `/analysis/${FIXTURE_ID}`]);
  expect(requests.filter((r) => new URL(r.url).searchParams.has("_rsc")).map((r) => r.url)).toEqual([]);
});
