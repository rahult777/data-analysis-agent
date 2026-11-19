// Every file a public build may export (M3a): the exact names of the pages,
// the site's own files and the charts, and patterns for Next's content-hashed
// files under _next/static. Anything else (a file put in public/, an image a
// component imports, a source map) fails the build-output specs of both public
// suites, which share this module.

const HASH = "[0-9a-f]{16}";

// Next's own output: the build's two manifests (under its 21-character build
// id), the scripts, the stylesheet and the self-hosted fonts.
export const NEXT_STATIC_PATTERNS: readonly RegExp[] = [
  /^_next\/static\/[A-Za-z0-9_-]{21}\/_(buildManifest|ssgManifest)\.js$/,
  new RegExp(`^_next/static/chunks/(framework|main|main-app|polyfills|webpack)-${HASH}\\.js$`),
  new RegExp(`^_next/static/chunks/([0-9]+|[0-9a-f]{8})-${HASH}\\.js$`),
  new RegExp(`^_next/static/chunks/app/(layout|page|not-found|_not-found/page|analysis/\\[id\\]/page)-${HASH}\\.js$`),
  new RegExp(`^_next/static/chunks/pages/_(app|error)-${HASH}\\.js$`),
  new RegExp(`^_next/static/css/${HASH}\\.css$`),
  new RegExp(`^_next/static/media/${HASH}-s(\\.p)?\\.woff2$`),
];

// The site's own files at the root: the pages, robots.txt and the sitemap,
// the icons and the link-preview card, and the third-party notice.
export const ROOT_FILES: readonly string[] = [
  "404.html",
  "index.html",
  "index.txt",
  "robots.txt",
  "sitemap.xml",
  "favicon.ico",
  "icon.svg",
  "apple-icon.png",
  "opengraph-image.png",
  "third-party-notices.txt",
];

// The exact files of a build: the root files, each analysis's page and RSC
// payload, and the chart files.
export function exactFiles(ids: readonly string[], charts: readonly string[]): string[] {
  return [...ROOT_FILES, ...ids.flatMap((id) => [`analysis/${id}.html`, `analysis/${id}.txt`]), ...charts.map((name) => `demo/charts/${name}`)];
}

// What never ships, whatever the lists say: a source map, a dotfile (any
// segment) or an .env-like file: a segment with env as a whole dot-separated
// part (.env, .env.local, env, env.json, x.env), not a chart named after an env
// column.
export function forbiddenKind(rel: string): string | null {
  const segments = rel.split("/");
  if (rel.endsWith(".map")) return "a source map";
  if (segments.some((segment) => segment.startsWith("."))) return "a dotfile";
  if (segments.some((segment) => /(^|\.)env(\.|$)/i.test(segment))) return "an .env-like file";
  return null;
}

// The files of `files` that are forbidden, or neither exact nor Next's.
export function unexpectedFiles(files: readonly string[], exact: readonly string[]): string[] {
  const allowed = new Set(exact);
  return files.filter((rel) => forbiddenKind(rel) !== null || !(allowed.has(rel) || NEXT_STATIC_PATTERNS.some((pattern) => pattern.test(rel))));
}
