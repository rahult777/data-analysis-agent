// Renders the site's raster brand assets from their sources, offline (M2b.4a):
//   app/favicon.ico          the mark's tile (app/icon.svg) at 16, 32 and 48 px, as PNGs in an icon file;
//   app/apple-icon.png       the tile at 180 px, square and opaque (iOS rounds the corners itself);
//   app/opengraph-image.png  the link-preview card, 1200 x 630, from scripts/brand/og-card.html.
// The card uses the site's own font files (DM Sans, Instrument Serif italic),
// found through the built CSS in .next/static/css, so run `npm run build` or
// `npm run build:public` first. Headless Chromium from @playwright/test renders
// everything, and every network request is refused. The same sources, font
// files and Chromium give the same bytes.
//
// Usage, in frontend/:
//   node scripts/brand-assets.mjs              write the three files into app/
//   node scripts/brand-assets.mjs --check      render them and compare with app/ byte for byte (exit 1 on a difference)
//   node scripts/brand-assets.mjs --out <dir>  write them into <dir>

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP = path.join(FRONTEND, "app");
const TEMPLATE = path.join(FRONTEND, "scripts", "brand", "og-card.html");
const FAVICON_SIZES = [16, 32, 48];
const APPLE_SIZE = 180;
const CARD = { width: 1200, height: 630 };
const USAGE = "usage: node scripts/brand-assets.mjs [--check | --out <dir>]";

class UsageError extends Error {}

/**
 * @param {string[]} argv
 * @returns {{ check: boolean, out: string }}
 */
function parseArgs(argv) {
  if (argv.length === 0) return { check: false, out: APP };
  if (argv.length === 1 && argv[0] === "--check") return { check: true, out: APP };
  if (argv.length === 2 && argv[0] === "--out" && !argv[1].startsWith("-")) return { check: false, out: path.resolve(argv[1]) };
  throw new UsageError(USAGE);
}

/**
 * The latin faces of the two brand fonts, from the built CSS: a production
 * build minifies it into .next/static/css/<hash>.css, next dev writes
 * .next/static/css/app/layout.css; both point at the same files in
 * .next/static/media.
 * @returns {{ sans: string, serifItalic: string }}
 */
function builtFonts() {
  const cssDir = path.join(FRONTEND, ".next", "static", "css");
  const sheets = fs.existsSync(cssDir)
    ? fs.readdirSync(cssDir, { recursive: true, encoding: "utf8" }).filter((name) => name.endsWith(".css"))
    : [];
  if (sheets.length === 0) {
    throw new Error("No built CSS in .next/static/css: run npm run build or npm run build:public first (the card uses the site's own font files).");
  }
  /** @type {{ family: string, style: string, file: string }[]} */
  const faces = [];
  for (const sheet of sheets) {
    const css = fs.readFileSync(path.join(cssDir, sheet), "utf8");
    for (const block of css.match(/@font-face\s*\{[^}]*\}/g) ?? []) {
      const family = /font-family:\s*["']?([^;"']+)/.exec(block)?.[1] ?? "";
      const style = /font-style:\s*([a-z]+)/.exec(block)?.[1] ?? "normal";
      const media = /url\(["']?\/_next\/(static\/media\/[^)"']+\.woff2)["']?\)/.exec(block)?.[1];
      const range = (/unicode-range:\s*([^;}]+)/.exec(block)?.[1] ?? "").trim();
      // The latin subset starts at U+0000 (minified CSS writes U+0000-00FF as u+00??).
      if (media !== undefined && /^u\+(0000-00ff|00\?\?)/i.test(range)) {
        faces.push({ family, style, file: path.join(FRONTEND, ".next", media) });
      }
    }
  }
  /** @param {string} prefix @param {string} style */
  const pick = (prefix, style) => {
    const face = faces.find((f) => f.family.startsWith(prefix) && !f.family.includes("Fallback") && f.style === style);
    if (face === undefined || !fs.existsSync(face.file)) {
      throw new Error(`The built CSS names no latin ${prefix}* ${style} font file in .next/static/media: rebuild (npm run build).`);
    }
    return face.file;
  };
  return { sans: pick("__DM_Sans_", "normal"), serifItalic: pick("__Instrument_Serif_", "italic") };
}

/**
 * @param {RegExp} pattern a pattern with one group
 * @param {string} text
 * @param {string} what
 */
function only(pattern, text, what) {
  const found = [...text.matchAll(pattern)];
  if (found.length !== 1) throw new Error(`app/icon.svg must hold exactly one ${what}; found ${found.length}.`);
  return found[0][1];
}

/** @param {Buffer} data */
const sha256 = (data) => createHash("sha256").update(data).digest("hex");

/** @param {string} file */
const dataUrl = (file) => `data:font/woff2;base64,${fs.readFileSync(file).toString("base64")}`;

/**
 * PNGs of the same square image at several sizes, in one icon file.
 * @param {{ size: number, png: Buffer }[]} images
 */
function iconFile(images) {
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, png }, i) => {
    const entry = 6 + 16 * i;
    header.writeUInt8(size, entry);
    header.writeUInt8(size, entry + 1);
    header.writeUInt16LE(1, entry + 4); // color planes
    header.writeUInt16LE(32, entry + 6); // bits per pixel
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  return Buffer.concat([header, ...images.map((image) => image.png)]);
}

/**
 * @param {{ sans: string, serifItalic: string }} fonts
 * @returns {Promise<{ files: Record<string, Buffer>, chromiumVersion: string }>}
 */
async function render(fonts) {
  const svg = fs.readFileSync(path.join(APP, "icon.svg"), "utf8");
  const tile = only(/<rect\b[^>]*\sfill="(#[0-9a-fA-F]{6})"/g, svg, "<rect> with a fill (the tile)");
  const card = fs
    .readFileSync(TEMPLATE, "utf8")
    .replace("{{DM_SANS}}", dataUrl(fonts.sans))
    .replace("{{INSTRUMENT_SERIF_ITALIC}}", dataUrl(fonts.serifItalic));
  if (card.includes("{{")) throw new Error("scripts/brand/og-card.html has a placeholder this script does not fill.");

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: CARD.width, height: CARD.height }, deviceScaleFactor: 1 });
    let requests = 0;
    await page.route("**/*", (route) => {
      requests += 1;
      return route.abort();
    });

    // The tile at `size`, transparent around its rounded corners, or on `background`.
    /** @param {number} size @param {string | undefined} background */
    const tileAt = async (size, background) => {
      const sized = svg.replace("<svg ", `<svg width="${size}" height="${size}" `);
      await page.setContent(
        `<!doctype html><html><head><style>*{margin:0}html,body{background:${background ?? "transparent"}}svg{display:block}</style></head><body>${sized}</body></html>`,
      );
      return page.screenshot({ type: "png", omitBackground: background === undefined, clip: { x: 0, y: 0, width: size, height: size } });
    };

    const favicon = [];
    for (const size of FAVICON_SIZES) favicon.push({ size, png: await tileAt(size, undefined) });
    // Full bleed: the page behind the tile has the tile's own color.
    const appleIcon = await tileAt(APPLE_SIZE, tile);

    await page.setContent(card);
    await page.evaluate(() => document.fonts.ready);
    const faces = await page.evaluate(() => Array.from(document.fonts, (face) => `${face.family} ${face.style} ${face.status}`));
    if (faces.length !== 2 || !faces.every((face) => face.endsWith(" loaded"))) {
      throw new Error(`The card's two fonts did not load: ${faces.join(", ")}`);
    }
    const ogImage = await page.screenshot({ type: "png", clip: { x: 0, y: 0, ...CARD } });

    if (requests > 0) throw new Error(`${requests} network request(s) were attempted; the brand assets render offline.`);
    return {
      files: { "favicon.ico": iconFile(favicon), "apple-icon.png": appleIcon, "opengraph-image.png": ogImage },
      chromiumVersion: browser.version(),
    };
  } finally {
    await browser.close();
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const fonts = builtFonts();
  const { files, chromiumVersion } = await render(fonts);
  console.log(`Chromium ${chromiumVersion}`);
  for (const [label, file] of [["DM Sans", fonts.sans], ["Instrument Serif italic", fonts.serifItalic]]) {
    console.log(`font ${label}: .next/${path.relative(path.join(FRONTEND, ".next"), file)} sha256 ${sha256(fs.readFileSync(file))}`);
  }
  let differences = 0;
  for (const [name, data] of Object.entries(files)) {
    const line = `${name} ${data.length} B sha256 ${sha256(data)}`;
    if (args.check) {
      const target = path.join(APP, name);
      const same = fs.existsSync(target) && fs.readFileSync(target).equals(data);
      if (!same) differences += 1;
      console.log(`${same ? "MATCH" : "DIFFERS"} ${line}`);
    } else {
      fs.mkdirSync(args.out, { recursive: true });
      fs.writeFileSync(path.join(args.out, name), data);
      console.log(`wrote ${args.out === APP ? `app/${name}` : path.join(args.out, name)}: ${line}`);
    }
  }
  if (args.check) {
    console.log(differences === 0 ? "The brand assets match app/." : `${differences} brand asset(s) differ from app/.`);
    process.exitCode = differences === 0 ? 0 : 1;
  }
}

main().catch((error) => {
  console.error(error instanceof UsageError ? error.message : `brand-assets: ${error.message}`);
  process.exitCode = error instanceof UsageError ? 2 : 1;
});
