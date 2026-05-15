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

export interface StatusResponse {
  analysis_id: string;
  status: AnalysisStatus;
  current_agent: string | null;
  progress_pct: number | null;
  error_message: string | null;
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
  cleaning_decisions: unknown[] | null;
  analysis_report: Record<string, unknown> | null;
  insight_report: Record<string, unknown> | null;
  executive_summary: Record<string, unknown> | null;
  chart_paths: string[] | null;
}
