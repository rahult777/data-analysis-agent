"use client";

// The active pause question, rendered inline in AnalysisProgress (no modal,
// no navigation). Select-then-confirm: the options are native radios in a
// fieldset, the chosen option's consequence is shown, and one button sends
// it. Every model-written string is rendered as plain text; the only markup
// derived from it is <code> for `backtick` spans. The model's reasoning sits
// behind a collapsed disclosure above the options, so the decision is never
// below a screenful of prose at 320px.

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronDown, HelpCircle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DOMAIN_CONFIDENCE_THRESHOLD,
  MAX_CORRECTED_DOMAIN_LENGTH,
  type AnswerableView,
  type DomainPauseView,
  type PauseOption,
  type PauseView,
} from "@/lib/pause";
import { cn } from "@/lib/utils";

interface PauseQuestionProps {
  view: PauseView;
  // False for visitors, and for an owner whose session the server rejected.
  canAnswer: boolean;
  // True after /resume rejected this browser's session (403).
  sessionRejected: boolean;
  submitting: boolean;
  submitError: string | null;
  onSubmit: (view: AnswerableView, optionId: string, correctedDomain?: string) => void;
}

export const VISITOR_PAUSE_NOTE =
  "Only the browser that started this analysis can answer. If that's you, open this link in that browser — the analysis is waiting for this answer.";
export const SESSION_REJECTED_NOTE =
  "This browser's saved session for this analysis was not accepted, so it can't answer here.";

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function formatNumber(value: number): string {
  return numberFormat.format(value);
}

// `code` spans become <code>; everything else stays a text node. An unpaired
// trailing backtick is kept as a literal character.
export function InlineText({ text }: { text: string }) {
  const parts = text.split("`");
  if (parts.length % 2 === 0) {
    const last = parts.pop() ?? "";
    parts[parts.length - 1] = `${parts[parts.length - 1]}\`${last}`;
  }
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <code key={index} className="rounded bg-muted px-1 py-0.5 font-mono [overflow-wrap:anywhere]">
            {part}
          </code>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

function domainOptions(view: DomainPauseView): PauseOption[] {
  const hypothesis = view.hypothesis.trim();
  return view.isUnknown
    ? [
        {
          id: "confirm",
          label: "Continue without a specific domain",
          details: ["The analysis will use general, conservative interpretations."],
        },
        {
          id: "correct",
          label: "Tell it the domain",
          details: ["The domain you describe becomes the one every later step uses."],
        },
      ]
    : [
        {
          id: "confirm",
          label: `Yes, it's ${hypothesis}`,
          details: [`The analysis continues treating this data as ${hypothesis}.`],
        },
        {
          id: "correct",
          label: "No, it's something else",
          details: ["The domain you describe becomes the one every later step uses."],
        },
      ];
}

export function PauseQuestion({ view, canAnswer, sessionRejected, submitting, submitError, onSubmit }: PauseQuestionProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  // This component is keyed by the pause, so mounting means a NEW question:
  // focus moves to it once, never on a poll.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  if (view.kind === "unrenderable") {
    return (
      <QuestionShell eyebrow="The pipeline is paused" icon={<AlertTriangle className="size-5" aria-hidden />}>
        <h2 ref={headingRef} tabIndex={-1} className="text-xl italic leading-tight focus:outline-none" style={{ fontFamily: "var(--font-display)" }}>
          This question can&apos;t be displayed
        </h2>
        <p className="text-sm text-muted-foreground">
          The pipeline is waiting for an answer, but the question it stored is incomplete, so it
          can&apos;t be answered here.{" "}
          <Link href="/" className={cn("text-foreground underline underline-offset-4 hover:text-primary", FOCUS_RING)}>
            Start a new analysis
          </Link>
          .
        </p>
      </QuestionShell>
    );
  }

  return (
    <AnswerableQuestion
      view={view}
      canAnswer={canAnswer}
      sessionRejected={sessionRejected}
      submitting={submitting}
      submitError={submitError}
      onSubmit={onSubmit}
      headingRef={headingRef}
    />
  );
}

interface AnswerableQuestionProps extends Omit<PauseQuestionProps, "view"> {
  view: AnswerableView;
  headingRef: RefObject<HTMLHeadingElement>;
}

function AnswerableQuestion({ view, canAnswer, sessionRejected, submitting, submitError, onSubmit, headingRef }: AnswerableQuestionProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [correction, setCorrection] = useState<string>("");
  const groupName = useId();
  const noteId = useId();
  const correctionId = useId();

  const options = view.kind === "domain" ? domainOptions(view) : view.options;
  const chosen = options.find((option) => option.id === selected) ?? null;
  const needsCorrection = view.kind === "domain" && selected === "correct";
  const ready = chosen !== null && (!needsCorrection || correction.trim() !== "");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canAnswer || submitting || !ready || chosen === null) return;
    onSubmit(view, chosen.id, needsCorrection ? correction.trim() : undefined);
  }

  const agentName = view.kind === "domain" ? "Profiler" : "Cleaner";

  return (
    <QuestionShell
      eyebrow={view.kind === "domain" ? `The ${agentName} needs your confirmation` : `The ${agentName} needs your decision`}
      icon={<HelpCircle className="size-5" aria-hidden />}
    >
      <QuestionBody view={view} headingRef={headingRef} />

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-describedby={canAnswer ? undefined : noteId}>
        <fieldset disabled={!canAnswer || submitting} className="flex min-w-0 flex-col gap-2">
          <legend className="mb-2 text-sm font-medium text-muted-foreground">
            {canAnswer ? "Choose one" : "Options"}
          </legend>
          {options.map((option) => (
            <label
              key={option.id}
              className={cn(
                "flex min-h-11 items-start gap-3 whitespace-normal rounded-md border p-3 text-left text-sm",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background",
                selected === option.id ? "border-primary bg-primary/10" : "border-border/60 bg-card/40",
                canAnswer && !submitting ? "cursor-pointer hover:border-border" : "cursor-default opacity-80",
              )}
            >
              <input
                type="radio"
                name={groupName}
                value={option.id}
                checked={selected === option.id}
                onChange={() => setSelected(option.id)}
                className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
              />
              <span className="min-w-0 [overflow-wrap:anywhere]">
                <InlineText text={option.label} />
              </span>
            </label>
          ))}
        </fieldset>

        {canAnswer ? (
          <>
            <AnimatePresence mode="wait" initial={false}>
              {chosen !== null && (
                <motion.div
                  key={chosen.id}
                  data-testid="choice-details"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.2, ease: "easeOut" }}
                  className="flex flex-col gap-2 rounded-md border border-border/60 bg-muted/30 p-3"
                >
                  <p className="text-sm font-medium">What happens if you choose this</p>
                  {chosen.details.length > 0 ? (
                    chosen.details.map((detail) => (
                      <p key={detail} className="text-sm text-muted-foreground [overflow-wrap:anywhere]">
                        <InlineText text={detail} />
                      </p>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">No further detail was given for this option.</p>
                  )}
                  {needsCorrection && (
                    <div className="flex flex-col gap-1.5 pt-1">
                      <label htmlFor={correctionId} className="text-sm font-medium">
                        What is this data?
                      </label>
                      <input
                        id={correctionId}
                        type="text"
                        value={correction}
                        maxLength={MAX_CORRECTED_DOMAIN_LENGTH}
                        onChange={(event) => setCorrection(event.target.value)}
                        disabled={submitting}
                        placeholder="e.g. school assessment records"
                        className={cn(
                          "min-h-11 w-full min-w-0 rounded-md border border-input bg-transparent px-3 text-base md:text-sm placeholder:text-muted-foreground",
                          FOCUS_RING,
                        )}
                      />
                      <p className="text-sm text-muted-foreground">Up to {MAX_CORRECTED_DOMAIN_LENGTH} characters.</p>
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            <div className="flex flex-col gap-2">
              <Button
                type="submit"
                disabled={!ready || submitting}
                className={cn("h-auto min-h-11 self-start whitespace-normal px-4 py-2 text-left", FOCUS_RING)}
              >
                {submitting ? (
                  <>
                    <motion.span
                      animate={{ rotate: 360 }}
                      transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                      className="inline-flex"
                    >
                      <Loader2 className="size-4" aria-hidden />
                    </motion.span>
                    Sending…
                  </>
                ) : (
                  "Continue with this choice"
                )}
              </Button>
              <AnimatePresence initial={false}>
                {submitError && (
                  <motion.p
                    key={submitError}
                    role="alert"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2, ease: "easeOut" }}
                    className="text-sm text-destructive"
                  >
                    {submitError}
                  </motion.p>
                )}
              </AnimatePresence>
            </div>
          </>
        ) : (
          <p id={noteId} className="text-sm text-muted-foreground">
            {sessionRejected ? `${SESSION_REJECTED_NOTE} ${VISITOR_PAUSE_NOTE}` : VISITOR_PAUSE_NOTE}
          </p>
        )}
      </form>
    </QuestionShell>
  );
}

function QuestionShell({ eyebrow, icon, children }: { eyebrow: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section
      aria-label="Pipeline question"
      className="flex min-w-0 flex-col gap-4 rounded-md border border-primary/40 bg-card/60 p-5 md:p-6"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-primary">
        {icon}
        {eyebrow}
      </p>
      {children}
    </section>
  );
}

function Heading({ headingRef, children }: { headingRef: RefObject<HTMLHeadingElement>; children: ReactNode }) {
  return (
    <h2
      ref={headingRef}
      tabIndex={-1}
      // A programmatic focus target (tabIndex -1), not a control: no ring.
      className="text-xl italic leading-tight [overflow-wrap:anywhere] focus:outline-none"
      style={{ fontFamily: "var(--font-display)" }}
    >
      {children}
    </h2>
  );
}

function Paragraph({ text, muted = true }: { text: string; muted?: boolean }) {
  return (
    <p className={cn("text-sm [overflow-wrap:anywhere]", muted && "text-muted-foreground")}>
      <InlineText text={text} />
    </p>
  );
}

interface ReasoningSection {
  label: string | null;
  text: string;
}

// A button with aria-expanded/aria-controls, not <details>: its content
// enters and leaves through Framer Motion (docs/ui-and-frontend.md, section
// reveals). It renders outside the options' fieldset, so it stays usable when
// the fieldset is disabled (visitors, while sending).
function Reasoning({ summary, sections, list = false }: { summary: string; sections: ReasoningSection[]; list?: boolean }) {
  const [open, setOpen] = useState<boolean>(false);
  const contentId = useId();
  if (sections.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "-mx-1 flex min-h-11 items-center gap-2 self-start rounded px-1 text-left text-sm font-medium hover:text-primary",
          FOCUS_RING,
        )}
      >
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2, ease: "easeOut" }} className="inline-flex">
          <ChevronDown className="size-4" aria-hidden />
        </motion.span>
        {summary}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={contentId}
            data-testid="reasoning"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="flex flex-col gap-3 border-l border-border/60 pl-3"
          >
            {list ? (
              <ul className="flex list-disc flex-col gap-1 pl-5">
                {sections.map((section, index) => (
                  <li key={index} className="text-sm text-muted-foreground [overflow-wrap:anywhere]">
                    <InlineText text={section.text} />
                  </li>
                ))}
              </ul>
            ) : (
              sections.map((section, index) => (
                <div key={index} className="flex flex-col gap-1">
                  {section.label && <p className="text-sm font-medium">{section.label}</p>}
                  <Paragraph text={section.text} />
                </div>
              ))
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function sectionsOf(entries: Array<[string | null, string | null]>): ReasoningSection[] {
  return entries.flatMap(([label, text]) => (text === null ? [] : [{ label, text }]));
}

function QuestionBody({ view, headingRef }: { view: AnswerableView; headingRef: RefObject<HTMLHeadingElement> }) {
  if (view.kind === "domain") {
    const hypothesis = view.hypothesis.trim();
    return (
      <div className="flex flex-col gap-3">
        <Heading headingRef={headingRef}>
          {view.isUnknown ? "The Profiler couldn't tell what kind of data this is." : "Confirm what this data is"}
        </Heading>
        {!view.isUnknown && <Paragraph text={`The Profiler's best guess is ${hypothesis}.`} muted={false} />}
        {view.score !== null && (
          <p className="text-sm text-muted-foreground">
            Confidence: {formatNumber(view.score)} / 100
            {view.score < DOMAIN_CONFIDENCE_THRESHOLD
              ? ` — below the ${DOMAIN_CONFIDENCE_THRESHOLD} needed to continue without asking.`
              : "."}
          </p>
        )}
        {/* Signals are shown as written: most begin with a column name (x1, ref). */}
        <Reasoning
          summary={`What it based this on (${view.signals.length})`}
          sections={view.signals.map((text) => ({ label: null, text }))}
          list
        />
      </div>
    );
  }

  if (view.kind === "missing_value") {
    const counts =
      view.missingCount !== null && view.totalRows !== null
        ? `${formatNumber(view.missingCount)} of ${formatNumber(view.totalRows)} values${
            view.missingPct !== null ? ` (${formatNumber(view.missingPct)}%)` : ""
          } are missing in the uploaded file.`
        : view.missingPct !== null
          ? `${formatNumber(view.missingPct)}% of its values are missing in the uploaded file.`
          : null;
    return (
      <div className="flex flex-col gap-3">
        <Heading headingRef={headingRef}>
          <InlineText text={`Missing values in \`${view.columnName}\``} />
        </Heading>
        {counts && <Paragraph text={counts} muted={false} />}
        <Reasoning
          summary="Why the Cleaner is asking"
          sections={sectionsOf([
            ["What this column is", view.represents],
            ["What the missingness likely means", view.provenance],
            ["What each choice costs here", view.domainContext],
          ])}
        />
      </div>
    );
  }

  const extreme =
    view.outlierValue !== null && view.sdDistance !== null && view.columnMean !== null
      ? `The most extreme, ${formatNumber(view.outlierValue)}, is ${formatNumber(view.sdDistance)} SD from the column mean of ${formatNumber(view.columnMean)}.`
      : null;
  return (
    <div className="flex flex-col gap-3">
      <Heading headingRef={headingRef}>
        <InlineText text={`Unusual values in \`${view.columnName}\``} />
      </Heading>
      {view.context && (
        <p className="self-start rounded-full border border-border/60 px-3 py-1 text-sm text-muted-foreground">
          {view.context === "medical" ? "Medical data" : "Financial data"}
        </p>
      )}
      {view.outlierCount !== null && (
        <Paragraph
          text={`${formatNumber(view.outlierCount)} value(s) lie outside the typical range in the uploaded file.${extreme ? ` ${extreme}` : ""}`}
          muted={false}
        />
      )}
      <Reasoning summary="Why the Cleaner is asking" sections={sectionsOf([[null, view.note]])} />
    </div>
  );
}
