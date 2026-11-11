// The real snapshot build's head metadata (M2b.4a), checked as the public
// suite checks the fixture's (e2e-public/metadata.spec.ts): "/" and the real
// analysis page with their titles, descriptions, canonical links and the root
// layout's link preview, the 404's title, and the name on "/". Every test runs
// at 320 px and at 1280 px.

import { expect, test } from "@playwright/test";

import { TEST_SITE_URL } from "../e2e-public/fixture";
import { shot } from "../e2e-public/helpers";
import {
  ANALYSIS_DESCRIPTION,
  OLD_NAME,
  SITE_DESCRIPTION,
  SITE_NAME,
  TITLE_ANALYSIS,
  TITLE_NOT_FOUND,
  VIEWPORT,
  expectIcons,
  expectLinkPreview,
  headTags,
  linkHrefs,
} from "../e2e-public/site";
import { REAL_ID } from "./snapshot";

const ANALYSIS = `/analysis/${REAL_ID}`;

test("'/' is Omnalynt, with the site's title, description, canonical link and link preview", async ({ page }, info) => {
  await page.goto("/");
  await shot(page, info, "snapshot-home");
  await expect(page.getByRole("heading", { level: 1, name: SITE_NAME, exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.body.innerText)).not.toContain(OLD_NAME);
  const head = await headTags(page);
  expect(head.title).toBe(SITE_NAME);
  expect(head.meta.description).toEqual([SITE_DESCRIPTION]);
  expect(linkHrefs(head, "canonical")).toEqual([TEST_SITE_URL]);
  expect(head.meta.viewport).toEqual([VIEWPORT]);
  expect(head.meta["color-scheme"]).toEqual(["dark"]);
  expectLinkPreview(head, { title: SITE_NAME, description: SITE_DESCRIPTION });
  expectIcons(head);
});

test("the real analysis page has its own title, description and canonical link, and keeps the link preview", async ({ page }) => {
  await page.goto("/");
  const card = expectLinkPreview(await headTags(page), { title: SITE_NAME, description: SITE_DESCRIPTION });
  await page.goto(ANALYSIS);
  const head = await headTags(page);
  expect(head.title).toBe(TITLE_ANALYSIS);
  expect(head.meta.description).toEqual([ANALYSIS_DESCRIPTION]);
  expect(linkHrefs(head, "canonical")).toEqual([`${TEST_SITE_URL}${ANALYSIS}`]);
  expect(head.meta.viewport).toEqual([VIEWPORT]);
  expect(expectLinkPreview(head, { title: TITLE_ANALYSIS, description: ANALYSIS_DESCRIPTION }), "the same card as '/'").toBe(card);
  expectIcons(head);
});

test("the 404 page has its own title, no canonical link, and noindex", async ({ page }, info) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  const head = await headTags(page);
  expect(head.title).toBe(TITLE_NOT_FOUND);
  expect(linkHrefs(head, "canonical")).toEqual([]);
  expect(head.meta.robots).toEqual(["noindex"]);
  await shot(page, info, "snapshot-not-found");
});
