import type { Metadata } from "next";
import type { ReactElement } from "react";

import { FileUpload } from "@/components/FileUpload";
import { isSnapshot } from "@/lib/mode";
import { formatCount } from "@/lib/results";
import { snapshotAnalyses } from "@/lib/snapshot";

// The site's root: its canonical link in the public build (the title is the
// layout's default). Local mode has no site address, so it sets none, like
// the analysis page.
export const metadata: Metadata = isSnapshot ? { alternates: { canonical: "/" } } : {};

export default function Home() {
  if (isSnapshot) return <Landing />;

  return (
    <main className="min-h-screen w-full px-6 py-8 sm:py-12 md:py-16">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Omnalynt
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

// "/" in the public snapshot build: the landing page (M2b.4b). A static server
// component with no motion, so all of it reads without JavaScript. Its copy
// states only what the code or the published snapshot shows (decisions.md,
// M2b.4b), never says "upload", and speaks of "the person running it": a
// visitor here can run nothing. Plain <a> links: next/link would add its
// router code to this page (owner ruling D7).
const TAGLINE = "An agentic analytics pipeline: LLM reasoning, deterministic execution, human checkpoints.";

const LEAD =
  "Omnalynt runs a spreadsheet, a CSV or an Excel (.xlsx) file, through four AI agents. They profile it, clean it, analyze it and write one report at three depths: a summary for decision-makers, the full narrative for analysts, and the methods and limits for data scientists. Where a choice belongs to a person, the run stops and asks.";

// The four agents, in the order they run. `pauses` marks the two steps where
// the run can stop for a person (the Profiler's domain question; the Cleaner's
// missing-value and outlier questions): the page draws a diamond, the mark's
// decision node, on those two.
const AGENTS: ReadonlyArray<{ name: string; pauses: boolean; text: string }> = [
  {
    name: "Profiler",
    pauses: true,
    text: "Code computes each column's statistics and counts the exact duplicate rows. The model then says what kind of data this is, with a confidence score. Below 80 out of 100, the run stops and asks the person running it to confirm or correct that.",
  },
  {
    name: "Cleaner",
    pauses: true,
    text: "Exact duplicate rows are removed first, in code. For the rest, the model chooses from a fixed set of operations, and code checks each one, runs it and writes the record of what was done; the reasons are the model's own words. When a column is more than 30% empty, or when the model judges that extreme values need a person's call, the run stops and asks the person running it.",
  },
  {
    name: "Analyzer",
    pauses: false,
    text: 'Code computes the correlations and draws every chart. A correlation that rests on fewer than 30 complete pairs of values is labelled "Cannot Determine" instead of being reported as a finding. Code also checks that the model\'s analysis covers each of the Profiler\'s top concerns and every strong correlation, and asks the model again when it does not.',
  },
  {
    name: "Explainer",
    pauses: false,
    text: "Writes the report: the findings with recommended actions, the analyst's narrative with its confidence in each finding, the technical detail, and the questions this data cannot answer.",
  },
];

const KEY = "A diamond marks a step where the run can stop and ask a person.";

// About the one saved example. These sentences are fixed copy: the snapshot
// e2e (e2e-snapshot/landing.spec.ts) pins each fact in them to the snapshot's
// own JSON, so a re-export that changes one fails until the copy follows.
const EXAMPLE =
  "One saved run on a small synthetic sales file. Three of its cleaning decisions were made by the person running it, at pauses in the run, and are marked as theirs. Nothing the agents wrote has been corrected, so known errors are left in; a note at the top of the page says so and points out the clearest one.";

const READ_ONLY =
  "This site is a read-only copy. The agents run only on their author's own computer, so nothing here can start an analysis or take in a file.";

// The link to an example's analysis, with a 44 px tap target. The page shows
// it twice for the first example (owner ruling R2), so the two stay the same.
function ExampleLink({ id }: { id: string }): ReactElement {
  return (
    <a
      href={`/analysis/${id}`}
      className="inline-flex min-h-11 items-center self-start text-base text-foreground underline underline-offset-4 hover:text-primary"
    >
      Open the example analysis
    </a>
  );
}

function Landing(): ReactElement {
  // Each example's file name and original size come from the snapshot itself.
  // The rules refuse an empty snapshot (lib/snapshot-rules.mjs), so there is
  // always a first example.
  const analyses = snapshotAnalyses();
  const [first] = analyses;
  return (
    // The skip link's target: tabIndex -1 lets <main> take the focus itself,
    // and as a focus target, not a control, it draws no ring.
    <main id="main" tabIndex={-1} className="w-full flex-1 px-6 py-8 outline-none sm:py-12 md:py-16">
      {/* A reading width: about 70 characters of the 16 px text to a line. */}
      <div className="mx-auto flex w-full max-w-[34rem] flex-col gap-12">
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Omnalynt
          </h1>
          <p className="text-balance text-base text-muted-foreground sm:text-lg">{TAGLINE}</p>
        </header>

        {/* Under the lead, the way to the example, so a visitor on a phone
            need not scroll past the four agents to find it (owner ruling R2). */}
        <div className="flex flex-col gap-3">
          <p className="text-base leading-relaxed text-foreground/90">{LEAD}</p>
          <ExampleLink id={first.id} />
        </div>

        <section aria-labelledby="how-it-works" className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h2 id="how-it-works" className="text-2xl italic leading-tight" style={{ fontFamily: "var(--font-display)" }}>
              How it works
            </h2>
            <p className="flex items-start gap-3 text-sm text-muted-foreground">
              <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rotate-45 bg-foreground" />
              <span>{KEY}</span>
            </p>
          </div>
          {/* The pipeline: one line through the four steps, as in the mark. */}
          <ol className="flex flex-col">
            {AGENTS.map((agent, index) => (
              <li key={agent.name} className="flex gap-4">
                <div aria-hidden="true" className="relative flex w-3 shrink-0 justify-center">
                  {/* The line runs on to the next step's marker, which is drawn over its end. */}
                  {index < AGENTS.length - 1 && <span className="absolute -bottom-2.5 top-3 w-px bg-muted-foreground/40" />}
                  {agent.pauses ? (
                    <span data-checkpoint="" className="relative mt-2 size-3 rotate-45 bg-foreground" />
                  ) : (
                    <span className="relative mt-2.5 size-2 rounded-full bg-muted-foreground" />
                  )}
                </div>
                <div className={`flex min-w-0 flex-col gap-2 ${index < AGENTS.length - 1 ? "pb-8" : ""}`}>
                  <h3 className="text-xl italic leading-tight" style={{ fontFamily: "var(--font-display)" }}>
                    {agent.name}
                  </h3>
                  <p className="text-base leading-relaxed text-foreground/90">{agent.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="the-example" className="flex flex-col gap-4">
          <h2 id="the-example" className="text-2xl italic leading-tight" style={{ fontFamily: "var(--font-display)" }}>
            The example
          </h2>
          <p className="text-base leading-relaxed text-foreground/90">{EXAMPLE}</p>
          <ul className="flex flex-col gap-3">
            {analyses.map((analysis) => (
              <li key={analysis.id} className="flex flex-col gap-1 rounded-md border border-border/60 bg-card/40 px-5 pb-2 pt-4">
                {/* A file's name often has no spaces; wrap it anywhere rather than widen the page at 320 px. */}
                <span className="min-w-0 font-mono text-sm tracking-wide text-foreground [overflow-wrap:anywhere]">
                  {analysis.filename}
                </span>
                <span className="text-sm text-muted-foreground">
                  {`${formatCount(analysis.row_count)} rows and ${formatCount(analysis.column_count)} columns before cleaning`}
                </span>
                <ExampleLink id={analysis.id} />
              </li>
            ))}
          </ul>
        </section>

        <p className="max-w-[29rem] text-sm leading-relaxed text-muted-foreground">{READ_ONLY}</p>
      </div>
    </main>
  );
}
