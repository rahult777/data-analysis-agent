// The header, footer and skip link of every public page (M2b.4b, owner ruling
// B2): rendered by the root layout in the public build, so "/", the analysis
// page and the 404 all carry them; <header> and <footer> landmarks outside
// <main>; the mark drawn inline, never an <img>; plain links. Every test runs
// at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { FIXTURE_ID } from "./fixture";
import { expectNoHorizontalOverflow, expectSameOriginOnly, logRequests, shot } from "./helpers";
import { NOTICES_URL, SKIP_LINK, expectChrome } from "./site";

const PAGES: ReadonlyArray<readonly [string, string]> = [
  ["home", "/"],
  ["analysis", `/analysis/${FIXTURE_ID}`],
  ["not-found", "/no-such-page"],
];

for (const [name, url] of PAGES) {
  test(`${url} carries the header and footer, outside <main>, with their links and the inline mark`, async ({ page, baseURL }, info) => {
    const requests = logRequests(page);
    await page.goto(url);
    await expectChrome(page);

    // Each link is a tap target, and no text is smaller than the 14 px minimum.
    const chrome = page.locator("body > header, body > footer");
    const links = chrome.getByRole("link");
    await expect(links).toHaveCount(5);
    const heights = await links.evaluateAll((elements) => elements.map((a) => Math.round(a.getBoundingClientRect().height)));
    expect(Math.min(...heights), `link heights ${heights.join(", ")}`).toBeGreaterThanOrEqual(44);
    const smallest = await chrome.evaluateAll((regions) => {
      let min = Infinity;
      for (const region of regions) {
        for (const element of [region, ...Array.from(region.querySelectorAll("*"))]) {
          const ownText = Array.from(element.childNodes).some((node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "");
          if (ownText) min = Math.min(min, Number.parseFloat(getComputedStyle(element).fontSize));
        }
      }
      return min;
    });
    expect(smallest, "smallest text in the header and footer").toBeGreaterThanOrEqual(14);

    await expectNoHorizontalOverflow(page);
    await page.waitForLoadState("networkidle");
    expectSameOriginOnly(requests, baseURL);
    await shot(page, info, `chrome-${name}`);
  });

  test(`${url}: the skip link appears on focus and leads into <main>`, async ({ page }) => {
    await page.goto(url);
    const skip = page.getByRole("link", { name: SKIP_LINK, exact: true });
    await expect(skip).toHaveAttribute("href", "#main");
    // Visually hidden until it has focus: a clipped one-pixel box.
    const before = await skip.boundingBox();
    expect(before !== null && before.width <= 1 && before.height <= 1, "hidden until focused").toBe(true);

    await page.keyboard.press("Tab");
    await expect(skip, "the first Tab stop").toBeFocused();
    const viewport = page.viewportSize();
    const shown = await skip.evaluate((a) => {
      const box = a.getBoundingClientRect();
      const style = getComputedStyle(a);
      return { x: box.x, y: box.y, right: box.right, width: box.width, height: box.height, clip: style.clip, overflow: style.overflow, opacity: style.opacity };
    });
    expect(shown.clip, "no longer clipped").toBe("auto");
    expect(shown.overflow).toBe("visible");
    expect(shown.opacity).toBe("1");
    expect(shown.height, "a tap target").toBeGreaterThanOrEqual(44);
    expect(shown.width).toBeGreaterThan(44);
    expect(shown.x >= 0 && shown.y >= 0 && shown.right <= (viewport?.width ?? 0), "on screen").toBe(true);

    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#main$/);
    // <main> itself takes the focus (tabIndex -1), so the skip link does not
    // rely on the browser moving its sequential focus starting point to the
    // fragment (owner ruling at STOP 2, Code Review #2). It is a focus target,
    // not a control, so it draws no focus ring.
    const main = page.getByRole("main");
    await expect(main, "<main> itself has focus").toBeFocused();
    const outline = await main.evaluate((element) => {
      const style = getComputedStyle(element);
      return { style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor };
    });
    expect(
      outline.style === "none" || outline.width === "0px" || outline.color === "rgba(0, 0, 0, 0)",
      `no focus ring on <main>: ${JSON.stringify(outline)}`,
    ).toBe(true);
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() => document.activeElement !== null && document.activeElement !== document.body && document.activeElement.closest("main") !== null),
      "the next Tab stop is inside <main>",
    ).toBe(true);
  });
}

test("the footer's notices link opens the third-party notices as plain text", async ({ page, request }) => {
  await page.goto("/");
  const link = page.getByRole("contentinfo").locator(`a[href="${NOTICES_URL}"]`);
  await expect(link).toHaveCount(1);
  const response = await request.get(NOTICES_URL);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("text/plain; charset=utf-8");
});
