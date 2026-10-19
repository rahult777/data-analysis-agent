// Helpers for the public snapshot e2e.

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page, type TestInfo } from "@playwright/test";

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

// The opacity an element is drawn with: its own computed opacity times every
// ancestor's (computed opacity is not inherited). toBeVisible() counts opacity
// 0 as visible, so content kept hidden until JavaScript runs needs this check.
export async function effectiveOpacity(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    let opacity = 1;
    for (let node: Element | null = element; node; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity);
    return opacity;
  });
}

// True when `a` comes before `b` in document order.
export async function comesBefore(a: Locator, b: Locator): Promise<boolean> {
  return a.evaluate(
    (element, other) => Boolean(other && element.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING),
    await b.elementHandle(),
  );
}

export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "no horizontal page overflow").toBe(0);
}

// The clipping rule (M2b.3b.2): nothing under <main> may hide content
// sideways. Fails on any element whose computed overflow-x is hidden or clip
// and whose content is wider than its box (scrollWidth > clientWidth), naming
// each one. It decides by overflow-x alone: CSS computes a visible overflow-y
// to auto beside a hidden overflow-x, and such an element is still checked.
// Skipped: elements that are not displayed; horizontal scroll containers
// (overflow-x auto or scroll: the code blocks, the correlation matrix) and
// their subtrees; visually hidden elements (clip rect(0px, 0px, 0px, 0px), as
// sr-only sets it); and a chart card's title, which an ellipsis truncates by
// design (card-title wrapping is an M2b.4 task). Open every panel first.
export async function expectNoClipping(page: Page): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const clipped = await page.evaluate(() => {
    const found: string[] = [];
    const scrolls = (value: string) => value === "auto" || value === "scroll";
    const visit = (element: Element): void => {
      const style = getComputedStyle(element);
      if (style.display === "none") return;
      if (scrolls(style.overflowX)) return;
      if (style.clip === "rect(0px, 0px, 0px, 0px)") return;
      const cardTitle = style.textOverflow === "ellipsis" && element.closest('[id^="chart-"]') !== null;
      const hides = style.overflowX === "hidden" || style.overflowX === "clip";
      if (hides && !cardTitle && element.scrollWidth > element.clientWidth) {
        const text = (element.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 80);
        found.push(`<${element.tagName.toLowerCase()} class="${element.getAttribute("class") ?? ""}"> ${element.scrollWidth}/${element.clientWidth}: ${text}`);
      }
      for (const child of Array.from(element.children)) visit(child);
    };
    const main = document.querySelector("main");
    if (main === null) return ["no <main> on the page"];
    visit(main);
    return found;
  });
  expect(clipped, "no element clips its content sideways").toEqual([]);
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
