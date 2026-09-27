// Narrowing for GET /status `pause_data`, which is raw agent JSON
// (decisions.md 2026-09-22). Every field the pause UI renders is read through
// here: a missing or malformed field becomes null or a fallback, and a
// question the UI cannot render or answer becomes an "unrenderable" view —
// never a crash, never a form that cannot be submitted.

import type { AnalysisStatus, PauseStatus } from "./types";

export const PAUSE_STATUSES: ReadonlyArray<PauseStatus> = [
  "domain_pause",
  "missing_value_pause",
  "outlier_pause",
];

export const DOMAIN_CONFIDENCE_THRESHOLD = 80;
// main.py _MAX_CORRECTED_DOMAIN_LENGTH (checked on the stripped text).
export const MAX_CORRECTED_DOMAIN_LENGTH = 200;

export function isPauseStatus(status: AnalysisStatus | null): status is PauseStatus {
  return status !== null && (PAUSE_STATUSES as ReadonlyArray<string>).includes(status);
}

export interface PauseOption {
  id: string;
  label: string;
  // What choosing it does, shown before the user confirms: an impute option's
  // method and assumption, or any other option's consequence.
  details: string[];
}

interface PauseBase {
  // Identifies one question within a run: status + column_name. Since F3's
  // repeat guard a (pause type, column) pair is never asked twice, and there
  // is at most one domain pause.
  key: string;
  status: PauseStatus;
}

export interface DomainPauseView extends PauseBase {
  kind: "domain";
  hypothesis: string;
  isUnknown: boolean;
  score: number | null;
  signals: string[];
}

export interface MissingValuePauseView extends PauseBase {
  kind: "missing_value";
  columnName: string;
  missingCount: number | null;
  missingPct: number | null;
  totalRows: number | null;
  represents: string | null;
  provenance: string | null;
  domainContext: string | null;
  options: PauseOption[];
}

export interface OutlierPauseView extends PauseBase {
  kind: "outlier";
  columnName: string;
  // In an outlier pause `domain_context` is this enum; in a missing-value
  // pause the same key is prose.
  context: "medical" | "financial" | null;
  outlierCount: number | null;
  outlierValue: number | null;
  sdDistance: number | null;
  columnMean: number | null;
  columnStd: number | null;
  note: string | null;
  options: PauseOption[];
}

export interface UnrenderablePauseView extends PauseBase {
  kind: "unrenderable";
}

export type PauseView =
  | DomainPauseView
  | MissingValuePauseView
  | OutlierPauseView
  | UnrenderablePauseView;

export type AnswerableView = DomainPauseView | MissingValuePauseView | OutlierPauseView;

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function pauseKey(status: PauseStatus, pauseData: unknown): string {
  const column = asRecord(pauseData)?.column_name;
  return `${status}|${typeof column === "string" ? column : ""}`;
}

function readOptions(
  raw: unknown,
  fallbackLabel: (id: string) => string,
  detailsOf: (option: Record<string, unknown>) => string[],
): PauseOption[] {
  if (!Array.isArray(raw)) return [];
  const options: PauseOption[] = [];
  for (const entry of raw) {
    const option = asRecord(entry);
    const id = asText(option?.id);
    if (option === null || id === null || options.some((o) => o.id === id)) continue;
    options.push({
      id,
      label: asText(option.label) ?? fallbackLabel(id),
      details: detailsOf(option),
    });
  }
  return options;
}

function consequenceOf(option: Record<string, unknown>): string[] {
  const consequence = asText(option.consequence);
  return consequence ? [capitalize(consequence)] : [];
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function missingValueLabel(column: string): (id: string) => string {
  return (id) =>
    ({
      impute: `Impute the missing values in \`${column}\``,
      exclude_column: `Exclude \`${column}\` from analysis entirely`,
      exclude_rows: `Exclude the rows where \`${column}\` is missing`,
      preserve_missingness: `Keep \`${column}\` as it is`,
    })[id] ?? id;
}

function outlierLabel(id: string): string {
  return (
    {
      include_with_annotation: "Include the outlier values, annotated",
      exclude_pending_clinical_review: "Exclude the outlier values pending clinical review",
      treat_as_valid: "Treat the outlier values as valid data",
      flag_as_suspected_error: "Flag the outlier values as suspected errors",
    }[id] ?? id
  );
}

export function parsePause(status: PauseStatus, raw: unknown): PauseView {
  const key = pauseKey(status, raw);
  const unrenderable: UnrenderablePauseView = { kind: "unrenderable", key, status };
  const data = asRecord(raw);
  if (data === null) return unrenderable;

  if (status === "domain_pause") {
    const hypothesis = asText(data.domain_hypothesis);
    const ids = readOptions(data.options, (id) => id, () => []).map((o) => o.id);
    // Only confirm and correct can be answered (build_domain_resolution);
    // Python writes exactly these since Build L, so anything else is a
    // question the UI could not answer.
    if (
      data.type !== "domain_confirmation_required" ||
      hypothesis === null ||
      !ids.includes("confirm") ||
      !ids.includes("correct")
    ) {
      return unrenderable;
    }
    const signals = Array.isArray(data.supporting_signals)
      ? data.supporting_signals.filter((s): s is string => asText(s) !== null)
      : [];
    return {
      kind: "domain",
      key,
      status,
      hypothesis,
      isUnknown: hypothesis.trim().toLowerCase() === "unknown",
      score: asNumber(data.domain_confidence_score),
      signals,
    };
  }

  const columnName = typeof data.column_name === "string" && data.column_name !== "" ? data.column_name : null;
  if (columnName === null) return unrenderable;

  if (status === "missing_value_pause") {
    if (data.type !== "missing_value_decision_required") return unrenderable;
    const options = readOptions(data.options, missingValueLabel(columnName), (option) => {
      if (option.id !== "impute") return consequenceOf(option);
      const method = asText(option.method);
      const assumption = asText(option.assumption);
      return [
        ...(method ? [`Method: ${method}.`] : []),
        ...(assumption ? [`Assumption: ${assumption}`] : []),
      ];
    });
    if (options.length === 0) return unrenderable;
    return {
      kind: "missing_value",
      key,
      status,
      columnName,
      missingCount: asNumber(data.missing_count),
      missingPct: asNumber(data.missing_pct),
      totalRows: asNumber(data.total_rows),
      represents: asText(data.what_this_column_represents),
      provenance: asText(data.provenance_interpretation),
      domainContext: asText(data.domain_context),
      options,
    };
  }

  if (data.type !== "outlier_decision_required") return unrenderable;
  const options = readOptions(data.options, outlierLabel, consequenceOf);
  if (options.length === 0) return unrenderable;
  const context =
    data.domain_context === "medical" || data.domain_context === "financial"
      ? data.domain_context
      : null;
  const note =
    context === "medical"
      ? asText(data.clinical_significance_note)
      : context === "financial"
        ? asText(data.financial_context_note)
        : (asText(data.financial_context_note) ?? asText(data.clinical_significance_note));
  return {
    kind: "outlier",
    key,
    status,
    columnName,
    context,
    outlierCount: asNumber(data.outlier_count),
    outlierValue: asNumber(data.outlier_value),
    sdDistance: asNumber(data.sd_distance),
    columnMean: asNumber(data.column_mean),
    columnStd: asNumber(data.column_std),
    note,
    options,
  };
}

// The inner `response` for POST /resume (decisions.md 2026-09-22): pause_type
// is the active status and column_name is echoed exactly as stored.
export function buildResumeResponse(
  view: AnswerableView,
  optionId: string,
  correctedDomain?: string,
): Record<string, unknown> {
  if (view.kind === "domain") {
    return optionId === "correct"
      ? { pause_type: view.status, option_id: optionId, corrected_domain: (correctedDomain ?? "").trim() }
      : { pause_type: view.status, option_id: optionId };
  }
  return { pause_type: view.status, column_name: view.columnName, option_id: optionId };
}
