"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Clock, Loader2, Send } from "lucide-react";

import { getQuestion, postQuestion } from "@/lib/api";
import type { QuestionStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CodeBlock } from "@/components/CodeBlock";

const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 40; // ~2 minutes at 3s cadence

interface SubmittedQuestion {
  questionId: string;
  question: string;
}

export function QuestionInput({
  analysisId,
  sessionId,
}: {
  analysisId: string;
  sessionId: string;
}) {
  const [value, setValue] = useState<string>("");
  const [items, setItems] = useState<SubmittedQuestion[]>([]);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const historyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Keep the newest question/answer in view as history grows.
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length]);

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    const question = value.trim();
    if (!question || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await postQuestion(analysisId, sessionId, question);
      setItems((prev) => [
        ...prev,
        { questionId: res.question_id, question },
      ]);
      setValue("");
    } catch {
      setSubmitError("Could not submit your question. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h3
          className="text-2xl italic leading-tight"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Ask a question
        </h3>
        <p className="text-sm text-muted-foreground">
          Query the cleaned dataset directly — every answer is computed with
          pandas and shows its code.
        </p>
      </div>

      {items.length > 0 && (
        <div
          ref={historyRef}
          className="flex max-h-[32rem] flex-col gap-4 overflow-y-auto pr-1"
        >
          {items.map((item) => (
            <QuestionItem
              key={item.questionId}
              analysisId={analysisId}
              sessionId={sessionId}
              questionId={item.questionId}
              question={item.question}
            />
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <div className="flex items-stretch gap-2">
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="e.g. Which category has the highest average value?"
            aria-label="Ask a question about this dataset"
            disabled={submitting}
            className="h-11 flex-1"
          />
          <Button
            type="submit"
            disabled={submitting || value.trim().length === 0}
            aria-label="Submit question"
            className="h-11 px-4"
          >
            {submitting ? (
              <motion.span
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                className="inline-flex"
              >
                <Loader2 className="size-4" aria-hidden />
              </motion.span>
            ) : (
              <Send className="size-4" aria-hidden />
            )}
            <span>Ask</span>
          </Button>
        </div>
        {submitError && (
          <p className="text-xs text-red-300" role="alert">
            {submitError}
          </p>
        )}
      </form>
    </section>
  );
}

interface QuestionItemProps {
  analysisId: string;
  sessionId: string;
  questionId: string;
  question: string;
}

/**
 * Owns the polling lifecycle for a single question. Rendering one child per
 * submitted question gives each an independent poll loop and — because items
 * are never removed — automatic interval cleanup when the whole surface
 * unmounts.
 */
function QuestionItem({
  analysisId,
  sessionId,
  questionId,
  question,
}: QuestionItemProps) {
  const [status, setStatus] = useState<QuestionStatus>("pending");
  const [answer, setAnswer] = useState<string | null>(null);
  const [pandasCode, setPandasCode] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    let polls = 0;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    async function poll(): Promise<void> {
      polls += 1;
      try {
        const res = await getQuestion(analysisId, sessionId, questionId);
        if (cancelled) return;
        setStatus(res.status);
        if (res.status === "complete" || res.status === "error") {
          setAnswer(res.answer);
          setPandasCode(res.pandas_code);
          if (intervalId) clearInterval(intervalId);
          return;
        }
      } catch {
        // Transient error (network / not-yet-visible row) — keep polling
        // until the ceiling rather than failing the whole question.
      }
      if (polls >= MAX_POLLS && !cancelled) {
        if (intervalId) clearInterval(intervalId);
        setTimedOut(true);
      }
    }

    void poll(); // immediate first check
    intervalId = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
  }, [analysisId, sessionId, questionId]);

  const pending = status === "pending" || status === "answering";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex flex-col gap-3 rounded-md border border-border/60 bg-card/40 p-4"
    >
      <div className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">
          You asked
        </span>
        <p className="text-sm font-medium text-foreground">{question}</p>
      </div>

      <div className="border-t border-border/60 pt-3">
        {pending && !timedOut && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <motion.span
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              className="inline-flex"
            >
              <Loader2 className="size-4" aria-hidden />
            </motion.span>
            <span>Analyzing…</span>
          </div>
        )}

        {timedOut && pending && (
          <div className="flex items-start gap-2 text-sm text-muted-foreground">
            <Clock className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              This is taking longer than expected. The answer may still arrive —
              you can ask another question in the meantime.
            </span>
          </div>
        )}

        {status === "error" && (
          <div className="flex items-start gap-2 text-sm text-red-300">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              {answer ?? "This question could not be answered. Please try rephrasing it."}
            </span>
          </div>
        )}

        {status === "complete" && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="flex flex-col gap-3"
          >
            <p className="whitespace-pre-line text-sm leading-relaxed text-foreground/90">
              {answer ?? "No answer was returned."}
            </p>
            {pandasCode && <CodeBlock code={pandasCode} language="python" />}
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
