// The public snapshot build's 404 page (app/not-found.tsx, exported as
// 404.html): plain and neutral, with no upload wording, served with status
// 404 for any unknown address. Every test runs at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { UNLISTED_ID } from "./fixture";
import { expectNoHorizontalOverflow, expectSameOriginOnly, logRequests, saveRequestLog, shot } from "./helpers";

const UNKNOWN = [`/analysis/${UNLISTED_ID}`, "/no-such-page"];

for (const url of UNKNOWN) {
  test(`${url} gets the plain 404 page, with status 404`, async ({ page, baseURL }, info) => {
    const requests = logRequests(page);
    const response = await page.goto(url);
    expect(response?.status()).toBe(404);

    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    // Not Next's default 404 page.
    await expect(page.getByText("This page could not be found.")).toHaveCount(0);
    expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/upload/i);
    await expect(page.locator('a[href="/"]')).toHaveCount(1);
    await expectNoHorizontalOverflow(page);

    await page.waitForLoadState("networkidle");
    expectSameOriginOnly(requests, baseURL);
    if (url === UNKNOWN[0]) {
      saveRequestLog(requests, info, "not-found");
      await shot(page, info, "not-found");
    }
  });
}
