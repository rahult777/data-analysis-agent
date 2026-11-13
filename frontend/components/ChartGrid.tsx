"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Maximize2, Minimize2 } from "lucide-react";

import { chartUrl } from "@/lib/api";
import { isSnapshot } from "@/lib/mode";
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
      {/* No entry animation in the public build (the cards inherit it): the
          prerendered grid would stay transparent until JavaScript runs. */}
      <motion.div
        variants={container}
        initial={isSnapshot ? false : "hidden"}
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
  // An interactive chart's frame renders only once the card has mounted: in
  // the prerendered public build it could finish loading before React
  // hydrates and listens for its load event, and a sandboxed frame's load
  // state cannot be read afterwards, so its placeholder would stay up (M2b.1
  // Code Review #7). An image renders at once, so it shows without
  // JavaScript; an image that loaded before hydration is caught by checking
  // it after mounting (M2b.4c).
  const [mounted, setMounted] = useState<boolean>(false);
  const imageRef = useRef<HTMLImageElement | null>(null);
  useEffect(() => {
    setMounted(true);
    const image = imageRef.current;
    if (image !== null && image.complete && image.naturalWidth > 0) setLoaded(true);
  }, []);
  const parsed = parseChartFilename(filename);
  const src = chartUrl(filename);
  const mediaHeight = expanded ? "h-[70vh]" : "h-56";

  return (
    // A focus target (tabIndex -1): a link to the card moves the keyboard
    // focus here, and a ring shows it (M2b.4c).
    <motion.div
      layout
      variants={item}
      id={chartAnchorId(filename)}
      tabIndex={-1}
      className={cn(
        "flex scroll-mt-8 flex-col overflow-hidden rounded-md border border-border/60 bg-card/40 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        expanded && "sm:col-span-2",
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        {/* The whole label, wrapping on a narrow card (M2b.4c). */}
        <span className="min-w-0 text-sm text-foreground/90 [overflow-wrap:anywhere]">
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
        {/* The analysis page's <noscript> rule hides the placeholder without
            JavaScript, where it would pulse forever. */}
        {!loaded && (
          <div data-chart-placeholder="" className="absolute inset-0 animate-pulse bg-muted" aria-hidden />
        )}
        {parsed.format === "png" ? (
          // A static PNG: cross-origin from FastAPI StaticFiles locally,
          // /demo/charts/ in the snapshot build; next/image would require
          // remotePatterns config. no-img-element is warn-only.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            ref={imageRef}
            src={src}
            alt={parsed.label}
            loading="lazy"
            decoding="async"
            onLoad={() => setLoaded(true)}
            onClick={onToggle}
            className="relative h-full w-full cursor-zoom-in object-contain"
          />
        ) : (
          <>
            {/* Shown only without JavaScript, by the public analysis page's
                <noscript> rule, which also makes it a flex box: a display
                class here would override the hidden attribute. */}
            <p
              data-chart-nojs=""
              hidden
              className="absolute inset-0 items-center justify-center px-4 text-center text-sm text-muted-foreground"
            >
              This interactive chart needs JavaScript.
            </p>
            {mounted && (
              // Scripts only: never allow-same-origin, so the chart runs in
              // an opaque origin. No allow-downloads either, so plotly's
              // "Download plot as a png" button and its logo link do nothing
              // (owner ruling D1; M2b.2 removes both from regenerated charts).
              <iframe
                src={src}
                title={parsed.label}
                sandbox="allow-scripts"
                loading="lazy"
                referrerPolicy="no-referrer"
                onLoad={() => setLoaded(true)}
                className="relative h-full w-full"
              />
            )}
          </>
        )}
      </div>
      {parsed.format === "png" && (
        // The image at its own address, where the browser's image view can
        // zoom it, as a phone needs (owner ruling Q7). A plain link: it works
        // without JavaScript, and its name says which chart it opens.
        <div className="border-t border-border/60 px-3">
          <a
            href={src}
            className="inline-flex min-h-11 items-center text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            Open full size<span className="sr-only"> ({parsed.label})</span>
          </a>
        </div>
      )}
    </motion.div>
  );
}
