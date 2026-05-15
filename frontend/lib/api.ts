import axios from "axios";

import type {
  AnalysisResponse,
  QuestionResponse,
  StatusResponse,
  UploadResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL: API_URL });

function authHeaders(sessionId: string): Record<string, string> {
  return { "session-id": sessionId };
}

function toError(error: unknown, fallback: string): Error {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: unknown } | undefined;
    const detail = typeof data?.detail === "string" ? data.detail : undefined;
    return new Error(detail ?? error.message ?? fallback);
  }
  if (error instanceof Error) {
    return new Error(error.message);
  }
  return new Error(fallback);
}

export async function uploadFile(
  file: File,
  context?: string,
  userType?: string,
): Promise<UploadResponse> {
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
  sessionId: string,
): Promise<StatusResponse> {
  try {
    const { data } = await client.get<StatusResponse>(
      `/api/analysis/${analysisId}/status`,
      { headers: authHeaders(sessionId) },
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to fetch analysis status.");
  }
}

export async function getAnalysis(
  analysisId: string,
  sessionId: string,
): Promise<AnalysisResponse> {
  try {
    const { data } = await client.get<AnalysisResponse>(
      `/api/analysis/${analysisId}`,
      { headers: authHeaders(sessionId) },
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to fetch analysis.");
  }
}

export async function getCharts(
  analysisId: string,
  sessionId: string,
): Promise<{ chart_paths: string[] }> {
  try {
    const { data } = await client.get<{ chart_paths: string[] }>(
      `/api/analysis/${analysisId}/charts`,
      { headers: authHeaders(sessionId) },
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

export async function resumeAnalysis(
  analysisId: string,
  sessionId: string,
  response: Record<string, unknown>,
): Promise<StatusResponse> {
  try {
    const { data } = await client.post<StatusResponse>(
      `/api/analysis/${analysisId}/resume`,
      { response },
      { headers: authHeaders(sessionId) },
    );
    return data;
  } catch (error) {
    throw toError(error, "Failed to resume analysis.");
  }
}
