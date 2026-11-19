import path from "node:path";
import { fileURLToPath } from "node:url";

import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

import { siteSettingsProblems } from "./lib/site-settings.mjs";

// NEXT_PUBLIC_DATA_SOURCE picks the data source at build time: unset or empty
// is local mode (the backend API); exactly "snapshot" is the public snapshot
// build (`npm run build:public`), a static export that renders saved analyses
// from built-in JSON. This file is its only validator; lib/mode.ts reads it.
// Next loads .env* files before this file, so never set it in a .env file.
//
// The public build also needs two site settings: NEXT_PUBLIC_SITE_URL, the
// site's address (canonical links, the link preview, the sitemap), and
// NEXT_PUBLIC_GITHUB_URL, its GitHub repository. This file is their only
// validator too (the rules: lib/site-settings.mjs) and refuses the public
// build when either is missing or invalid; lib/site.ts reads them, and local
// mode ignores them. Unlike the flag, they may be set in .env.local.
function isSnapshotBuild() {
  const value = process.env.NEXT_PUBLIC_DATA_SOURCE;
  if (value === undefined || value === "") return false;
  if (value === "snapshot") return true;
  throw new Error(
    `NEXT_PUBLIC_DATA_SOURCE must be unset, empty or "snapshot"; got ${JSON.stringify(value)}.`,
  );
}

// The public build's stand-in for lib/api.ts (M3a): lib/api-public.ts has the
// same exports, with no axios and no request, so neither axios nor
// lib/api.ts's code reaches the public site's chunks. It is matched on the
// resolved file, however an import names it: Next rewrites the "@/" paths
// before webpack's resolve.alias would see them. It is a webpack plugin, which
// Turbopack does not run (tasks.md, the Next upgrade).
const LIB = path.join(path.dirname(fileURLToPath(import.meta.url)), "lib");
const API_TS = path.join(LIB, "api.ts");
const API_PUBLIC = path.join(LIB, "api-public.ts");

// NormalModuleReplacementPlugin's function form: for the resolved lib/api.ts
// (its path compared as a string), the resource and the request and
// userRequest that end with it all name lib/api-public.ts, so the module's
// identifier and webpack's cache key are the stand-in's too. A request before
// resolve, and any other file, is left alone.
/** @param {{ createData?: { resource: string, request: string, userRequest: string } }} resolveData */
function useApiPublic(resolveData) {
  const data = resolveData.createData;
  if (!data || data.resource !== API_TS) return;
  for (const key of /** @type {const} */ (["request", "userRequest"])) {
    if (!data[key].endsWith(API_TS)) throw new Error(`next.config.mjs: lib/api.ts's ${key} does not end with its path: ${data[key]}`);
    data[key] = data[key].slice(0, -API_TS.length) + API_PUBLIC;
  }
  data.resource = API_PUBLIC;
}

/**
 * @param {string} phase
 * @returns {import('next').NextConfig}
 */
export default function nextConfig(phase) {
  const snapshot = isSnapshotBuild();
  // Under `next dev` a static export answers an unlisted id with a server
  // error ("missing param … in generateStaticParams()"), not a 404.
  if (snapshot && phase === PHASE_DEVELOPMENT_SERVER) {
    throw new Error("snapshot mode is build-only; use npm run build:public");
  }
  if (snapshot) {
    const problems = siteSettingsProblems(process.env);
    if (problems.length > 0) {
      throw new Error(
        [
          "The public build (npm run build:public) needs both site settings, set inline or in frontend/.env.local:",
          ...problems.map((problem) => `  - ${problem}`),
        ].join("\n"),
      );
    }
  }
  // Neither mode optimizes images (M3a): the app uses no next/image, and
  // /_next/image then answers 404 under next dev and next start.
  const images = { unoptimized: true };
  if (!snapshot) return { images };
  return {
    output: "export",
    images,
    webpack(config, { webpack }) {
      config.plugins.push(new webpack.NormalModuleReplacementPlugin(/api\.ts$/, useApiPublic));
      return config;
    },
  };
}
