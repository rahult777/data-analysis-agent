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

// Every response the page and its frames receive, with its status and its
// headers (names in lower case).
export interface LoggedResponse {
  url: string;
  status: number;
  headers: Record<string, string>;
}

export function logResponses(page: Page): LoggedResponse[] {
  const log: LoggedResponse[] = [];
  page.on("response", (response) => {
    log.push({ url: response.url(), status: response.status(), headers: response.headers() });
  });
  return log;
}

// The Content Security Policy violations the page and every frame it loads
// report (the securitypolicyviolation event; an init script runs in every
// frame, the sandboxed chart frames included). Call before the first
// navigation; each entry names the directive, what was blocked and where.
const VIOLATION = "csp violation: ";

export async function recordCspViolations(page: Page): Promise<string[]> {
  const violations: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    if (text.startsWith(VIOLATION)) violations.push(text.slice(VIOLATION.length));
  });
  await page.addInitScript((prefix: string) => {
    document.addEventListener("securitypolicyviolation", (event) => {
      console.log(`${prefix}${event.effectiveDirective} ${event.blockedURI || "(inline)"} on ${location.pathname}`);
    });
  }, VIOLATION);
  return violations;
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
// their subtrees; and visually hidden elements (clip rect(0px, 0px, 0px, 0px),
// as sr-only sets it). The chart cards' titles wrap since M2b.4c, so they are
// checked like everything else. Open every panel first.
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
      const hides = style.overflowX === "hidden" || style.overflowX === "clip";
      if (hides && element.scrollWidth > element.clientWidth) {
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

// Every text on the page is drawn (M2b.4b): each element under <body> that
// holds text of its own (a non-blank text node as a direct child) must be
// displayed (no `display: none` on it or above it), with `visibility: visible`
// and an effective opacity of 1 (its own times every ancestor's). Run it with
// JavaScript off: content the static HTML keeps hidden until scripts run fails
// here, and toBeVisible() would not notice an opacity of 0.
// Skipped: script, style, noscript and template elements; visually hidden
// elements (clip rect(0px, 0px, 0px, 0px), as sr-only sets it and as the
// clipping rule above skips them: the skip link until it is focused, text for
// screen readers). The chart cards' loading placeholders hold no text; since
// M2b.4c the public page hides them without JavaScript (the nojs specs check).
export async function expectTextVisible(page: Page): Promise<void> {
  const result = await page.evaluate(() => {
    const hidden: string[] = [];
    let texts = 0;
    const visit = (element: Element, opacityAbove: number, displayedAbove: boolean): void => {
      if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"].includes(element.tagName)) return;
      const style = getComputedStyle(element);
      if (style.clip === "rect(0px, 0px, 0px, 0px)") return;
      const opacity = opacityAbove * Number(style.opacity);
      const displayed = displayedAbove && style.display !== "none";
      const ownText = Array.from(element.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent ?? "")
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      if (ownText !== "") {
        texts += 1;
        const problems: string[] = [];
        if (!displayed) problems.push("not displayed");
        if (style.visibility !== "visible") problems.push(`visibility ${style.visibility}`);
        if (opacity !== 1) problems.push(`opacity ${opacity}`);
        if (problems.length > 0) hidden.push(`<${element.tagName.toLowerCase()}> ${problems.join(", ")}: ${ownText.slice(0, 60)}`);
      }
      for (const child of Array.from(element.children)) visit(child, opacity, displayed);
    };
    visit(document.body, 1, true);
    return { hidden, texts };
  });
  expect(result.texts, "the page has text").toBeGreaterThan(0);
  expect(result.hidden, "every text is displayed, visible and at full opacity").toEqual([]);
}

export interface LineStats {
  lines: number;
  // Characters in the longest line, and in the median line.
  longest: number;
  median: number;
}

// The characters per line of an element's text as it is laid out: each
// character is counted in the line box it is drawn in.
export async function lineStats(locator: Locator): Promise<LineStats> {
  return locator.evaluate((element) => {
    const perLine = new Map<number, number>();
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const length = (node.textContent ?? "").length;
      for (let i = 0; i < length; i += 1) {
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        const rect = range.getClientRects()[0];
        if (!rect) continue;
        const top = Math.round(rect.top);
        perLine.set(top, (perLine.get(top) ?? 0) + 1);
      }
    }
    const counts = Array.from(perLine.values()).sort((a, b) => a - b);
    return {
      lines: counts.length,
      longest: counts.length > 0 ? counts[counts.length - 1] : 0,
      median: counts.length > 0 ? counts[Math.floor(counts.length / 2)] : 0,
    };
  });
}

// One block of long text keeps to the reading width (owner rulings B6 and R4,
// M2b.4b), in both modes (R5): the block has a max-width narrower than a wide
// screen's column (896 px) and stays within it and within the page's column;
// on a wide screen the text inside it (`text`, an element as wide as the
// block's measure) is 29rem, 464 px, wide, give or take a card's borders.
// Soft, so one run names every block that misses it.
export async function expectReadingWidth(name: string, block: Locator, text: Locator, column: number, wide: boolean): Promise<void> {
  await expect(block, name).toHaveCount(1);
  await expect(text, `${name}: its text`).toHaveCount(1);
  const { maxWidth, width } = await block.evaluate((element) => ({ maxWidth: getComputedStyle(element).maxWidth, width: element.getBoundingClientRect().width }));
  expect.soft(maxWidth, `${name}: a max-width is set`).toMatch(/^\d+(\.\d+)?px$/);
  expect.soft(Number.parseFloat(maxWidth), `${name}: narrower than a wide screen's column`).toBeLessThan(896);
  expect.soft(width, `${name}: within its measure and the page's column`).toBeLessThanOrEqual(Math.min(Number.parseFloat(maxWidth), column) + 0.5);
  if (!wide) return;
  const measure = await text.evaluate((element) => {
    const style = getComputedStyle(element);
    return element.clientWidth - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight);
  });
  expect.soft(Math.abs(measure - 464), `${name}: its text is 29rem wide (${measure} px)`).toBeLessThanOrEqual(3);
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
