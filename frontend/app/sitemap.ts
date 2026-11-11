import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";
import { snapshotAnalyses } from "@/lib/snapshot";

// sitemap.xml, a static file in the public build: "/" and each saved analysis
// at the site's address ("/" as the bare origin, like its canonical link). No
// dates or priorities, so the file changes only with the analyses. Local mode
// has no site address: an empty sitemap, without calling the snapshot loader
// (it throws outside the public build).
export default function sitemap(): MetadataRoute.Sitemap {
  if (SITE_URL === undefined) return [];
  return [{ url: SITE_URL }, ...snapshotAnalyses().map(({ id }) => ({ url: `${SITE_URL}/analysis/${id}` }))];
}
