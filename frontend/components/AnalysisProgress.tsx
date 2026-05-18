// TODO: full pause UI deferred to follow-up build. Will be paired with backend
//   pause_data persistence (pause_data jsonb column on analyses table).
//   Also deferred: no stale-state timeout in pause states — polling continues
//   indefinitely. No max-retry on persistent polling failures.
//   See assessment round 1 findings.

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, AlertTriangle, Check, Loader2 } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { getAnalysisStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AnalysisStatus } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;

const STAGE_ORDER = ["profiler", "cleaner", "analyzer", "explainer"] as const;
type Stage = (typeof STAGE_ORDER)[number];

const PAUSE_STATUSES: ReadonlyArray<AnalysisStatus> = [
  "domain_pause",
  "missing_value_pause",
  "outlier_pause",
];

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

const PAUSE_SUBTEXTS: Record<string, string> = {
  domain_pause: "Waiting on domain confirmation",
  missing_value_pause: "Waiting on missing-value decisions",
  outlier_pause: "Waiting on outlier review",
};

type StageState = "waiting" | "active-running" | "active-paused" | "complete";

interface AnalysisProgressProps {
  analysisId: string;
  sessionId: string;
}

function isPauseStatus(status: AnalysisStatus): boolean {
  return PAUSE_STATUSES.includes(status);
}

function getStageState(
  stage: Stage,
  status: AnalysisStatus,
  currentAgent: string | null,
): StageState {
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

export function AnalysisProgress({
  analysisId,
  sessionId,
}: AnalysisProgressProps) {
  const router = useRouter();

  const [status, setStatus] = useState<AnalysisStatus | null>(null);
  const [currentAgent, setCurrentAgent] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pollingError, setPollingError] = useState<boolean>(false);

  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchStatus(): Promise<AnalysisStatus | null> {
      try {
        const data = await getAnalysisStatus(analysisId, sessionId);
        if (cancelled) return null;
        setStatus(data.status);
        setCurrentAgent(data.current_agent);
        setProgressPct(data.progress_pct);
        setErrorMessage(data.error_message);
        setPollingError(false);
        return data.status;
      } catch {
        if (cancelled) return null;
        setPollingError(true);
        return null;
      }
    }

    async function init() {
      const initialStatus = await fetchStatus();
      if (cancelled) return;
      if (initialStatus === "complete" || initialStatus === "error") return;
      intervalRef.current = setInterval(async () => {
        const next = await fetchStatus();
        if (next === "complete" || next === "error") {
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
        }
      }, POLL_INTERVAL_MS);
    }

    void init();

    return () => {
      cancelled = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [analysisId, sessionId]);

  let view: "loading" | "pipeline" | "error-card" | "complete-card";
  if (status === "error") view = "error-card";
  else if (status === "complete") view = "complete-card";
  else if (status === null || currentAgent === null) view = "loading";
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

      {view === "pipeline" && status !== null && currentAgent !== null && (
        <motion.div
          key="pipeline"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="flex flex-col gap-8"
        >
          <PipelineView
            status={status}
            currentAgent={currentAgent}
            progressPct={progressPct}
            pollingError={pollingError}
          />

          <AnimatePresence initial={false}>
            {isPauseStatus(status) && (
              <motion.div
                key="pause-card"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
                className="flex items-start gap-3 rounded-md border border-border/60 bg-card/40 p-5 md:p-6"
              >
                <AlertCircle
                  className="size-5 mt-0.5 shrink-0 text-muted-foreground"
                  aria-hidden
                />
                <div className="flex flex-col gap-1.5">
                  <p className="text-sm font-medium">
                    Pipeline paused — pause handling coming in next build
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {PAUSE_SUBTEXTS[status]}
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {view === "error-card" && (
        <ErrorCard
          key="error-card"
          errorMessage={errorMessage}
          onTryAgain={() => router.push("/")}
        />
      )}

      {view === "complete-card" && <CompleteCard key="complete-card" />}
    </AnimatePresence>
  );
}

interface PipelineViewProps {
  status: AnalysisStatus;
  currentAgent: string;
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
              className="text-xs italic text-muted-foreground/70"
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
          <p className="text-xs text-muted-foreground">
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
  onTryAgain: () => void;
}

function ErrorCard({ errorMessage, onTryAgain }: ErrorCardProps) {
  const isUserError = errorMessage?.startsWith("USER_ERROR:") ?? false;

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

function CompleteCard() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex flex-col items-center justify-center gap-4 rounded-md border border-border/60 bg-card/40 px-6 py-12 text-center"
    >
      <Check
        className="size-10 text-green-500"
        strokeWidth={2.5}
        aria-hidden
      />
      <h2
        className="italic text-3xl leading-tight"
        style={{ fontFamily: "var(--font-display)" }}
      >
        Analysis complete
      </h2>
      <p className="text-sm text-muted-foreground">
        Results display coming in next build.
      </p>
    </motion.div>
  );
}
