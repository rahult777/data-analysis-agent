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
  return snapshot ? { output: "export" } : {};
}
