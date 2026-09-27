// Live progress for one analysis: polls GET /status every 3 s, shows the
// four-stage pipeline, and — when the pipeline pauses — the question inline
// (PauseQuestion). Only the browser that uploaded the file (sessionId) can
// answer; everyone else sees the question read-only.
//
// Every status source — the first fetch, the interval, the resume response
// and each refetch after a failed answer — goes through applyStatus with a
// sequence number taken when the request is sent, so a slow earlier response
// can never overwrite a newer one or re-show a question already answered.
//
// The stall notice (10 minutes in the same non-pause status) is client-side
// only: the backend exposes no heartbeat, and a reload resets the timer.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Check, Loader2 } from "lucide-react";

import { PauseQuestion } from "@/components/PauseQuestion";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError, getAnalysisStatus, resumeAnalysis } from "@/lib/api";
import {
  buildResumeResponse,
  isPauseStatus,
  parsePause,
  pauseKey,
  type AnswerableView,
} from "@/lib/pause";
import { cn } from "@/lib/utils";
import type { AnalysisStatus, StatusResponse } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;
const STALL_MS = 10 * 60 * 1000;

const STAGE_ORDER = ["profiler", "cleaner", "analyzer", "explainer"] as const;
type Stage = (typeof STAGE_ORDER)[number];

const STAGE_LABELS: Record<Stage, string> = {
  profiler: "Profiler",
  cleaner: "Cleaner",
  analyzer: "Analyzer",
  explainer: "Explainer",
};

const STAGE_DESCRIPTIONS: Record<Stage, string> = {
  profiler:
    "Reading data provenance signals and forming domain hypothesis.",
  cleaner: "Cleaning with domain-aware methods.",
  analyzer: "Investigating top concerns and patterns.",
  explainer: "Translating findings into three layers.",
};

const MOVED_ON_TEXT = "This question was already answered or has changed.";
const REJECTED_TEXT =
  "Your answer couldn't be accepted. Check your choice and try again.";
const SERVER_TEXT =
  "Something went wrong on the server, so your answer wasn't recorded. Please try again.";
const NETWORK_TEXT =
  "Couldn't reach the server, so your answer may not have been sent. Please try again.";
const STALL_TEXT =
  "This step is taking longer than usual. If nothing changes, the server may have restarted and this analysis can't continue — you can start a new one.";

function recordedText(view: AnswerableView): string {
  return view.kind === "domain"
    ? "Answer recorded — the Profiler is re-running with your answer, and the Cleaner may ask about a column next (this can take a minute or two)."
    : "Answer recorded — the Cleaner is re-running and may ask about another column (this can take a minute or two).";
}

// A message in the status line that outlives the poll that caused it.
// "recorded" clears once a pause appears or another agent takes over;
// "moved-on" clears once the status or the question changes again.
type Notice =
  | { kind: "recorded"; text: string; anchorAgent: string | null }
  | { kind: "moved-on"; text: string; anchorStatus: AnalysisStatus; anchorKey: string | null };

type FetchOutcome =
  | { outcome: "applied"; data: StatusResponse }
  | { outcome: "dropped" }
  | { outcome: "failed" }
  | { outcome: "not-found" }
  | { outcome: "inactive" };

type StageState = "waiting" | "active-running" | "active-paused" | "complete";

interface AnalysisProgressProps {
  analysisId: string;
  // The uploader's session_id from this browser's localStorage, or null for
  // a read-only visitor (including the real owner on another device).
  sessionId: string | null;
  onComplete?: () => void;
}

function getStageState(
  stage: Stage,
  status: AnalysisStatus,
  currentAgent: string | null,
): StageState {
  if (status === "complete") return "complete";
  if (currentAgent === stage) {
    return isPauseStatus(status) ? "active-paused" : "active-running";
  }
  const stageIdx = STAGE_ORDER.indexOf(stage);
  const activeIdx = currentAgent
    ? STAGE_ORDER.indexOf(currentAgent as Stage)
    : -1;
  if (activeIdx === -1) return "waiting";
  return stageIdx < activeIdx ? "complete" : "waiting";
}

function keyOf(data: StatusResponse): string | null {
  return isPauseStatus(data.status) ? pauseKey(data.status, data.pause_data) : null;
}

function isTerminal(status: AnalysisStatus | null): boolean {
  return status === "complete" || status === "error";
}

function statusSentence(
  status: AnalysisStatus,
  currentAgent: string | null,
  canAnswer: boolean,
  questionRenderable: boolean,
): string {
  if (status === "complete") return "The analysis is complete.";
  const agent = currentAgent && currentAgent in STAGE_LABELS ? STAGE_LABELS[currentAgent as Stage] : "pipeline";
  if (isPauseStatus(status)) {
    if (!questionRenderable) return `Paused: the ${agent} is waiting, but its question could not be loaded.`;
    return canAnswer
      ? `Paused: the ${agent} needs your answer below.`
      : `Paused: the ${agent} is waiting for an answer from the browser that started this analysis.`;
  }
  return `The ${agent} is working.`;
}

export function AnalysisProgress({
  analysisId,
  sessionId,
  onComplete,
}: AnalysisProgressProps) {
  const router = useRouter();
  const isOwner = sessionId !== null;

  // Hold the latest onComplete in a ref so the polling effect never
  // re-subscribes when the parent passes a new callback identity.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [currentAgent, setCurrentAgent] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pauseData, setPauseData] = useState<Record<string, unknown> | null>(null);
  const [pollingError, setPollingError] = useState<boolean>(false);
  const [notFound, setNotFound] = useState<boolean>(false);
  const [stalled, setStalled] = useState<boolean>(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  // The key of the question whose answer is being sent (one question's state,
  // not whichever question happens to be shown).
  const [submittingKey, setSubmittingKey] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Set when /resume rejects this browser's session (403): the question
  // stays visible, read-only.
  const [sessionRejected, setSessionRejected] = useState<boolean>(false);

  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const activeRef = useRef<boolean>(true);
  const issuedSeqRef = useRef<number>(0);
  const appliedSeqRef = useRef<number>(0);
  const answeredKeysRef = useRef<Set<string>>(new Set());
  const statusRef = useRef<AnalysisStatus | null>(null);
  const statusSinceRef = useRef<number>(Date.now());
  const shownKeyRef = useRef<string | null>(null);
  const completedRef = useRef<boolean>(false);
  const submittingKeyRef = useRef<string | null>(null);
  const statusLineRef = useRef<HTMLParagraphElement>(null);

  const canAnswer = isOwner && !sessionRejected;

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  // The only place status state is set. Drops a response older than the
  // last one applied, and any response showing a question already answered.
  const applyStatus = useCallback(
    (data: StatusResponse, seq: number): StatusResponse | null => {
      if (seq < appliedSeqRef.current) return null;
      const key = keyOf(data);
      if (key !== null && answeredKeysRef.current.has(key)) {
        // A lagging read of an answered question: the server did answer.
        setPollingError(false);
        return null;
      }
      appliedSeqRef.current = seq;

      if (data.status !== statusRef.current) {
        statusRef.current = data.status;
        statusSinceRef.current = Date.now();
        setStalled(false);
      }
      if (key !== shownKeyRef.current) {
        shownKeyRef.current = key;
        setSubmitError(null);
      }
      setNotice((previous) => {
        if (previous === null) return null;
        if (previous.kind === "recorded") {
          return key !== null || isTerminal(data.status) || data.current_agent !== previous.anchorAgent
            ? null
            : previous;
        }
        return data.status !== previous.anchorStatus || key !== previous.anchorKey ? null : previous;
      });
      setStatus(data.status);
      setCurrentAgent(data.current_agent);
      setProgressPct(data.progress_pct);
      setErrorMessage(data.error_message);
      setPauseData(key !== null ? data.pause_data : null);
      setPollingError(false);

      if (isTerminal(data.status)) stopPolling();
      if (data.status === "complete" && !completedRef.current) {
        completedRef.current = true;
        onCompleteRef.current?.();
      }
      return data;
    },
    [stopPolling],
  );

  // One status fetch, numbered when it is sent. "dropped" means the server
  // answered but a newer response had already been applied.
  const fetchStatus = useCallback(async (): Promise<FetchOutcome> => {
    const seq = ++issuedSeqRef.current;
    try {
      const data = await getAnalysisStatus(analysisId);
      if (!activeRef.current) return { outcome: "inactive" };
      return applyStatus(data, seq) !== null ? { outcome: "applied", data } : { outcome: "dropped" };
    } catch (err) {
      if (!activeRef.current) return { outcome: "inactive" };
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        stopPolling();
        return { outcome: "not-found" };
      }
      if (seq >= appliedSeqRef.current) setPollingError(true);
      return { outcome: "failed" };
    }
  }, [analysisId, applyStatus, stopPolling]);

  const checkStall = useCallback(() => {
    const current = statusRef.current;
    if (
      current !== null &&
      !isPauseStatus(current) &&
      !isTerminal(current) &&
      Date.now() - statusSinceRef.current >= STALL_MS
    ) {
      setStalled(true);
    }
  }, []);

  useEffect(() => {
    activeRef.current = true;

    async function init(): Promise<void> {
      const first = await fetchStatus();
      if (!activeRef.current) return;
      if (first.outcome === "not-found" || (first.outcome === "applied" && isTerminal(first.data.status))) return;
      stopPolling();
      intervalRef.current = setInterval(async () => {
        await fetchStatus();
        if (activeRef.current) checkStall();
      }, POLL_INTERVAL_MS);
    }

    void init();

    return () => {
      activeRef.current = false;
      stopPolling();
    };
  }, [fetchStatus, checkStall, stopPolling]);

  const focusStatusLine = useCallback((): void => {
    // After the question card has gone, focus would otherwise fall to <body>.
    requestAnimationFrame(() => statusLineRef.current?.focus());
  }, []);

  const handleSubmit = useCallback(
    async (view: AnswerableView, optionId: string, correctedDomain?: string): Promise<void> => {
      if (sessionId === null || submittingKeyRef.current === view.key) return;
      submittingKeyRef.current = view.key;
      setSubmittingKey(view.key);
      setSubmitError(null);
      // Numbered when sent: a response applied with a higher number was read
      // after this answer left the browser.
      const sentSeq = ++issuedSeqRef.current;
      try {
        const data = await resumeAnalysis(
          analysisId,
          sessionId,
          buildResumeResponse(view, optionId, correctedDomain),
        );
        if (!activeRef.current) return;
        answeredKeysRef.current.add(view.key);
        // A read sent after the answer that already shows something past this
        // question (the next question, or a later stage) is newer than the
        // write's own result: keep it.
        const newerReadShown =
          appliedSeqRef.current > sentSeq && shownKeyRef.current !== view.key;
        if (!newerReadShown) {
          // At its send number, so polls sent after the answer still win; only
          // when a pre-write read of this same question was applied since does
          // it need a fresh number to replace it.
          applyStatus(data, appliedSeqRef.current > sentSeq ? ++issuedSeqRef.current : sentSeq);
          setNotice({ kind: "recorded", text: recordedText(view), anchorAgent: data.current_agent });
        }
        // A new question takes focus itself (PauseQuestion); otherwise the status line does.
        if (shownKeyRef.current === null) focusStatusLine();
      } catch (err) {
        if (!activeRef.current) return;
        const status = err instanceof ApiError ? err.status : null;
        if (status === 403) setSessionRejected(true);
        // Whatever failed, the server's state decides what to show next.
        const refetch = await fetchStatus();
        if (!activeRef.current) return;
        // The latest applied state is the newest known, whether the refetch
        // was applied, dropped for a newer poll, or failed: if it no longer
        // shows this question, the answer's pause has moved on.
        const movedOn = shownKeyRef.current !== view.key;
        if (status === 403) {
          // Marks nothing as answered: the question is still open for its owner.
        } else if (movedOn) {
          answeredKeysRef.current.add(view.key);
          setNotice({
            kind: "moved-on",
            text: MOVED_ON_TEXT,
            anchorStatus: statusRef.current ?? "cleaning",
            anchorKey: shownKeyRef.current,
          });
          if (shownKeyRef.current === null) focusStatusLine();
        } else if (status === null || refetch.outcome === "failed") {
          setSubmitError(NETWORK_TEXT);
        } else {
          setSubmitError(status === 400 || status === 409 ? REJECTED_TEXT : SERVER_TEXT);
        }
      } finally {
        if (submittingKeyRef.current === view.key) {
          submittingKeyRef.current = null;
          if (activeRef.current) setSubmittingKey(null);
        }
      }
    },
    [analysisId, sessionId, applyStatus, fetchStatus, focusStatusLine],
  );

  const pauseView = useMemo(
    () => (isPauseStatus(status) ? parsePause(status, pauseData) : null),
    [status, pauseData],
  );

  // At "complete" the pipeline is shown fully finished (all stages green)
  // during the brief exit transition while the parent swaps in the results
  // view — the parent is notified via onComplete the moment status hits it.
  let view: "loading" | "pipeline" | "error-card" | "not-found";
  if (notFound) view = "not-found";
  else if (status === "error") view = "error-card";
  else if (status === null) view = "loading";
  else if (status === "complete") view = "pipeline";
  else if (currentAgent === null) view = "loading";
  else view = "pipeline";

  return (
    <AnimatePresence mode="wait" initial={false}>
      {view === "loading" && (
        <motion.div
          key="loading"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="flex flex-col items-center justify-center gap-4 py-16"
        >
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            className="inline-flex"
          >
            <Loader2
              className="size-6 text-muted-foreground"
              aria-label="Loading"
            />
          </motion.span>
          <p className="text-sm text-muted-foreground">Loading analysis…</p>
        </motion.div>
      )}

      {view === "pipeline" && status !== null && (
        <motion.div
          key="pipeline"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="flex flex-col gap-8"
        >
          <div className="flex flex-col gap-3">
            <PipelineView
              status={status}
              currentAgent={currentAgent}
              progressPct={progressPct}
              pollingError={pollingError}
            />
            <p
              ref={statusLineRef}
              role="status"
              aria-live="polite"
              tabIndex={-1}
              data-testid="status-line"
              className="text-sm text-muted-foreground focus:outline-none"
            >
              {notice?.text ??
                statusSentence(status, currentAgent, canAnswer, pauseView?.kind !== "unrenderable")}
            </p>
            <AnimatePresence initial={false}>
              {stalled && (
                <motion.div
                  key="stall"
                  data-testid="stall-notice"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25, ease: "easeOut" }}
                  className="flex items-start gap-3 rounded-md border border-border/60 bg-card/40 p-4"
                >
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <p className="text-sm text-muted-foreground">
                    {STALL_TEXT}{" "}
                    <Link
                      href="/"
                      className="text-foreground underline underline-offset-4 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Start a new analysis
                    </Link>
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <AnimatePresence mode="wait" initial={false}>
            {pauseView !== null && (
              <motion.div
                key={pauseView.key}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
              >
                <PauseQuestion
                  view={pauseView}
                  canAnswer={canAnswer}
                  sessionRejected={sessionRejected}
                  submitting={submittingKey === pauseView.key}
                  submitError={submitError}
                  onSubmit={handleSubmit}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {view === "error-card" && (
        <ErrorCard
          key="error-card"
          errorMessage={errorMessage}
          isOwner={isOwner}
          onTryAgain={() => router.push("/")}
        />
      )}

      {view === "not-found" && (
        <NotFoundCard key="not-found" onUpload={() => router.push("/")} />
      )}
    </AnimatePresence>
  );
}

interface PipelineViewProps {
  status: AnalysisStatus;
  currentAgent: string | null;
  progressPct: number | null;
  pollingError: boolean;
}

function PipelineView({
  status,
  currentAgent,
  progressPct,
  pollingError,
}: PipelineViewProps) {
  return (
    <div className="flex flex-col gap-6">
      <ol role="list" className="flex flex-col">
        {STAGE_ORDER.map((stage, idx) => {
          const state = getStageState(stage, status, currentAgent);
          const isLast = idx === STAGE_ORDER.length - 1;
          return (
            <StageRow
              key={stage}
              stage={stage}
              state={state}
              isLast={isLast}
            />
          );
        })}
      </ol>

      <div className="flex flex-col gap-2">
        <div className="h-1.5 overflow-hidden rounded-full border border-border/60 bg-card/40">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${progressPct ?? 0}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="h-full rounded-full"
            style={{ backgroundColor: "var(--primary)" }}
          />
        </div>
        <AnimatePresence initial={false}>
          {pollingError && (
            <motion.p
              key="reconnecting"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="text-sm italic text-muted-foreground/70"
            >
              Reconnecting…
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

interface StageRowProps {
  stage: Stage;
  state: StageState;
  isLast: boolean;
}

function StageRow({ stage, state, isLast }: StageRowProps) {
  const isActive = state === "active-running" || state === "active-paused";
  const isComplete = state === "complete";

  return (
    <li
      role="listitem"
      aria-current={isActive ? "step" : undefined}
      className="flex items-start gap-4"
    >
      <div className="flex flex-col items-center self-stretch shrink-0 pt-1.5">
        <StageIndicator state={state} />
        {!isLast && (
          <div
            className={cn(
              "mt-2 w-px flex-1",
              isComplete ? "bg-primary/40" : "bg-border/60",
            )}
            style={{ minHeight: 28 }}
          />
        )}
      </div>
      <div className="flex flex-col gap-1 pb-5 flex-1 min-w-0">
        {isActive ? (
          <p
            className="italic text-lg leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {STAGE_LABELS[stage]}
          </p>
        ) : (
          <p
            className={cn(
              "text-sm font-medium",
              isComplete ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {STAGE_LABELS[stage]}
          </p>
        )}
        {isActive && (
          <p className="text-sm text-muted-foreground">
            {STAGE_DESCRIPTIONS[stage]}
          </p>
        )}
      </div>
    </li>
  );
}

interface StageIndicatorProps {
  state: StageState;
}

function StageIndicator({ state }: StageIndicatorProps) {
  if (state === "waiting") {
    return (
      <div
        className="size-3.5 rounded-full border-2 border-border/60"
        aria-hidden
      />
    );
  }

  if (state === "active-running") {
    return (
      <motion.div
        animate={{ scale: [1, 1.1, 1] }}
        transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
        className="size-3.5 rounded-full"
        style={{ backgroundColor: "var(--primary)" }}
        aria-hidden
      />
    );
  }

  if (state === "active-paused") {
    return (
      <div
        className="size-3.5 rounded-full"
        style={{ backgroundColor: "var(--primary)" }}
        aria-hidden
      />
    );
  }

  return (
    <div
      className="flex size-3.5 items-center justify-center rounded-full"
      style={{ backgroundColor: "var(--primary)" }}
      aria-hidden
    >
      <Check
        className="size-2.5 text-primary-foreground"
        strokeWidth={3}
      />
    </div>
  );
}

interface ErrorCardProps {
  errorMessage: string | null;
  isOwner: boolean;
  onTryAgain: () => void;
}

function ErrorCard({ errorMessage, isOwner, onTryAgain }: ErrorCardProps) {
  if (!isOwner) return <VisitorErrorCard onUpload={onTryAgain} />;

  // /status returns only the category ("USER_ERROR" | "SYSTEM_ERROR"), never detail.
  const isUserError = errorMessage === "USER_ERROR";

  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={cn(
        "flex items-start gap-4 rounded-md border px-5 py-5 md:px-6 md:py-6",
        isUserError
          ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
          : "border-red-500/30 bg-red-500/10 text-red-200",
      )}
    >
      <AlertTriangle className="size-5 mt-0.5 shrink-0" aria-hidden />
      <div className="flex flex-col gap-4 flex-1 min-w-0">
        <div className="flex flex-col gap-1.5">
          <h2
            className="italic text-xl leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {isUserError
              ? "Something went wrong"
              : "Something went wrong on our end"}
          </h2>
          <p className="text-sm opacity-90">
            {isUserError
              ? "There was an issue with your file. Please try uploading again."
              : "We hit an unexpected issue. Please try again or contact support."}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button
            type="button"
            onClick={onTryAgain}
            aria-label="Try again from the upload page"
          >
            Try Again
          </Button>
          {!isUserError && (
            <a
              href="#"
              aria-label="Contact support (placeholder)"
              className={buttonVariants({ variant: "ghost" })}
            >
              Contact Support
            </a>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// Read-only visitors did not upload this file, so the owner's "your file" /
// "try again" copy would be wrong; they get a neutral explanation and a way
// to start their own analysis. No Contact Support placeholder.
function VisitorErrorCard({ onUpload }: { onUpload: () => void }) {
  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex items-start gap-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-5 py-5 text-amber-200 md:px-6 md:py-6"
    >
      <AlertTriangle className="size-5 mt-0.5 shrink-0" aria-hidden />
      <div className="flex flex-col gap-4 flex-1 min-w-0">
        <div className="flex flex-col gap-1.5">
          <h2
            className="italic text-xl leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            This analysis didn&apos;t finish
          </h2>
          <p className="text-sm opacity-90">
            The analysis at this link stopped with an error, so there are no
            results to show.
          </p>
        </div>
        <Button
          type="button"
          onClick={onUpload}
          aria-label="Analyze your own file on the upload page"
          className="self-start"
        >
          Analyze your own file
        </Button>
      </div>
    </motion.div>
  );
}

function NotFoundCard({ onUpload }: { onUpload: () => void }) {
  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex items-start gap-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-5 py-5 text-amber-200 md:px-6 md:py-6"
    >
      <AlertTriangle className="size-5 mt-0.5 shrink-0" aria-hidden />
      <div className="flex flex-col gap-4 flex-1 min-w-0">
        <div className="flex flex-col gap-1.5">
          <h2
            className="italic text-xl leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Analysis not found
          </h2>
          <p className="text-sm opacity-90">
            This link doesn&apos;t match any analysis. It may be mistyped or
            incomplete.
          </p>
        </div>
        <Button
          type="button"
          onClick={onUpload}
          aria-label="Go to the upload page"
          className="self-start"
        >
          Upload a file
        </Button>
      </div>
    </motion.div>
  );
}
