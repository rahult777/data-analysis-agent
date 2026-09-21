"use client";

import { motion } from "framer-motion";
import { ArrowRight, HelpCircle } from "lucide-react";

import type { CleaningDecision } from "@/lib/types";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { CodeBlock } from "@/components/CodeBlock";
import { chartAnchorId, parseChartFilename } from "@/components/ChartGrid";
import {
  CorrelationMatrix,
  pairKey,
  type CorrelationMatrixData,
} from "@/components/CorrelationMatrix";

// ---------------------------------------------------------------------------
// Narrow shapes for the raw JSONB dicts (stored raw — see decisions.md
// 2026-06-04). These mirror explainer_system.md §13; every field is optional
// because nothing enforces the LLM output contract between the model and here.
// ---------------------------------------------------------------------------

interface ExecutiveBullet {
  finding?: string;
  context?: string;
  recommended_action?: string;
}

interface AnalystLayer {
  narrative?: string;
  chart_references?: string[];
}

interface TechnicalLayer {
  statistical_methodology?: string;
  code_blocks?: string[];
  limitations?: string;
  sophistication_suggestions?: string;
  self_evaluation_notes?: string;
  lead_override_note?: string | null;
}

interface OpenQuestion {
  question?: string;
  why_unanswerable?: string;
  what_data_would_answer?: string;
}

// --- unknown-safe accessors (strict mode, no `any`) ------------------------

function asString(v: unknown): string | undefined {
  return typeof v === "string" && v.trim().length > 0 ? v : undefined;
}

function asRecord(v: unknown): Record<string, unknown> | undefined {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : undefined;
}

function asStringArray(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string")
    : [];
}

function readBullets(executiveSummary: Record<string, unknown> | null): ExecutiveBullet[] {
  const raw = executiveSummary?.bullets;
  if (!Array.isArray(raw)) return [];
  return raw.map((b) => {
    const r = asRecord(b) ?? {};
    return {
      finding: asString(r.finding),
      context: asString(r.context),
      recommended_action: asString(r.recommended_action),
    };
  });
}

// analysis_report.correlation_matrix is Python-computed (analyzer.py
// compute_correlation_matrix): { matrix: dict-of-dicts, symmetric, diagonal
// included, values number | null; strong_pairs: [{col1, col2, ...}] }. Not
// .correlation, which is the LLM-authored qualitative object. JSONB does not
// preserve DataFrame column order, so columns are sorted alphabetically
// (decisions.md 2026-09-21). Never assumes a 1.0 diagonal — constant columns
// store null there.
function asFiniteNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function readCorrelationMatrix(
  analysisReport: Record<string, unknown> | null,
): CorrelationMatrixData | undefined {
  const cm = asRecord(analysisReport?.correlation_matrix);
  const matrix = asRecord(cm?.matrix);
  if (!matrix) return undefined;

  const columns = Object.keys(matrix).sort((a, b) => a.localeCompare(b));
  if (columns.length < 2) return undefined;

  const lookup = (a: string, b: string): number | null =>
    asFiniteNumber(asRecord(matrix[a])?.[b]) ??
    asFiniteNumber(asRecord(matrix[b])?.[a]);
  const values = columns.map((row) => columns.map((col) => lookup(row, col)));

  const strongPairs = new Set<string>();
  if (Array.isArray(cm?.strong_pairs)) {
    for (const p of cm.strong_pairs) {
      const r = asRecord(p);
      const col1 = typeof r?.col1 === "string" ? r.col1 : undefined;
      const col2 = typeof r?.col2 === "string" ? r.col2 : undefined;
      if (col1 && col2 && col1 !== col2) strongPairs.add(pairKey(col1, col2));
    }
  }

  return { columns, values, strongPairs };
}

function readOpenQuestions(v: unknown): OpenQuestion[] {
  if (!Array.isArray(v)) return [];
  return v.map((q) => {
    const r = asRecord(q) ?? {};
    return {
      question: asString(r.question),
      why_unanswerable: asString(r.why_unanswerable),
      what_data_would_answer: asString(r.what_data_would_answer),
    };
  });
}

// ---------------------------------------------------------------------------
// Executive layer — always expanded, most prominent.
// ---------------------------------------------------------------------------

const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const staggerItem = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" as const } },
};

export function InsightReportExecutive({
  executiveSummary,
}: {
  executiveSummary: Record<string, unknown> | null;
}) {
  const bullets = readBullets(executiveSummary);

  return (
    <section className="flex flex-col gap-5">
      <SectionHeader
        title="Executive Summary"
        description="For decision-makers — the findings that matter and what to do next."
      />
      {bullets.length === 0 ? (
        <EmptyNote>No executive summary was produced for this analysis.</EmptyNote>
      ) : (
        <motion.ol
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="flex flex-col gap-4"
        >
          {bullets.map((bullet, i) => (
            <motion.li
              key={i}
              variants={staggerItem}
              className="flex flex-col gap-3 rounded-md border border-border/60 bg-card/40 p-5"
            >
              {bullet.finding && (
                <p className="text-base font-medium leading-snug text-foreground">
                  {bullet.finding}
                </p>
              )}
              {bullet.context && (
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {bullet.context}
                </p>
              )}
              {bullet.recommended_action && (
                <div className="flex items-start gap-2 border-t border-border/60 pt-3">
                  <ArrowRight
                    className="mt-0.5 size-4 shrink-0 text-primary"
                    aria-hidden
                  />
                  <p className="text-sm font-medium leading-relaxed text-foreground">
                    {bullet.recommended_action}
                  </p>
                </div>
              )}
            </motion.li>
          ))}
        </motion.ol>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Analyst + Open Questions + Technical — collapsible accordion, all closed.
// Base UI drives the expand/collapse height animation natively; no Framer
// Motion wraps the panels (see decisions.md).
// ---------------------------------------------------------------------------

export function InsightReportDetail({
  insightReport,
  cleaningDecisions,
  chartPaths,
  analysisReport,
}: {
  insightReport: Record<string, unknown> | null;
  cleaningDecisions: CleaningDecision[] | null;
  chartPaths: string[] | null;
  analysisReport: Record<string, unknown> | null;
}) {
  const analyst = asRecord(insightReport?.analyst_layer) as AnalystLayer | undefined;
  const technical = asRecord(insightReport?.technical_layer) as
    | TechnicalLayer
    | undefined;
  const openQuestions = readOpenQuestions(insightReport?.open_questions);
  const userQuestionAddressed = asString(insightReport?.user_question_addressed);
  const decisions = cleaningDecisions ?? [];
  const availableCharts = chartPaths ?? [];
  const correlationMatrix = readCorrelationMatrix(analysisReport);

  return (
    <Accordion multiple className="flex flex-col">
      <AccordionItem value="analyst" className="border-t border-border/60">
        <AccordionTrigger>
          <TriggerLabel
            title="Analyst Report"
            description="For analysts — the full narrative, evidence, and confidence."
          />
        </AccordionTrigger>
        <AccordionContent>
          <AnalystPanel
            analyst={analyst}
            userQuestionAddressed={userQuestionAddressed}
            availableCharts={availableCharts}
            correlationMatrix={correlationMatrix}
          />
        </AccordionContent>
      </AccordionItem>

      <AccordionItem value="open-questions" className="border-t border-border/60">
        <AccordionTrigger>
          <TriggerLabel
            title="Open Questions"
            description="What this data cannot answer — and what would."
          />
        </AccordionTrigger>
        <AccordionContent>
          <OpenQuestionsPanel questions={openQuestions} />
        </AccordionContent>
      </AccordionItem>

      <AccordionItem
        value="technical"
        className="border-t border-b border-border/60"
      >
        <AccordionTrigger>
          <TriggerLabel
            title="Technical Detail"
            description="For data scientists — methodology, code, and limitations."
          />
        </AccordionTrigger>
        <AccordionContent>
          <TechnicalPanel technical={technical} decisions={decisions} />
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}

// --- Analyst panel ---------------------------------------------------------

function AnalystPanel({
  analyst,
  userQuestionAddressed,
  availableCharts,
  correlationMatrix,
}: {
  analyst: AnalystLayer | undefined;
  userQuestionAddressed: string | undefined;
  availableCharts: string[];
  correlationMatrix: CorrelationMatrixData | undefined;
}) {
  const narrative = asString(analyst?.narrative);
  const paragraphs = narrative ? narrative.split(/\n\n+/).filter(Boolean) : [];
  // Only reference charts that actually exist — an LLM-hallucinated filename
  // degrades to nothing rather than a dead anchor.
  const references = asStringArray(analyst?.chart_references).filter((f) =>
    availableCharts.includes(f),
  );

  // The existing PNG card's anchor — the caption links to it, it never
  // replaces the "Correlation heatmap" reference pill below.
  const heatmapFile = availableCharts.find(
    (f) => parseChartFilename(f).kind === "heatmap" && parseChartFilename(f).format === "png",
  );

  if (
    paragraphs.length === 0 &&
    references.length === 0 &&
    !userQuestionAddressed &&
    !correlationMatrix
  ) {
    return <EmptyNote>No analyst narrative was produced for this analysis.</EmptyNote>;
  }

  return (
    <div className="flex flex-col gap-4 pt-1">
      {userQuestionAddressed && (
        <Callout title="Your question, addressed">{userQuestionAddressed}</Callout>
      )}
      {paragraphs.map((p, i) => (
        <p key={i} className="text-sm leading-relaxed text-foreground/90">
          {p}
        </p>
      ))}
      {correlationMatrix && (
        <div className="pt-1">
          <CorrelationMatrix
            data={correlationMatrix}
            heatmapAnchorId={heatmapFile ? chartAnchorId(heatmapFile) : undefined}
          />
        </div>
      )}
      {references.length > 0 && (
        <div className="flex flex-col gap-2 pt-1">
          <p className="text-sm uppercase tracking-wider text-muted-foreground">
            Referenced charts
          </p>
          <div className="flex flex-wrap gap-2">
            {references.map((filename) => (
              <a
                key={filename}
                href={`#${chartAnchorId(filename)}`}
                className="inline-flex items-center rounded-full border border-border/60 bg-card/40 px-3 py-1 text-sm text-foreground/90 transition-colors hover:border-primary/50 hover:text-foreground max-sm:min-h-11"
              >
                {parseChartFilename(filename).label}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --- Open Questions panel --------------------------------------------------

function OpenQuestionsPanel({ questions }: { questions: OpenQuestion[] }) {
  if (questions.length === 0) {
    return (
      <EmptyNote>
        No open questions were recorded — see the Technical Detail for caveats.
      </EmptyNote>
    );
  }
  return (
    <ol className="flex flex-col gap-4 pt-1">
      {questions.map((q, i) => (
        <li
          key={i}
          className="flex flex-col gap-2 rounded-md border border-border/60 bg-card/40 p-4"
        >
          <div className="flex items-start gap-2">
            <HelpCircle
              className="mt-0.5 size-4 shrink-0 text-primary"
              aria-hidden
            />
            <p className="text-sm font-medium leading-snug text-foreground">
              {q.question ?? "Open question"}
            </p>
          </div>
          {q.why_unanswerable && (
            <p className="pl-6 text-sm leading-relaxed text-muted-foreground">
              {q.why_unanswerable}
            </p>
          )}
          {q.what_data_would_answer && (
            <p className="pl-6 text-sm leading-relaxed text-foreground/80">
              <span className="text-muted-foreground">What would resolve it: </span>
              {q.what_data_would_answer}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

// --- Technical panel -------------------------------------------------------

function TechnicalPanel({
  technical,
  decisions,
}: {
  technical: TechnicalLayer | undefined;
  decisions: CleaningDecision[];
}) {
  const statistical = asString(technical?.statistical_methodology);
  const codeBlocks = asStringArray(technical?.code_blocks);
  const limitations = asString(technical?.limitations);
  const sophistication = asString(technical?.sophistication_suggestions);
  const selfEval = asString(technical?.self_evaluation_notes);
  const leadOverride = asString(technical?.lead_override_note ?? undefined);

  const hasAnything =
    statistical ||
    codeBlocks.length > 0 ||
    limitations ||
    sophistication ||
    selfEval ||
    leadOverride ||
    decisions.length > 0;

  if (!hasAnything) {
    return <EmptyNote>No technical detail was produced for this analysis.</EmptyNote>;
  }

  return (
    <div className="flex flex-col gap-6 pt-1">
      {decisions.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-sm uppercase tracking-wider text-muted-foreground">
            Cleaning decisions
          </p>
          <ul className="flex flex-col gap-2">
            {decisions.map((d, i) => (
              <li
                key={i}
                className="flex flex-col gap-1 rounded-md border border-border/60 bg-card/40 p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  {d.column_name && (
                    <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-sm text-secondary-foreground">
                      {d.column_name}
                    </span>
                  )}
                  <span className="text-sm font-medium text-foreground">
                    {d.action}
                  </span>
                </div>
                {d.issue && (
                  <p className="text-sm text-muted-foreground">Issue: {d.issue}</p>
                )}
                {d.reason && (
                  <p className="text-sm leading-relaxed text-foreground/80">
                    {d.reason}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {statistical && (
        <div className="flex flex-col gap-2">
          <p className="text-sm uppercase tracking-wider text-muted-foreground">
            Statistical methodology
          </p>
          <p className="whitespace-pre-line text-sm leading-relaxed text-foreground/90">
            {statistical}
          </p>
        </div>
      )}

      {codeBlocks.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-sm uppercase tracking-wider text-muted-foreground">
            Code
          </p>
          <div className="flex flex-col gap-3">
            {codeBlocks.map((code, i) => (
              <CodeBlock key={i} code={code} language="python" />
            ))}
          </div>
        </div>
      )}

      {limitations && <Callout title="Limitations">{limitations}</Callout>}
      {sophistication && (
        <Callout title="Sophistication suggestions">{sophistication}</Callout>
      )}
      {selfEval && <Callout title="Self-evaluation notes">{selfEval}</Callout>}
      {leadOverride && <Callout title="Lead override">{leadOverride}</Callout>}
    </div>
  );
}

// --- shared bits -----------------------------------------------------------

function SectionHeader({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <h3
        className="text-2xl italic leading-tight"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {title}
      </h3>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function TriggerLabel({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <span className="flex flex-col gap-0.5 text-left">
      <span
        className="text-lg italic leading-tight"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {title}
      </span>
      <span className="text-sm text-muted-foreground">{description}</span>
    </span>
  );
}

function Callout({ title, children }: { title: string; children: string }) {
  return (
    <div className="rounded-md border border-l-2 border-border/60 border-l-primary/50 bg-card/40 px-4 py-3">
      <p className="mb-1 text-sm uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      <p className="whitespace-pre-line text-sm leading-relaxed text-foreground/90">
        {children}
      </p>
    </div>
  );
}

function EmptyNote({ children }: { children: string }) {
  return <p className="text-sm italic text-muted-foreground">{children}</p>;
}
