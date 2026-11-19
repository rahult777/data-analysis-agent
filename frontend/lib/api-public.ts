// The public snapshot build's lib/api (M3a). In `npm run build:public` only,
// next.config.mjs puts this module in place of lib/api.ts, however an import
// names it, so the public site ships no axios and none of lib/api.ts's code.
// The public site makes no API request: every network function refuses before
// any request, as lib/api.ts's do in that build. Each export is typed as
// lib/api.ts's own (a type-only import, erased when built), and
// lib/mode.test.mjs checks that the two modules export the same names.
import type * as Api from "./api";
import { API_URL } from "./mode";

export { API_URL };

export const ApiError: typeof Api.ApiError = class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
};

function refuse(): never {
  throw new ApiError("This is a read-only snapshot: it makes no API requests.", null);
}

export const uploadFile: typeof Api.uploadFile = async () => refuse();
export const getAnalysisStatus: typeof Api.getAnalysisStatus = async () => refuse();
export const getAnalysis: typeof Api.getAnalysis = async () => refuse();
export const getCharts: typeof Api.getCharts = async () => refuse();
export const postQuestion: typeof Api.postQuestion = async () => refuse();
export const getQuestion: typeof Api.getQuestion = async () => refuse();
export const RESUME_TIMEOUT_MS: typeof Api.RESUME_TIMEOUT_MS = 15_000;
export const resumeAnalysis: typeof Api.resumeAnalysis = async () => refuse();
