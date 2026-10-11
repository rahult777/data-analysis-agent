import { FileUpload } from "@/components/FileUpload";
import { isSnapshot } from "@/lib/mode";
import { snapshotAnalyses } from "@/lib/snapshot";

export default function Home() {
  if (isSnapshot) return <SnapshotHome />;

  return (
    <main className="min-h-screen w-full px-6 py-8 sm:py-12 md:py-16">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Data Analysis Agent
          </h1>
          <p
            className="text-base sm:text-lg text-muted-foreground"
            style={{ fontFamily: "var(--font-sans)" }}
          >
            Upload your data. Get intelligent analysis.
          </p>
        </header>
        <FileUpload />
      </div>
    </main>
  );
}

// "/" in the public snapshot build: a minimal placeholder that links to each
// saved analysis, never the upload UI (the landing page comes later). Plain
// <a> links: next/link would add its router code to this page (owner ruling
// D7).
function SnapshotHome() {
  const analyses = snapshotAnalyses();
  return (
    <main className="min-h-screen w-full px-6 py-8 sm:py-12 md:py-16">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Data Analysis Agent
          </h1>
          <p
            className="text-base sm:text-lg text-muted-foreground"
            style={{ fontFamily: "var(--font-sans)" }}
          >
            Example analyses, saved as{" "}
            {/* Never broken at its hyphen; DM Sans may lack a non-breaking hyphen glyph. */}
            <span className="whitespace-nowrap">read-only</span> copies.
          </p>
        </header>
        <ul className="flex flex-col gap-3">
          {analyses.map((analysis) => (
            <li key={analysis.id}>
              <a
                href={`/analysis/${analysis.id}`}
                className="flex min-h-11 flex-col gap-1 rounded-md border border-border/60 bg-card/40 px-5 py-4 transition-colors hover:border-primary/50"
              >
                {/* An uploaded name often has no spaces; wrap it anywhere rather than widen the page at 320 px. */}
                <span className="min-w-0 font-mono text-sm tracking-wide text-muted-foreground [overflow-wrap:anywhere]">
                  {analysis.filename}
                </span>
                <span className="text-base text-foreground">Open the analysis</span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
