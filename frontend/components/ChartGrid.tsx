"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Maximize2, Minimize2 } from "lucide-react";

import { API_URL } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Filename parsing — shared with InsightReport's chart-reference chips.
//
// viz_tools.py names charts `{analysis_id}_{type}_{...}.{ext}`. analysis_id is
// a uuid4 (hyphens only, no underscores), so the FIRST underscore separates
// the id from the chart-type keyword. Scatter's two column names are joined by
// underscores AND each truncated to 30 chars, so they are shown verbatim
// rather than split back into x / y.
// ---------------------------------------------------------------------------

export type ChartKind =
  | "histogram"
  | "boxplot"
  | "barchart"
  | "heatmap"
  | "linechart"
  | "scatter"
  | "unknown";

export interface ParsedChart {
  kind: ChartKind;
  label: string;
  format: "png" | "html";
}

function humanize(s: string): string {
  return s.replace(/_/g, " ").trim();
}

export function parseChartFilename(filename: string): ParsedChart {
  const format: "png" | "html" = /\.html$/i.test(filename) ? "html" : "png";
  const base = filename.replace(/\.(png|html)$/i, "");
  const firstUnderscore = base.indexOf("_");
  const rest = firstUnderscore === -1 ? base : base.slice(firstUnderscore + 1);

  if (rest.startsWith("histogram_")) {
    return {
      kind: "histogram",
      format,
      label: `Distribution — ${humanize(rest.slice("histogram_".length))}`,
    };
  }
  if (rest.startsWith("boxplot_")) {
    return {
      kind: "boxplot",
      format,
      label: `Box plot — ${humanize(rest.slice("boxplot_".length))}`,
    };
  }
  if (rest.startsWith("barchart_")) {
    return {
      kind: "barchart",
      format,
      label: `Top values — ${humanize(rest.slice("barchart_".length))}`,
    };
  }
  if (rest.startsWith("correlation")) {
    return { kind: "heatmap", format, label: "Correlation heatmap" };
  }
  if (rest.startsWith("linechart_")) {
    return {
      kind: "linechart",
      format,
      label: `${humanize(rest.slice("linechart_".length))} over time`,
    };
  }
  if (rest.startsWith("scatter_")) {
    return {
      kind: "scatter",
      format,
      label: `Scatter — ${humanize(rest.slice("scatter_".length))}`,
    };
  }
  return { kind: "unknown", format, label: humanize(rest) || filename };
}

export function chartAnchorId(filename: string): string {
  return `chart-${filename.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
};

const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: "easeOut" as const } },
};

export function ChartGrid({ chartPaths }: { chartPaths: string[] | null }) {
  const charts = chartPaths ?? [];
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (charts.length === 0) return null;

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h3
          className="text-2xl italic leading-tight"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Charts
        </h3>
        <p className="text-sm text-muted-foreground">
          Visualizations generated during the analysis. Select a chart to expand it.
        </p>
      </div>
      <motion.div
        variants={container}
        initial="hidden"
        animate="show"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        {charts.map((filename, i) => (
          <ChartCard
            key={filename}
            filename={filename}
            expanded={expandedIndex === i}
            onToggle={() =>
              setExpandedIndex((prev) => (prev === i ? null : i))
            }
          />
        ))}
      </motion.div>
    </section>
  );
}

interface ChartCardProps {
  filename: string;
  expanded: boolean;
  onToggle: () => void;
}

function ChartCard({ filename, expanded, onToggle }: ChartCardProps) {
  const [loaded, setLoaded] = useState<boolean>(false);
  const parsed = parseChartFilename(filename);
  const src = `${API_URL}/charts/${filename}`;
  const mediaHeight = expanded ? "h-[70vh]" : "h-56";

  return (
    <motion.div
      layout
      variants={item}
      id={chartAnchorId(filename)}
      className={cn(
        "flex scroll-mt-8 flex-col overflow-hidden rounded-md border border-border/60 bg-card/40",
        expanded && "sm:col-span-2",
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <span className="truncate text-sm text-foreground/90" title={parsed.label}>
          {parsed.label}
        </span>
        <button
          type="button"
          onClick={onToggle}
          aria-label={expanded ? "Collapse chart" : "Expand chart"}
          aria-expanded={expanded}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground max-sm:size-11"
        >
          {expanded ? (
            <Minimize2 className="size-4" aria-hidden />
          ) : (
            <Maximize2 className="size-4" aria-hidden />
          )}
        </button>
      </div>

      <div className={cn("relative bg-background/40", mediaHeight)}>
        {!loaded && (
          <div className="absolute inset-0 animate-pulse bg-muted" aria-hidden />
        )}
        {parsed.format === "png" ? (
          // Cross-origin static PNG served by FastAPI StaticFiles; next/image
          // would require remotePatterns config. no-img-element is warn-only.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt={parsed.label}
            onLoad={() => setLoaded(true)}
            onClick={onToggle}
            className="relative h-full w-full cursor-zoom-in object-contain"
          />
        ) : (
          <iframe
            src={src}
            title={parsed.label}
            onLoad={() => setLoaded(true)}
            className="relative h-full w-full"
          />
        )}
      </div>
    </motion.div>
  );
}
