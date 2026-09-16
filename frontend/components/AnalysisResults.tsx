"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";

import { getAnalysis } from "@/lib/api";
import type { AnalysisResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  InsightReportExecutive,
  InsightReportDetail,
} from "@/components/InsightReport";
import { ChartGrid } from "@/components/ChartGrid";
import { QuestionInput } from "@/components/QuestionInput";

interface AnalysisResultsProps {
  analysisId: string;
  sessionId: string;
}

type ViewState = "loading" | "error" | "loaded";

export function AnalysisResults({
  analysisId,
  sessionId,
}: AnalysisResultsProps) {
  const router = useRouter();
  const [view, setView] = useState<ViewState>("loading");
  const [data, setData] = useState<AnalysisResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const result = await getAnalysis(analysisId, sessionId);
        if (cancelled) return;
        setData(result);
        setView("loaded");
      } catch {
        if (cancelled) return;
        setView("error");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [analysisId, sessionId]);

  if (view === "loading") {
    return <ResultsSkeleton />;
  }

  if (view === "error" || data === null) {
    return <ResultsError onTryAgain={() => router.push("/")} />;
  }

  return (
    <div className="flex flex-col gap-12">
      <AnalysisHeader
        filename={data.filename}
        rowCount={data.row_count}
        columnCount={data.column_count}
        dataQualityScore={data.data_quality_score}
      />

      <InsightReportExecutive executiveSummary={data.executive_summary} />

      <ChartGrid chartPaths={data.chart_paths} />

      <InsightReportDetail
        insightReport={data.insight_report}
        cleaningDecisions={data.cleaning_decisions}
        chartPaths={data.chart_paths}
      />

      <QuestionInput analysisId={analysisId} sessionId={sessionId} />
    </div>
  );
}

interface AnalysisHeaderProps {
  filename: string;
  rowCount: number | null;
  columnCount: number | null;
  dataQualityScore: number | null;
}

function AnalysisHeader({
  filename,
  rowCount,
  columnCount,
  dataQualityScore,
}: AnalysisHeaderProps) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="flex flex-col gap-5"
    >
      <div className="flex flex-col gap-1.5">
        <span className="font-mono text-xs tracking-wide text-muted-foreground">
          {filename}
        </span>
        <h2
          className="text-3xl italic leading-tight sm:text-4xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Analysis complete
        </h2>
      </div>
      <dl className="flex flex-wrap gap-x-10 gap-y-4">
        <Stat label="Rows" value={rowCount !== null ? rowCount.toLocaleString() : "—"} />
        <Stat label="Columns" value={columnCount !== null ? String(columnCount) : "—"} />
        <Stat
          label="Data quality"
          value={
            dataQualityScore !== null
              ? `${Math.round(dataQualityScore * 100)}%`
              : "—"
          }
        />
      </dl>
    </motion.header>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="font-mono text-2xl tabular-nums text-foreground">
        {value}
      </dd>
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div className="flex flex-col gap-12" aria-busy="true" aria-label="Loading results">
      <div className="flex flex-col gap-5">
        <div className="h-3 w-40 animate-pulse rounded bg-muted" />
        <div className="h-9 w-64 animate-pulse rounded bg-muted" />
        <div className="flex gap-10">
          <div className="h-12 w-20 animate-pulse rounded bg-muted" />
          <div className="h-12 w-20 animate-pulse rounded bg-muted" />
          <div className="h-12 w-24 animate-pulse rounded bg-muted" />
        </div>
      </div>
      <div className="flex flex-col gap-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-md border border-border/60 bg-card/40"
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[0, 1].map((i) => (
          <div
            key={i}
            className="h-56 animate-pulse rounded-md border border-border/60 bg-card/40"
          />
        ))}
      </div>
    </div>
  );
}

function ResultsError({ onTryAgain }: { onTryAgain: () => void }) {
  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex items-start gap-4 rounded-md border border-red-500/30 bg-red-500/10 px-5 py-5 text-red-200 md:px-6 md:py-6"
    >
      <AlertTriangle className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <h2
            className="text-xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Something went wrong on our end
          </h2>
          <p className="text-sm opacity-90">
            Your results could not be loaded. Please try again.
          </p>
        </div>
        <Button
          type="button"
          onClick={onTryAgain}
          aria-label="Try again from the upload page"
          className="max-sm:h-11 self-start"
        >
          Try Again
        </Button>
      </div>
    </motion.div>
  );
}
