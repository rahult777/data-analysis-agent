// The headers frontend/vercel.json gives a path (M2b.4c), matched as Vercel
// matches a header rule's `source`: path-to-regexp syntax, case-sensitive.
// Next ships a copy of path-to-regexp (next/dist/compiled/path-to-regexp), so
// this needs no dependency. Pure apart from loading it; used by
// e2e-public/serve-static.mjs, which serves the public build the way Vercel
// does, and by lib/vercel-config.test.mjs.

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { pathToRegexp } = require("next/dist/compiled/path-to-regexp");

/**
 * vercel.json's header rules, each with its source compiled to a matcher.
 * @param {{ headers?: { source: string, headers: { key: string, value: string }[] }[] }} config
 * @returns {{ source: string, matcher: RegExp, headers: { key: string, value: string }[] }[]}
 */
export function vercelHeaderRules(config) {
  return (config.headers ?? []).map((rule) => ({
    source: rule.source,
    matcher: pathToRegexp(rule.source, [], { strict: true, sensitive: true, delimiter: "/" }),
    headers: rule.headers,
  }));
}

/**
 * The headers of every rule whose source matches the path, in order.
 * @param {{ matcher: RegExp, headers: { key: string, value: string }[] }[]} rules
 * @param {string} pathname
 * @returns {{ key: string, value: string }[]}
 */
export function headersFor(rules, pathname) {
  return rules.filter((rule) => rule.matcher.test(pathname)).flatMap((rule) => rule.headers);
}
