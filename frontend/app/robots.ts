import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

// robots.txt, a static file in the public build. Indexing is allowed (owner
// ruling Q5, 2026-10-19): every page, and the sitemap at the site's address.
// The chart files stay out of search results through an X-Robots-Tag header
// (M2b.4c's vercel.json), not a Disallow here, which would also stop crawlers
// from rendering the charts in the page. Local mode has no site address and
// must never be indexed: everything is disallowed.
export default function robots(): MetadataRoute.Robots {
  if (SITE_URL === undefined) return { rules: { userAgent: "*", disallow: "/" } };
  return { rules: { userAgent: "*", allow: "/" }, sitemap: `${SITE_URL}/sitemap.xml` };
}
