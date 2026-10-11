// Helpers for the public snapshot e2e.

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, type TestInfo } from "@playwright/test";

export interface LoggedRequest {
  method: string;
  url: string;
  resourceType: string;
  frame: "main" | "iframe";
  status: number | "failed" | null;
}

// Every request the page and its frames make, in order, with its outcome.
export function logRequests(page: Page): LoggedRequest[] {
  const log: LoggedRequest[] = [];
  const byRequest = new Map<object, LoggedRequest>();
  page.on("request", (request) => {
    const entry: LoggedRequest = {
      method: request.method(),
      url: request.url(),
      resourceType: request.resourceType(),
      frame: request.frame() === page.mainFrame() ? "main" : "iframe",
      status: null,
    };
    byRequest.set(request, entry);
    log.push(entry);
  });
  page.on("response", (response) => {
    const entry = byRequest.get(response.request());
    if (entry) entry.status = response.status();
  });
  page.on("requestfailed", (request) => {
    const entry = byRequest.get(request);
    if (entry) entry.status = "failed";
  });
  return log;
}

export function expectSameOriginOnly(log: LoggedRequest[], baseURL: string | undefined): void {
  const origin = new URL(baseURL ?? "").origin;
  expect(log.length, "the page made requests").toBeGreaterThan(0);
  expect(
    log.filter((r) => new URL(r.url).origin !== origin).map((r) => r.url),
    "every request stays on the site's own origin",
  ).toEqual([]);
  expect(
    log.filter((r) => new URL(r.url).pathname.startsWith("/api")).map((r) => r.url),
    "no request goes to /api",
  ).toEqual([]);
}

export function statusCalls(log: LoggedRequest[]): string[] {
  return log.filter((r) => /\/status$/.test(new URL(r.url).pathname)).map((r) => r.url);
}

// The request log for the build report: attached to the test, and written to
// E2E_REQUEST_LOG_DIR when it is set.
export function saveRequestLog(log: LoggedRequest[], info: TestInfo, name: string): void {
  const text = log.map((r) => `${r.method} ${r.status ?? "-"} ${r.resourceType} [${r.frame}] ${r.url}`).join("\n");
  void info.attach(`requests-${name}`, { body: text, contentType: "text/plain" });
  const dir = process.env.E2E_REQUEST_LOG_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, `${name}-${info.project.name}.txt`), `${text}\n`);
}

export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "no horizontal page overflow").toBe(0);
}

// Records every localStorage call the page makes (the local client page reads
// session_id_<id>; the snapshot page must make none).
export async function spyOnLocalStorage(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const calls: string[] = [];
    Object.defineProperty(window, "__localStorageCalls", { value: calls });
    for (const method of ["getItem", "setItem", "removeItem", "clear", "key"] as const) {
      const original = Storage.prototype[method] as (...args: unknown[]) => unknown;
      Object.defineProperty(Storage.prototype, method, {
        configurable: true,
        value: function (this: Storage, ...args: unknown[]): unknown {
          if (this === window.localStorage) calls.push(method);
          return original.apply(this, args);
        },
      });
    }
  });
}

export async function localStorageCalls(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __localStorageCalls: string[] }).__localStorageCalls);
}

// Screenshots for the build report, only when E2E_SCREENSHOT_DIR is set.
export async function shot(page: Page, info: TestInfo, name: string): Promise<void> {
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(400); // let entry animations settle
  await page.screenshot({ path: path.join(dir, `${name}-${info.project.name}.png`), fullPage: true });
}
