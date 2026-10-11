import { AnalysisResults } from "@/components/AnalysisResults";
import { isSnapshot } from "@/lib/mode";
import { snapshotAnalyses, snapshotAnalysis } from "@/lib/snapshot";

import AnalysisPageClient from "./AnalysisPageClient";

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
  return (
    <main className="min-h-screen w-full px-6 py-8 sm:py-12 md:py-16">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Analysis
          </h1>
        </header>
        <AnalysisResults analysisId={analysis.id} sessionId={null} initialData={analysis} />
      </div>
    </main>
  );
}
