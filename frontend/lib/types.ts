export type AnalysisStatus =
  | "profiling"
  | "cleaning"
  | "cleaned"
  | "analyzing"
  | "explaining"
  | "complete"
  | "error"
  | "domain_pause"
  | "missing_value_pause"
  | "outlier_pause";

export type QuestionStatus = "pending" | "answering" | "complete" | "error";

export type PauseStatus = "domain_pause" | "missing_value_pause" | "outlier_pause";

export interface StatusResponse {
  analysis_id: string;
  status: AnalysisStatus;
  current_agent: string | null;
  progress_pct: number | null;
  error_message: string | null;
  // The active pause question, set only in a pause status. Raw agent JSON
  // (decisions.md 2026-09-22) — never read it directly; narrow it with
  // parsePause (lib/pause.ts).
  pause_data: Record<string, unknown> | null;
}

export interface UploadResponse {
  analysis_id: string;
  filename: string;
  status: string;
  message: string;
  session_id: string;
}

export interface QuestionRequest {
  question: string;
}

export interface QuestionResponse {
  question_id: string;
  analysis_id: string;
  question: string;
  answer: string | null;
  pandas_code: string | null;
  status: QuestionStatus;
}

export interface PauseResumeRequest {
  response: Record<string, unknown>;
}

export interface CleaningDecision {
  column_name: string | null;
  issue: string;
  action: string;
  reason: string;
}

export interface AnalysisResponse {
  id: string;
  filename: string;
  status: AnalysisStatus;
  created_at: string;
  row_count: number | null;
  column_count: number | null;
  data_quality_score: number | null;
  profile_report: Record<string, unknown> | null;
  cleaning_report: Record<string, unknown> | null;
  cleaning_decisions: CleaningDecision[] | null;
  analysis_report: Record<string, unknown> | null;
  insight_report: Record<string, unknown> | null;
  executive_summary: Record<string, unknown> | null;
  chart_paths: string[] | null;
}

// What the results view (AnalysisResults) reads. The local fetch
// (AnalysisResponse) and the public snapshot (SnapshotAnalysis) both satisfy it.
export type AnalysisView = Pick<
  AnalysisResponse,
  | "filename"
  | "row_count"
  | "column_count"
  | "data_quality_score"
  | "cleaning_decisions"
  | "analysis_report"
  | "insight_report"
  | "executive_summary"
  | "chart_paths"
>;

// One analysis in the public snapshot build: exactly the fields the results
// view reads, plus cleaning_report.summary (for M2b.3's header). Enforced at
// build time by lib/snapshot-rules.mjs, which rejects any other key at the top
// level and inside cleaning_report, analysis_report, insight_report and
// executive_summary.
// Type aliases, not interfaces: an interface is not assignable to
// AnalysisResponse's Record<string, unknown> fields. Inside the free-form
// agent content every field is optional, as in InsightReport.tsx.
export type SnapshotAnalysis = {
  id: string;
  filename: string;
  row_count: number;
  column_count: number;
  data_quality_score: number;
  cleaning_report: { summary: SnapshotCleaningSummary };
  cleaning_decisions: CleaningDecision[];
  analysis_report: { correlation_matrix: SnapshotCorrelationMatrix };
  insight_report: SnapshotInsightReport;
  executive_summary: SnapshotExecutiveSummary;
  chart_paths: string[];
};

export type SnapshotCleaningSummary = {
  rows_before: number;
  rows_after: number;
  rows_removed: number;
  columns_before: number;
  columns_after: number;
  columns_removed: number;
};

export type SnapshotCorrelationMatrix = {
  matrix: Record<string, Record<string, number | null>>;
  strong_pairs?: { col1: string; col2: string }[];
};

export type SnapshotInsightReport = {
  analyst_layer: { narrative?: string; chart_references?: string[] };
  open_questions: { question?: string; why_unanswerable?: string; what_data_would_answer?: string }[];
  technical_layer: {
    statistical_methodology?: string;
    code_blocks?: string[];
    limitations?: string;
    sophistication_suggestions?: string;
    self_evaluation_notes?: string;
    lead_override_note?: string | null;
  };
  user_question_addressed: string | null;
};

export type SnapshotExecutiveSummary = {
  bullets: { finding?: string; context?: string; recommended_action?: string }[];
};
