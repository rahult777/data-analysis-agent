// The public build ships no axios and none of lib/api.ts's code (M3a):
// next.config.mjs puts lib/api-public.ts in lib/api.ts's place. The markers
// are three strings of axios's own source and two of lib/api.ts's error
// fallbacks; each is first found in its source, so a marker that no longer
// exists there fails the test instead of letting it pass. The build-output
// specs of both public suites share this module.

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

export const AXIOS_MARKERS: readonly string[] = ["X-XSRF-TOKEN", "Request failed with status code", "AxiosHeaders"];
export const API_MARKERS: readonly string[] = ["Failed to upload file.", "Failed to fetch analysis status."];

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((rel) => statSync(path.join(dir, rel)).isFile())
    .sort();
}

// The markers that their sources no longer hold (expected: none): axios's
// lib/ folder in node_modules and lib/api.ts, under the frontend folder.
export function markersMissingFromSources(frontend: string): string[] {
  const axiosLib = path.join(frontend, "node_modules", "axios", "lib");
  const axiosSource = filesUnder(axiosLib).map((rel) => readFileSync(path.join(axiosLib, rel), "utf8")).join("\n");
  const apiSource = readFileSync(path.join(frontend, "lib", "api.ts"), "utf8");
  return [
    ...AXIOS_MARKERS.filter((marker) => !axiosSource.includes(marker)).map((marker) => `axios's source lacks "${marker}"`),
    ...API_MARKERS.filter((marker) => !apiSource.includes(marker)).map((marker) => `lib/api.ts lacks "${marker}"`),
  ];
}

// Every marker in the files under an export's _next/static, one line per
// marker and file, and how many scripts were scanned.
export function clientMarkerHits(staticDir: string): { scripts: number; hits: string[] } {
  const files = filesUnder(staticDir);
  const hits: string[] = [];
  for (const rel of files) {
    const text = readFileSync(path.join(staticDir, rel), "latin1");
    for (const marker of [...AXIOS_MARKERS, ...API_MARKERS]) if (text.includes(marker)) hits.push(`"${marker}" in out/_next/static/${rel}`);
  }
  return { scripts: files.filter((rel) => rel.endsWith(".js")).length, hits };
}
