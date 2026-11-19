import { API_URL, isSnapshot } from "./mode";

// Where a chart file is served. Local mode: the backend's /charts route. The
// snapshot build copies the charts into out/demo/charts/ and Vercel strips
// ".html" from exported files, so an HTML chart's URL drops it; PNG names stay.
// Its own module, apart from lib/api.ts, so ChartGrid imports no axios (M3a).
export function chartUrl(filename: string): string {
  if (isSnapshot) return `/demo/charts/${filename.replace(/\.html$/, "")}`;
  return `${API_URL}/charts/${filename}`;
}
