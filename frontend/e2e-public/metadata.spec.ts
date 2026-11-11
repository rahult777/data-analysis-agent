// The public build's head metadata (M2b.4a): each page's title, description
// and canonical link; the link preview every page takes from the root layout
// (the committed card: no page sets its own openGraph, which would replace
// the root's and drop the card); the icons, the viewport and the dark color
// scheme; and the files they point to, served with their types. Every test
// runs at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { FIXTURE_ID, TEST_SITE_URL } from "./fixture";
import {
  ANALYSIS_DESCRIPTION,
  SITE_DESCRIPTION,
  SITE_NAME,
  THEME_COLOR,
  TITLE_ANALYSIS,
  TITLE_NOT_FOUND,
  VIEWPORT,
  expectIcons,
  expectLinkPreview,
  headTags,
  linkHrefs,
} from "./site";

const ANALYSIS = `/analysis/${FIXTURE_ID}`;

test("'/' carries the site's title, description, canonical link, link preview, icons and dark color scheme", async ({ page }) => {
  await page.goto("/");
  const head = await headTags(page);
  expect(head.title).toBe(SITE_NAME);
  expect(head.meta.description).toEqual([SITE_DESCRIPTION]);
  // Next writes the site's root as the bare origin.
  expect(linkHrefs(head, "canonical")).toEqual([TEST_SITE_URL]);
  expect(head.meta.viewport).toEqual([VIEWPORT]);
  expect(head.meta["color-scheme"]).toEqual(["dark"]);
  expect(head.meta["theme-color"]).toEqual([THEME_COLOR]);
  expectLinkPreview(head, { title: SITE_NAME, description: SITE_DESCRIPTION });
  expectIcons(head);
});

test("the analysis page has its own title, description and canonical link, and keeps the site's link preview", async ({ page }) => {
  await page.goto("/");
  const card = expectLinkPreview(await headTags(page), { title: SITE_NAME, description: SITE_DESCRIPTION });
  await page.goto(ANALYSIS);
  const head = await headTags(page);
  expect(head.title).toBe(TITLE_ANALYSIS);
  expect(head.meta.description).toEqual([ANALYSIS_DESCRIPTION]);
  expect(linkHrefs(head, "canonical")).toEqual([`${TEST_SITE_URL}${ANALYSIS}`]);
  expect(head.meta.viewport).toEqual([VIEWPORT]);
  expect(head.meta["color-scheme"]).toEqual(["dark"]);
  expect(expectLinkPreview(head, { title: TITLE_ANALYSIS, description: ANALYSIS_DESCRIPTION }), "the same card as '/'").toBe(card);
  expectIcons(head);
});

test("the 404 page has its own title, no canonical link, and noindex", async ({ page }) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  const head = await headTags(page);
  expect(head.title).toBe(TITLE_NOT_FOUND);
  expect(linkHrefs(head, "canonical"), "a root canonical would reach the 404").toEqual([]);
  expect(head.meta.robots).toEqual(["noindex"]);
  expect(head.meta.viewport).toEqual([VIEWPORT]);
});

test("the icons, the card, robots.txt and sitemap.xml are served with their types", async ({ request }) => {
  const types: Record<string, string> = {
    "/favicon.ico": "image/x-icon",
    "/icon.svg": "image/svg+xml",
    "/apple-icon.png": "image/png",
    "/opengraph-image.png": "image/png",
    "/robots.txt": "text/plain; charset=utf-8",
    "/sitemap.xml": "application/xml",
  };
  for (const [url, type] of Object.entries(types)) {
    const response = await request.get(url);
    expect(response.status(), url).toBe(200);
    expect(response.headers()["content-type"], url).toBe(type);
  }
});
