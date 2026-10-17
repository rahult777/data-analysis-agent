// The real analysis page's "About this example" note: the owner's text from
// the manifest, under its own h2 between the page's h1 and the results header,
// with no motion, so it is there without JavaScript too. Every test runs at
// 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { comesBefore, effectiveOpacity, expectNoHorizontalOverflow, shot } from "../e2e-public/helpers";
import { NOTE, REAL_ID } from "./snapshot";

const PAGE = `/analysis/${REAL_ID}`;

test("shows the manifest's note under 'About this example', between the page's h1 and the results header", async ({ page }, info) => {
  await page.goto(PAGE);
  const section = page.getByRole("region", { name: "About this example", exact: true });
  await expect(section.getByRole("heading", { level: 2, name: "About this example", exact: true })).toBeVisible();
  await expect(section.locator("p")).toHaveCount(1);
  expect(await section.locator("p").textContent()).toBe(NOTE);
  const h1 = page.getByRole("heading", { level: 1, name: "Analysis" });
  const header = page.getByRole("heading", { name: "Analysis complete" });
  expect(await comesBefore(h1, section), "the page's h1 comes first").toBe(true);
  expect(await comesBefore(section, header), "then the note, then the results header").toBe(true);
  await expectNoHorizontalOverflow(page);
  await shot(page, info, "snapshot-note");
});

test.describe("the prerendered HTML (JavaScript off)", () => {
  test.use({ javaScriptEnabled: false });

  test("holds the note, with nothing hiding it", async ({ page }) => {
    await page.goto(PAGE);
    const section = page.getByRole("region", { name: "About this example", exact: true });
    await expect(section).toBeVisible();
    expect(await section.locator("p").textContent()).toBe(NOTE);
    // toBeVisible() counts opacity 0 as visible: check the opacity each part is drawn with.
    for (const part of [section, section.getByRole("heading", { level: 2 }), section.locator("p")]) {
      expect(await effectiveOpacity(part)).toBe(1);
    }
  });
});
