// The site's identity as the e2e suites expect it (M2b.4a): the head metadata
// of every page and the files it points to; and its front door (M2b.4b): the
// landing page's copy and the header, footer and skip link every public page
// carries. The texts are independent literals, never read from the app; the
// builders write robots.txt and sitemap.xml the way Next serializes them.
// Shared by e2e-public, e2e-snapshot and the local suite (e2e/).

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page } from "@playwright/test";

import { TEST_GITHUB_PROFILE_URL, TEST_GITHUB_URL, TEST_SITE_URL } from "./fixture";

export const SITE_NAME = "Omnalynt";
export const OLD_NAME = "Data Analysis Agent";
export const SITE_DESCRIPTION =
  "Four AI agents profile, clean and analyze a spreadsheet, then write one report at three depths, pausing to ask a person about an uncertain domain, missing values and outliers.";
export const ANALYSIS_DESCRIPTION =
  "A saved run of Omnalynt's four AI agents, shown read-only: the cleaning decisions, the charts and the report at three depths. Nothing the agents wrote has been corrected.";
export const OG_IMAGE_ALT = "Omnalynt. An agentic analytics pipeline: LLM reasoning, deterministic execution, human checkpoints.";
export const TITLE_ANALYSIS = "Example analysis \u00b7 Omnalynt";
export const TITLE_LOCAL_ANALYSIS = "Analysis \u00b7 Omnalynt";
export const TITLE_NOT_FOUND = "Page not found \u00b7 Omnalynt";
// The dark background token (globals.css, .dark --background), oklch(0.145 0 0),
// as sRGB hex: some browsers and link-preview apps don't parse oklch here.
export const THEME_COLOR = "#0a0a0a";
// Next's default, which the layout's viewport export must keep.
export const VIEWPORT = "width=device-width, initial-scale=1";

// The icons and the link-preview card in app/, exported as files of their own.
export const BRAND_FILES = ["favicon.ico", "icon.svg", "apple-icon.png", "opengraph-image.png"];

export function robotsTxt(siteUrl: string): string {
  return `User-Agent: *\nAllow: /\n\nSitemap: ${siteUrl}/sitemap.xml\n`;
}

// Local mode: never indexed, and no address for a sitemap.
export const LOCAL_ROBOTS_TXT = "User-Agent: *\nDisallow: /\n\n";

export function sitemapXml(urls: string[]): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls.map((url) => `<url>\n<loc>${url}</loc>\n</url>`),
    "</urlset>",
    "",
  ].join("\n");
}

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// A PNG's pixel size, from its IHDR chunk.
export function pngSize(png: Buffer): { width: number; height: number } {
  expect(png.subarray(0, 8).equals(PNG_SIGNATURE), "a PNG file").toBe(true);
  expect(png.toString("latin1", 12, 16), "IHDR first").toBe("IHDR");
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

// The square sizes in an .ico file, each image a PNG of that size.
export function icoSizes(ico: Buffer): number[] {
  expect([ico.readUInt16LE(0), ico.readUInt16LE(2)], "an icon file").toEqual([0, 1]);
  const sizes: number[] = [];
  for (let i = 0; i < ico.readUInt16LE(4); i += 1) {
    const entry = 6 + 16 * i;
    const width = ico[entry] || 256;
    const height = ico[entry + 1] || 256;
    const image = ico.subarray(ico.readUInt32LE(entry + 12), ico.readUInt32LE(entry + 12) + ico.readUInt32LE(entry + 8));
    expect(pngSize(image), `icon ${i}`).toEqual({ width, height });
    expect(width, `icon ${i} is square`).toBe(height);
    sizes.push(width);
  }
  return sizes;
}

export interface HeadTags {
  title: string;
  // By name or property; every value, in document order.
  meta: Record<string, string[]>;
  links: { rel: string; href: string; type: string | null; sizes: string | null }[];
}

export async function headTags(page: Page): Promise<HeadTags> {
  return page.evaluate(() => {
    const meta: Record<string, string[]> = {};
    for (const element of Array.from(document.head.querySelectorAll("meta"))) {
      const key = element.getAttribute("name") ?? element.getAttribute("property");
      if (key !== null) (meta[key] ??= []).push(element.getAttribute("content") ?? "");
    }
    const links = Array.from(document.head.querySelectorAll("link")).map((element) => ({
      rel: element.getAttribute("rel") ?? "",
      href: element.getAttribute("href") ?? "",
      type: element.getAttribute("type"),
      sizes: element.getAttribute("sizes"),
    }));
    return { title: document.title, meta, links };
  });
}

export function linkHrefs(head: HeadTags, rel: string): string[] {
  return head.links.filter((link) => link.rel === rel).map((link) => link.href);
}

// The link preview every page takes from the root layout: the committed card
// (absolute, at the site's address) for Open Graph and Twitter alike, with the
// page's own title and description. Returns the card's URL.
export function expectLinkPreview(head: HeadTags, page: { title: string; description: string }): string {
  const image = head.meta["og:image"] ?? [];
  expect(image, "one link-preview image").toHaveLength(1);
  expect(image[0].startsWith(`${TEST_SITE_URL}/opengraph-image.png?`), image[0]).toBe(true);
  expect(head.meta).toMatchObject({
    "og:title": [page.title],
    "og:description": [page.description],
    "og:site_name": [SITE_NAME],
    "og:type": ["website"],
    "og:locale": ["en_US"],
    "og:image:type": ["image/png"],
    "og:image:width": ["1200"],
    "og:image:height": ["630"],
    "og:image:alt": [OG_IMAGE_ALT],
    "twitter:card": ["summary_large_image"],
    "twitter:title": [page.title],
    "twitter:description": [page.description],
    "twitter:image": image,
    "twitter:image:alt": [OG_IMAGE_ALT],
  });
  // A root og:url would reach every page; pages set none (no page-level openGraph).
  expect(head.meta["og:url"], "no og:url").toBeUndefined();
  return image[0];
}

export function expectIcons(head: HeadTags): void {
  const icons = head.links
    .filter((link) => link.rel === "icon" || link.rel === "apple-touch-icon")
    .map((link) => ({ ...link, href: link.href.replace(/\?[0-9a-f]+$/, "") }));
  expect(icons).toEqual([
    { rel: "icon", href: "/favicon.ico", type: "image/x-icon", sizes: expect.any(String) },
    { rel: "icon", href: "/icon.svg", type: "image/svg+xml", sizes: "any" },
    { rel: "apple-touch-icon", href: "/apple-icon.png", type: "image/png", sizes: "180x180" },
  ]);
}

// ---------------------------------------------------------------------------
// The front door (M2b.4b).
// ---------------------------------------------------------------------------

// The landing page ("/" in the public build), in reading order. No text says
// "upload", and the pauses ask "the person running it", never "you".
export const TAGLINE = "An agentic analytics pipeline: LLM reasoning, deterministic execution, human checkpoints.";
export const LANDING_LEAD =
  "Omnalynt runs a spreadsheet, a CSV or an Excel (.xlsx) file, through four AI agents. They profile it, clean it, analyze it and write one report at three depths: a summary for decision-makers, the full narrative for analysts, and the methods and limits for data scientists. Where a choice belongs to a person, the run stops and asks.";
export const LANDING_HOW = "How it works";
// The key to the steps' markers: a diamond (the mark's decision node) stands
// on the two steps that can pause, the Profiler's and the Cleaner's.
export const LANDING_KEY = "A diamond marks a step where the run can stop and ask a person.";
export const LANDING_AGENTS: ReadonlyArray<readonly [string, string]> = [
  [
    "Profiler",
    "Code computes each column's statistics and counts the exact duplicate rows. The model then says what kind of data this is, with a confidence score. Below 80 out of 100, the run stops and asks the person running it to confirm or correct that.",
  ],
  [
    "Cleaner",
    "Exact duplicate rows are removed first, in code. For the rest, the model chooses from a fixed set of operations, and code checks each one, runs it and writes the record of what was done; the reasons are the model's own words. When a column is more than 30% empty, or when the model judges that extreme values need a person's call, the run stops and asks the person running it.",
  ],
  [
    "Analyzer",
    'Code computes the correlations and draws every chart. A correlation that rests on fewer than 30 complete pairs of values is labelled "Cannot Determine" instead of being reported as a finding. Code also checks that the model\'s analysis covers each of the Profiler\'s top concerns and every strong correlation, and asks the model again when it does not.',
  ],
  [
    "Explainer",
    "Writes the report: the findings with recommended actions, the analyst's narrative with its confidence in each finding, the technical detail, and the questions this data cannot answer.",
  ],
];
export const LANDING_EXAMPLE_HEADING = "The example";
export const LANDING_EXAMPLE =
  "One saved run on a small synthetic sales file. Three of its cleaning decisions were made by the person running it, at pauses in the run, and are marked as theirs. Nothing the agents wrote has been corrected, so known errors are left in; a note at the top of the page says so and points out the clearest one.";
export const EXAMPLE_LINK = "Open the example analysis";
export const LANDING_READ_ONLY =
  "This site is a read-only copy. The agents run only on their author's own computer, so nothing here can start an analysis or take in a file.";

// The example's counts line, as the landing page writes it from the snapshot.
export function exampleCounts(rows: number, columns: number): string {
  return `${rows} rows and ${columns} columns before cleaning`;
}

// The header, footer and skip link of every public page.
export const SKIP_LINK = "Skip to main content";
export const HEADER_GITHUB = "GitHub";
export const FOOTER_SOURCE = "Source on GitHub";
export const FOOTER_NOTICES = "Third-party notices";
export const NOTICES_URL = "/third-party-notices.txt";
export const AUTHOR = "Rahul Tanikanti";
export const BUILT_BY = `Built by ${AUTHOR}`;

// The mark's path in app/icon.svg, which the header draws inline.
export const ICON_PATH = / d="([^"]+)"/.exec(readFileSync(path.join(__dirname, "..", "app", "icon.svg"), "utf8"))?.[1] ?? "";

async function hrefs(links: Locator): Promise<(string | null)[]> {
  return links.evaluateAll((elements) => elements.map((a) => a.getAttribute("href")));
}

// The header, footer and skip link a public page carries (owner ruling B2):
// one <header> and one <footer>, outside <main> and around it; the mark drawn
// inline from app/icon.svg's path, never an <img>; plain links to the home
// page, the repository, the third-party notices and the owner's profile; one
// h1, which the header's name is not.
export async function expectChrome(page: Page): Promise<void> {
  expect(ICON_PATH, "app/icon.svg has a path").not.toBe("");
  const header = page.getByRole("banner");
  const main = page.getByRole("main");
  const footer = page.getByRole("contentinfo");
  await expect(header, "one header landmark").toHaveCount(1);
  await expect(main, "one main landmark").toHaveCount(1);
  await expect(footer, "one footer landmark").toHaveCount(1);
  await expect(main).toHaveAttribute("id", "main");
  const order = await page.evaluate(() => {
    const mainElement = document.querySelector("main");
    const outside = (tag: string) => Array.from(document.querySelectorAll(tag)).filter((element) => !mainElement?.contains(element));
    const [headers, footers] = [outside("header"), outside("footer")];
    if (mainElement === null || headers.length !== 1 || footers.length !== 1) return `${headers.length} header(s), ${footers.length} footer(s) outside <main>`;
    const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    return before(headers[0], mainElement) && before(mainElement, footers[0]) ? "header, main, footer" : "out of order";
  });
  expect(order).toBe("header, main, footer");
  await expect(page.locator("h1"), "one h1").toHaveCount(1);

  const skip = page.locator('a[href="#main"]');
  await expect(skip).toHaveCount(1);
  await expect(skip).toHaveText(SKIP_LINK);
  await expect(page.getByRole("link").first(), "the skip link is the page's first link").toHaveText(SKIP_LINK);

  const headerLinks = header.getByRole("link");
  await expect(headerLinks).toHaveText([SITE_NAME, HEADER_GITHUB]);
  expect(await hrefs(headerLinks)).toEqual(["/", TEST_GITHUB_URL]);
  const mark = headerLinks.first().locator("svg");
  await expect(mark, "the mark, inline").toHaveCount(1);
  await expect(mark).toHaveAttribute("aria-hidden", "true");
  await expect(mark.locator("path")).toHaveAttribute("d", ICON_PATH);
  expect(await mark.evaluate((svg) => getComputedStyle(svg.querySelector("path") ?? svg).fill === getComputedStyle(svg).color), "drawn in the text color").toBe(true);

  const footerLinks = footer.getByRole("link");
  await expect(footerLinks).toHaveText([FOOTER_SOURCE, FOOTER_NOTICES, AUTHOR]);
  expect(await hrefs(footerLinks)).toEqual([TEST_GITHUB_URL, NOTICES_URL, TEST_GITHUB_PROFILE_URL]);
  await expect(footer).toContainText(BUILT_BY);

  await expect(header.locator("img, iframe"), "no image or frame in the header").toHaveCount(0);
  await expect(footer.locator("img, iframe"), "no image or frame in the footer").toHaveCount(0);
}

// ---------------------------------------------------------------------------
// The charts and the host's headers (M2b.4c).
// ---------------------------------------------------------------------------

// The line an interactive chart's card shows without JavaScript.
export const CHART_NOJS_LINE = "This interactive chart needs JavaScript.";
// The link under every PNG chart; its accessible name adds the chart's label
// in parentheses, "Open full size (<label>)".
export const FULL_SIZE = "Open full size";

// The two header sets frontend/vercel.json gives the public site, as a
// response carries them (header names in lower case): the page set everywhere
// but under /demo/charts/, the chart set there. Literals, never read from
// vercel.json (lib/vercel-config.test.mjs pins the file itself).
export const PAGE_HEADERS: Readonly<Record<string, string>> = {
  "content-security-policy":
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
};
export const CHART_HEADERS: Readonly<Record<string, string>> = {
  "content-security-policy": "script-src 'self' 'unsafe-inline'; sandbox allow-scripts",
  "x-content-type-options": "nosniff",
  "x-robots-tag": "noindex",
  "referrer-policy": "no-referrer",
};

// A response carries exactly one of the two sets: every header of the set its
// path takes, with that set's value, and none of the other set's own headers.
// Soft, so one run names every miss.
export function expectOneHeaderSet(url: string, headers: Record<string, string>): void {
  const { pathname } = new URL(url);
  const [want, other] = pathname.startsWith("/demo/charts/") ? [CHART_HEADERS, PAGE_HEADERS] : [PAGE_HEADERS, CHART_HEADERS];
  for (const [key, value] of Object.entries(want)) expect.soft(headers[key], `${pathname}: ${key}`).toBe(value);
  for (const key of Object.keys(other)) {
    if (!(key in want)) expect.soft(headers[key], `${pathname}: no ${key}`).toBeUndefined();
  }
}
