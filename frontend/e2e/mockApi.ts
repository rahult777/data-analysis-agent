// A route-mocked backend for the pause-UI e2e tests. Nothing here reaches a
// real server: the app is started with NEXT_PUBLIC_API_URL = MOCK_API_URL (an
// unreachable address), every call to it is answered by page.route, and any
// call this mock does not handle is recorded and aborted.

import { readFileSync } from "node:fs";
import path from "node:path";

import type { Page, Request, Route } from "@playwright/test";

import type { AnalysisResponse, AnalysisStatus, StatusResponse } from "../lib/types";

// Deliberately unreachable by default (port 9, "discard"): not a service URL.
// The app is started with it (playwright.config.ts) so an unmocked call can
// only fail. Override with E2E_MOCK_API_URL.
export const MOCK_API_URL = process.env.E2E_MOCK_API_URL || "http://127.0.0.1:9";
export const ANALYSIS_ID = "11111111-1111-4111-8111-111111111111";
export const SESSION_ID = "22222222-2222-4222-8222-222222222222";

// The app's own response type, so the mock cannot drift from it.
export type StatusBody = StatusResponse;
type Status = AnalysisStatus;

// main.py _AGENT_MAP / _PROGRESS_MAP.
const AGENT: Record<Status, string | null> = {
  profiling: "profiler",
  domain_pause: "profiler",
  cleaning: "cleaner",
  cleaned: "cleaner",
  missing_value_pause: "cleaner",
  outlier_pause: "cleaner",
  analyzing: "analyzer",
  explaining: "explainer",
  complete: null,
  error: null,
};
const PROGRESS: Record<Status, number> = {
  profiling: 20,
  domain_pause: 20,
  cleaning: 40,
  cleaned: 45,
  missing_value_pause: 40,
  outlier_pause: 40,
  analyzing: 60,
  explaining: 80,
  complete: 100,
  error: 0,
};

export function statusBody(status: Status, pauseData: Record<string, unknown> | null = null): StatusBody {
  return {
    analysis_id: ANALYSIS_ID,
    status,
    current_agent: AGENT[status],
    progress_pct: PROGRESS[status],
    error_message: null,
    pause_data: pauseData,
  };
}

export function fixture(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path.join(__dirname, "fixtures", name), "utf8")) as Record<string, unknown>;
}

export interface ResumeCall {
  body: unknown;
  sessionHeader: string | null;
}

export type ResumeReply =
  | { status: number; body: unknown }
  | { abort: true }
  | { hang: true };

export interface HeldStatus {
  arrived: Promise<void>;
  release: (body: StatusBody) => Promise<void>;
}

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
};

export class MockApi {
  current: StatusBody = statusBody("profiling");
  readonly statusRequests: number[] = [];
  readonly resumeCalls: ResumeCall[] = [];
  resumeReplies = 0;
  private servedWaiters: Array<() => void> = [];
  private failStatus = false;
  private analysis: AnalysisResponse | null = null;
  readonly unmocked: string[] = [];
  private pendingHolds: Array<{ onArrive: () => void; wait: Promise<StatusBody> }> = [];
  private uploadHandler: () => Promise<ResumeReply> | ResumeReply = () => ({
    status: 500,
    body: { detail: "no upload handler set in this test" },
  });
  private resumeHandler: (call: ResumeCall) => Promise<ResumeReply> | ResumeReply = () => ({
    status: 500,
    body: { detail: "no resume handler set in this test" },
  });

  constructor(private readonly page: Page) {}

  async install(): Promise<void> {
    await this.page.route(`${MOCK_API_URL}/**`, (route) => this.handle(route));
  }

  setStatus(body: StatusBody): void {
    this.current = body;
  }

  // The full result GET /api/analysis/{id} returns once the status is complete.
  setAnalysis(body: AnalysisResponse): void {
    this.analysis = body;
  }

  onResume(handler: (call: ResumeCall) => Promise<ResumeReply> | ResumeReply): void {
    this.resumeHandler = handler;
  }

  onUpload(handler: () => Promise<ResumeReply> | ResumeReply): void {
    this.uploadHandler = handler;
  }

  // Resolves when the next status request has been answered — right after an
  // interval poll, so the next one is about 3 s away.
  nextStatusServed(): Promise<void> {
    return new Promise((resolve) => this.servedWaiters.push(resolve));
  }

  // From now on, every status request fails as a network error.
  failStatusRequests(): void {
    this.failStatus = true;
  }

  // The next status request waits until release(); the test decides what it
  // finally returns (typically a stale body).
  holdNextStatus(): HeldStatus {
    let onArrive: () => void = () => undefined;
    const arrived = new Promise<void>((resolve) => {
      onArrive = resolve;
    });
    let releaseWith: (body: StatusBody) => void = () => undefined;
    const wait = new Promise<StatusBody>((resolve) => {
      releaseWith = resolve;
    });
    let fulfilled: () => void = () => undefined;
    const done = new Promise<void>((resolve) => {
      fulfilled = resolve;
    });
    this.pendingHolds.push({
      onArrive,
      wait: wait.then((body) => {
        fulfilled();
        return body;
      }),
    });
    return {
      arrived,
      release: async (body: StatusBody) => {
        releaseWith(body);
        await done;
      },
    };
  }

  private async handle(route: Route): Promise<void> {
    const request: Request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === `/api/analysis/${ANALYSIS_ID}/status`) {
      this.statusRequests.push(Date.now());
      if (this.failStatus) {
        await route.abort("failed");
        return;
      }
      const hold = this.pendingHolds.shift();
      let body = this.current;
      if (hold) {
        hold.onArrive();
        body = await hold.wait;
      }
      await this.json(route, 200, body);
      for (const served of this.servedWaiters.splice(0)) served();
      return;
    }
    if (request.method() === "GET" && url.pathname === `/api/analysis/${ANALYSIS_ID}` && this.analysis !== null) {
      await this.json(route, 200, this.analysis);
      return;
    }
    if (request.method() === "POST" && url.pathname === `/api/analysis/${ANALYSIS_ID}/resume`) {
      const call: ResumeCall = {
        body: request.postDataJSON() as unknown,
        sessionHeader: (await request.allHeaders())["session-id"] ?? null,
      };
      this.resumeCalls.push(call);
      const reply = await this.resumeHandler(call);
      if ("hang" in reply) return; // never answered: the client's timeout decides
      if ("abort" in reply) {
        await route.abort("failed");
        return;
      }
      await this.json(route, reply.status, reply.body);
      this.resumeReplies += 1;
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/upload") {
      const reply = await this.uploadHandler();
      if ("hang" in reply) return;
      if ("abort" in reply) {
        await route.abort("failed");
        return;
      }
      await this.json(route, reply.status, reply.body);
      return;
    }
    this.unmocked.push(`${request.method()} ${url.pathname}`);
    await route.abort("failed");
  }

  private async json(route: Route, status: number, body: unknown): Promise<void> {
    await route.fulfill({
      status,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }
}

export async function openAsOwner(page: Page): Promise<void> {
  await page.addInitScript(
    ([id, sid]) => {
      window.localStorage.setItem(`session_id_${id}`, sid);
    },
    [ANALYSIS_ID, SESSION_ID],
  );
  await page.goto(`/analysis/${ANALYSIS_ID}`);
}

export async function openAsVisitor(page: Page): Promise<void> {
  await page.goto(`/analysis/${ANALYSIS_ID}`);
}
