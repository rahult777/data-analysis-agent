"use client";

import { useCallback, useRef, useState } from "react";
import type { FocusEvent, KeyboardEvent, PointerEvent } from "react";

// ---------------------------------------------------------------------------
// Interactive correlation matrix (Analyst layer). Deliberately a native
// <table> of fixed-size button cells rather than a chart library — see
// decisions.md 2026-09-21 (Recharts-to-CSS-grid redirect). Parsing of the raw
// analysis_report JSONB lives in InsightReport.tsx; this component only ever
// sees the already-validated shape below.
// ---------------------------------------------------------------------------

export interface CorrelationMatrixData {
  /** Column names, already in display order (alphabetical — see decisions.md). */
  columns: string[];
  /** values[row][col]; null when r could not be computed. */
  values: (number | null)[][];
  /** Order-insensitive keys of backend-flagged strong pairs (pairKey). */
  strongPairs: Set<string>;
}

export function pairKey(a: string, b: string): string {
  return a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

interface CellRef {
  row: number;
  col: number;
}

function sameCell(a: CellRef | null, b: CellRef | null): boolean {
  return a !== null && b !== null && a.row === b.row && a.col === b.col;
}

// Compact in-cell label: two decimals, leading zero dropped so "−0.89" fits a
// 44px cell at the 14px text minimum. The detail readout shows the full form.
// The sign is taken after rounding, so r = −0.003 reads "0.00", not "−0.00".
function formatFull(r: number): string {
  const fixed = Math.abs(r).toFixed(2);
  return r < 0 && Number(fixed) !== 0 ? `−${fixed}` : fixed;
}

function formatCompact(r: number): string {
  return formatFull(r).replace(/^(−?)0\./, "$1.");
}

function cellFill(r: number | null): string {
  if (r === null) return "var(--muted)";
  const pct = Math.round(Math.min(Math.abs(r), 1) * 100);
  const end = r < 0 ? "var(--corr-negative)" : "var(--corr-positive)";
  return `color-mix(in oklch, ${end} ${pct}%, var(--corr-neutral))`;
}

export function CorrelationMatrix({
  data,
  heatmapAnchorId,
}: {
  data: CorrelationMatrixData;
  heatmapAnchorId: string | undefined;
}) {
  const { columns, values, strongPairs } = data;
  const n = columns.length;

  const [hovered, setHovered] = useState<CellRef | null>(null);
  const [focused, setFocused] = useState<CellRef | null>(null);
  const [pinned, setPinned] = useState<CellRef | null>(null);
  // Roving tabindex: the whole matrix is one tab stop, arrows move within it.
  const [tabStop, setTabStop] = useState<CellRef>({ row: 0, col: 0 });
  const tableRef = useRef<HTMLTableElement>(null);

  const isStrong = useCallback(
    (row: number, col: number) =>
      row !== col && strongPairs.has(pairKey(columns[row], columns[col])),
    [columns, strongPairs],
  );

  const focusCell = (cell: CellRef) => {
    setTabStop(cell);
    tableRef.current
      ?.querySelector<HTMLButtonElement>(
        `button[data-row="${cell.row}"][data-col="${cell.col}"]`,
      )
      ?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, cell: CellRef) => {
    let next: CellRef | null = null;
    switch (e.key) {
      case "ArrowRight":
        next = { row: cell.row, col: Math.min(cell.col + 1, n - 1) };
        break;
      case "ArrowLeft":
        next = { row: cell.row, col: Math.max(cell.col - 1, 0) };
        break;
      case "ArrowDown":
        next = { row: Math.min(cell.row + 1, n - 1), col: cell.col };
        break;
      case "ArrowUp":
        next = { row: Math.max(cell.row - 1, 0), col: cell.col };
        break;
      case "Home":
        next = { row: cell.row, col: 0 };
        break;
      case "End":
        next = { row: cell.row, col: n - 1 };
        break;
      case "Escape":
        if (pinned) {
          e.preventDefault();
          setPinned(null);
        }
        return;
      default:
        return;
    }
    e.preventDefault();
    focusCell(next);
  };

  // Hover drives the transient readout for mouse/pen only. Touch has no
  // hover, so a tap goes through onClick (pin toggle) instead.
  const onPointerEnter = (e: PointerEvent<HTMLButtonElement>, cell: CellRef) => {
    if (e.pointerType !== "touch") setHovered(cell);
  };

  // Keyboard focus shows the readout; pointer-induced focus does not, or a
  // second tap to unpin would leave the still-focused cell on display.
  const onFocus = (e: FocusEvent<HTMLButtonElement>, cell: CellRef) => {
    setTabStop(cell);
    if (e.currentTarget.matches(":focus-visible")) setFocused(cell);
  };

  const shown = hovered ?? focused ?? pinned;
  const shownIsPinned = shown !== null && sameCell(shown, pinned);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-sm uppercase tracking-wider text-[var(--muted-foreground)]">
          Correlation matrix
        </span>
        {heatmapAnchorId && (
          <a
            href={`#${heatmapAnchorId}`}
            className="inline-flex items-center text-sm text-[var(--muted-foreground)] max-sm:min-h-11"
          >
            Static heatmap ↑
          </a>
        )}
      </div>

      <div className="overflow-x-auto pb-1">
        <table
          ref={tableRef}
          className="border-separate border-spacing-0.5"
          onPointerLeave={() => setHovered(null)}
        >
          <caption className="sr-only">
            Pearson correlation coefficient (r) between each pair of numeric
            columns. Correlation is not causation. Outlined cells are pairs the
            analysis flagged as strong.
          </caption>
          <thead>
            <tr>
              <td className="sticky left-0 z-10 bg-background" />
              {columns.map((c) => (
                <th
                  key={c}
                  scope="col"
                  title={c}
                  className="w-11 p-0 align-bottom text-sm font-normal text-[var(--muted-foreground)]"
                >
                  <span className="mx-auto block max-h-28 overflow-hidden text-ellipsis whitespace-nowrap pb-1 [writing-mode:vertical-rl] rotate-180">
                    {c}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {columns.map((rowName, row) => (
              <tr key={rowName}>
                <th
                  scope="row"
                  title={rowName}
                  className="sticky left-0 z-10 bg-background p-0 pr-2 text-left text-sm font-normal text-[var(--muted-foreground)]"
                >
                  {/* Truncation lives on the span: max-width on a table cell
                      itself is not honored consistently across browsers. */}
                  <span className="block max-w-24 truncate sm:max-w-40">
                    {rowName}
                  </span>
                </th>
                {columns.map((colName, col) => {
                  const r = values[row][col];
                  const cell = { row, col };
                  const strong = isStrong(row, col);
                  const isPinned = sameCell(cell, pinned);
                  const label =
                    r === null
                      ? `${rowName} and ${colName}: r not computable`
                      : `${rowName} and ${colName}: r = ${formatFull(r)}${strong ? ", flagged strong" : ""}`;
                  return (
                    <td key={colName} className="p-0">
                      <button
                        type="button"
                        data-row={row}
                        data-col={col}
                        data-strong={strong || undefined}
                        tabIndex={sameCell(cell, tabStop) ? 0 : -1}
                        aria-label={label}
                        aria-pressed={isPinned}
                        onClick={() => setPinned(isPinned ? null : cell)}
                        onKeyDown={(e) => onKeyDown(e, cell)}
                        onPointerEnter={(e) => onPointerEnter(e, cell)}
                        onFocus={(e) => onFocus(e, cell)}
                        onBlur={() => setFocused(null)}
                        style={{ background: cellFill(r) }}
                        className={
                          "flex size-11 items-center justify-center rounded-sm font-mono text-sm tabular-nums text-foreground outline-offset-2 focus-visible:outline focus-visible:outline-2 " +
                          (strong ? "ring-2 ring-inset ring-foreground " : "") +
                          (isPinned ? "outline outline-2 outline-[var(--ring)] " : "") +
                          (r === null ? "text-[var(--muted-foreground)]" : "")
                        }
                      >
                        {r === null ? "—" : formatCompact(r)}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        aria-live="polite"
        className="min-h-12 rounded-md border border-border/60 bg-[color-mix(in_oklch,var(--card)_40%,transparent)] px-3 py-2 text-sm"
      >
        {shown === null ? (
          <span className="text-[var(--muted-foreground)]">
            Hover, focus, or tap a cell for the exact pair and r. Tap again to
            dismiss.
          </span>
        ) : (
          <CellDetail
            rowName={columns[shown.row]}
            colName={columns[shown.col]}
            r={values[shown.row][shown.col]}
            strong={isStrong(shown.row, shown.col)}
            pinned={shownIsPinned}
          />
        )}
      </div>

      <Legend />
    </div>
  );
}

function CellDetail({
  rowName,
  colName,
  r,
  strong,
  pinned,
}: {
  rowName: string;
  colName: string;
  r: number | null;
  strong: boolean;
  pinned: boolean;
}) {
  const diagonal = rowName === colName;
  return (
    <span className="flex flex-col gap-0.5">
      <span className="break-words text-foreground">
        <span className="font-mono">{rowName}</span>
        {" × "}
        <span className="font-mono">{colName}</span>
        {pinned && <span className="text-[var(--muted-foreground)]"> · pinned</span>}
      </span>
      <span className="text-[var(--muted-foreground)]">
        {r === null
          ? diagonal
            ? "r not computable — this column has no variance (constant) or too few values."
            : "r not computable from this data — a constant column or too few paired values."
          : diagonal
            ? `r = ${formatFull(r)} (a column with itself)`
            : `Pearson r = ${formatFull(r)}${strong ? " — flagged as a strong correlation" : ""}. A correlation, not an explanation.`}
      </span>
    </span>
  );
}

const LEGEND_GRADIENT = `linear-gradient(to right, ${[
  -1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1,
]
  .map(cellFill)
  .join(", ")})`;

function Legend() {
  return (
    <div className="flex flex-col gap-2 text-sm text-[var(--muted-foreground)]">
      <div className="flex items-center gap-2">
        <span className="font-mono tabular-nums">{"−"}1</span>
        <span
          aria-hidden
          className="h-3 w-32 rounded-sm"
          // Stops come from cellFill itself so the legend can never drift from
          // the cells (gradient interpolation handles the neutral's `none`
          // hue differently from color-mix).
          style={{ background: LEGEND_GRADIENT }}
        />
        <span className="font-mono tabular-nums">+1</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-3 rounded-sm ring-2 ring-inset ring-foreground"
          />
          Flagged strong by the analysis
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-3 rounded-sm bg-[var(--muted)]" />
          Not computable
        </span>
      </div>
    </div>
  );
}
