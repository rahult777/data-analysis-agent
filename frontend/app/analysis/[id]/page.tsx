import type { Metadata } from "next";

import { AnalysisResults } from "@/components/AnalysisResults";
import { isSnapshot } from "@/lib/mode";
import { snapshotAnalyses, snapshotAnalysis, snapshotNote } from "@/lib/snapshot";

import AnalysisPageClient from "./AnalysisPageClient";

// A saved analysis's public page has its own title, description and canonical
// link, and no openGraph (a page's openGraph would drop the site's card).
// Local mode shows the visitor's own analysis: "Analysis". It reads no
// snapshot data, so local mode never reaches the snapshot loader.
export function generateMetadata({ params }: { params: { id: string } }): Metadata {
  if (!isSnapshot) return { title: "Analysis" };
  return {
    title: "Example analysis",
    description:
      "A saved run of Omnalynt's four AI agents, shown read-only: the cleaning decisions, the charts and the report at three depths. Nothing the agents wrote has been corrected.",
    alternates: { canonical: `/analysis/${params.id}` },
  };
}

// Local mode renders the client page: live progress from the backend API, then
// the results. The public snapshot build (`npm run build:public`) exports one
// static page per saved analysis instead: the finished results only, already
// loaded from the snapshot JSON, with no progress view, status call,
// localStorage or fetch. Any other id is a 404.

// Every snapshot check runs here, so a broken snapshot fails the build with its
// own message. Local mode returns [] without touching the snapshot dir: `next
// build` marks the route ● with nothing prerendered, and `next start` renders
// each visited id on its first request and caches it.
export function generateStaticParams(): { id: string }[] {
  if (!isSnapshot) return [];
  return snapshotAnalyses().map(({ id }) => ({ id }));
}

export default function AnalysisPage({ params }: { params: { id: string } }) {
  if (!isSnapshot) return <AnalysisPageClient />;

  const analysis = snapshotAnalysis(params.id);
  const note = snapshotNote(params.id);
  return (
    // The skip link's target: tabIndex -1 lets <main> take the focus itself,
    // and as a focus target, not a control, it draws no ring.
    <main id="main" tabIndex={-1} className="w-full flex-1 px-6 py-8 outline-none sm:py-12 md:py-16">
      {/* Without JavaScript the closed layers stay in the page but hidden
          (Base UI gives each panel `hidden`): show them. A chart card's
          loading placeholder would pulse forever: hide it. An interactive
          chart cannot draw: show its card's line instead (ChartGrid.tsx).
          The selectors are unquoted because React escapes quotes inside
          <style>, which would drop the rule; keep "&", "<" and ">" out of it
          too. It sits outside the column below, where an empty element would
          still take a gap. */}
      <noscript>
        <style>
          {"[data-slot=accordion-content][hidden]{display:block!important}[data-chart-placeholder]{display:none!important}[data-chart-nojs][hidden]{display:flex!important}"}
        </style>
      </noscript>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Example analysis
          </h1>
        </header>
        {/* The manifest's note, plain text with no motion, so it reads without JavaScript.
            Its box keeps to the reading width: 29rem of text plus the padding. From lg it
            starts on the left edge of the results' 32.5rem spine (AnalysisResults.tsx):
            half the column less half the spine (M3a.2). */}
        <section aria-labelledby="about-this-example" className="flex max-w-[31.5rem] flex-col gap-2 rounded-md border border-border/60 bg-card/40 p-5 lg:ml-[calc(50%-16.25rem)]">
          <h2 id="about-this-example" className="text-xl italic leading-tight" style={{ fontFamily: "var(--font-display)" }}>
            About this example
          </h2>
          <p className="text-sm leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{note}</p>
        </section>
        <AnalysisResults analysisId={analysis.id} sessionId={null} initialData={analysis} />
      </div>
    </main>
  );
}
