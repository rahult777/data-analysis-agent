import axios from "axios";

import { API_URL, isSnapshot } from "./mode";
import type {
  AnalysisResponse,
  QuestionResponse,
  StatusResponse,
  UploadResponse,
} from "./types";

export { API_URL };

const client = axios.create({ baseURL: API_URL });

// Only the strict POST routes (question, resume) take a session-id; the
// read-only GETs are public by analysis_id (see decisions.md 2026-09-21).
function authHeaders(sessionId: string): Record<string, string> {
  return { "session-id": sessionId };
}

// Carries the HTTP status (null for network failures) so callers can tell a
// genuine 404 apart from a transient error. Still an Error, so existing
// `instanceof Error` / `.message` handling is unchanged.
export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// The public snapshot build makes no API request: every network function
// below refuses before one starts.
function refuseInSnapshot(): void {
  if (isSnapshot) {
    throw new ApiError("This is a read-only snapshot: it makes no API requests.", null);
  }
}

// Where a chart file is served. Local mode: the backend's /charts route. The
// snapshot build copies the charts into out/demo/charts/ and Vercel strips
// ".html" from exported files, so an HTML chart's URL drops it; PNG names stay.
export function chartUrl(filename: string): string {
  if (isSnapshot) return `/demo/charts/${filename.replace(/\.html$/, "")}`;
  return `${API_URL}/charts/${filename}`;
}

function toError(error: unknown, fallback: string): ApiError {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: unknown } | undefined;
    const detail = typeof data?.detail === "string" ? data.detail : undefined;
    return new ApiError(detail ?? error.message ?? fallback, error.response?.status ?? null);
  }
  if (error instanceof Error) {
    return new ApiError(error.message, null);
  }
  return new ApiError(fallback, null);
}

export async function uploadFile(
  file: File,
  context?: string,
  userType?: string,
): Promise<UploadResponse> {
  refuseInSnapshot();
  const formData = new FormData();
  formData.append("file", file);
  if (context) formData.append("context", context);
  if (userType) formData.append("user_type", userType);
  try {
    const { data } = await client.post<UploadResponse>("/api/upload", formData);
    return data;
  } catch (error) {
    throw toError(error, "Failed to upload file.");
  }
}

export async function getAnalysisStatus(
  analysisId: string,
): Promise<StatusResponse> {
  refuseInSnapshot();
  try {
    const { data } = await client.get<StatusResponse>(
      `/api/analysis/${analysisId}/status`,
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to fetch analysis status.");
  }
}

export async function getAnalysis(
  analysisId: string,
): Promise<AnalysisResponse> {
  refuseInSnapshot();
  try {
    const { data } = await client.get<AnalysisResponse>(
      `/api/analysis/${analysisId}`,
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to fetch analysis.");
  }
}

export async function getCharts(
  analysisId: string,
): Promise<{ chart_paths: string[] }> {
  refuseInSnapshot();
  try {
    const { data } = await client.get<{ chart_paths: string[] }>(
      `/api/analysis/${analysisId}/charts`,
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to fetch charts.");
  }
}

export async function postQuestion(
  analysisId: string,
  sessionId: string,
  question: string,
): Promise<QuestionResponse> {
  refuseInSnapshot();
  try {
    const { data } = await client.post<QuestionResponse>(
      `/api/analysis/${analysisId}/question`,
      { question },
      { headers: authHeaders(sessionId) },
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to post question.");
  }
}

export async function getQuestion(
  analysisId: string,
  questionId: string,
): Promise<QuestionResponse> {
  refuseInSnapshot();
  try {
    const { data } = await client.get<QuestionResponse>(
      `/api/analysis/${analysisId}/question/${questionId}`,
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to fetch question.");
  }
}

// Per request, not an axios default: uploads of up to 100MB share this client.
// A resume that times out may still have been applied, so callers refetch
// the status instead of assuming it failed.
export const RESUME_TIMEOUT_MS = 15_000;

export async function resumeAnalysis(
  analysisId: string,
  sessionId: string,
  response: Record<string, unknown>,
): Promise<StatusResponse> {
  refuseInSnapshot();
  try {
    const { data } = await client.post<StatusResponse>(
      `/api/analysis/${analysisId}/resume`,
      { response },
      { headers: authHeaders(sessionId), timeout: RESUME_TIMEOUT_MS },
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to resume analysis.");
  }
}
