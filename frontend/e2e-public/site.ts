// The site's identity as the e2e suites expect it (M2b.4a): the head metadata
// of every page and the files it points to. The texts are independent literals,
// never read from the app; the builders write robots.txt and sitemap.xml the
// way Next serializes them. Shared by e2e-public, e2e-snapshot and the local
// suite (e2e/).

import { expect, type Page } from "@playwright/test";

import { TEST_SITE_URL } from "./fixture";

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
