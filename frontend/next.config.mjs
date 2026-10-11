import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

// NEXT_PUBLIC_DATA_SOURCE picks the data source at build time: unset or empty
// is local mode (the backend API); exactly "snapshot" is the public snapshot
// build (`npm run build:public`), a static export that renders saved analyses
// from built-in JSON. This file is its only validator; lib/mode.ts reads it.
// Next loads .env* files before this file, so never set it in a .env file.
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
  return snapshot ? { output: "export" } : {};
}
