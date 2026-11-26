// The keyboard focus indicator check (M3a.2): shared by e2e-snapshot/focus.spec.ts
// (the build Vercel deploys) and e2e/focus.spec.ts (local mode). Not a spec.
//
// For the element that has the keyboard focus, it compares the focused and the
// unfocused render of a band around the element and counts the "strong" pixels:
// those whose two renders differ by a contrast of at least 3:1 (relative
// luminance, the way WCAG 2.2 measures a focus indicator's change, SC 2.4.13).
// A stop passes when
// - it has at least as many strong pixels as its 1 px perimeter, summed over its
//   line fragments (a wrapped link is one rect per line box, getClientRects,
//   never its bounding box);
// - every outer side of every fragment has strong pixels, counted over that
//   side's own span, between the ring's inner corners: the ends of the two
//   strokes that cross a corner count for neither side, so a ring with one
//   stroke hidden (under a sticky header, say) fails (a side that faces
//   another fragment of the same element is not required); a pixel counts for
//   a side only when it lies wholly inside the span (a box at a fraction of a
//   pixel is painted on the whole pixels it rounds to);
// - no clipping ancestor (overflow other than visible) cuts the ring: its outer
//   edge stays inside every such ancestor's padding box (an inset outline is
//   judged inside its own box).
// The band runs from 2 px inside the border box (or inside an inset ring) to
// 2 px outside the ring's outer edge, the ring read from the host's computed
// style while focused: an outline from its offset to offset + width beyond the
// border box (inside it when the offset is negative), a box-shadow ring from 0
// to its widest spread. Nothing outside the band counts: a readout that changes
// on focus, a neighbour's highlight, the element's own interior. The host is
// the focused element, or the label around a focused radio or checkbox (a pause
// option's ring is drawn by its label).
// A stop taller or wider than the window is measured as cut: the crop stops at
// the window's edge while the perimeter it needs, and its sides, are the whole
// stop's, so such a stop would fail (none the walks reach is that large).
// Determinism: the host's running transitions are finished before the ring is
// read (transition-all would leave a box-shadow mid-way), the measure waits
// until the element has stopped fading and moving (an entry animation), the
// screenshots disable animations and hide the caret, the specs ask for reduced
// motion and park the mouse at (0, 0), and both renders come from one page, so
// the font source does not decide a verdict. The renders are compared in a
// blank page of the same context: the public pages' CSP (img-src 'self') blocks
// data: images.

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page, type TestInfo } from "@playwright/test";

export interface Fragment {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FocusStop {
  // What the stop is (a skip link, a matrix cell, ...) and its name.
  kind: string;
  name: string;
  // Its line fragments, in viewport pixels, as measured.
  fragments: Fragment[];
  strong: number;
  required: number;
  // The highest contrast between the two renders in the band.
  bestRatio: number;
  sidesMissing: string[];
  clippedBy: string[];
  pass: boolean;
  focused: Buffer;
  unfocused: Buffer;
}

interface Geometry {
  kind: string;
  name: string;
  fragments: Fragment[];
  // The band's inner and outer edges, in px from each fragment's border box
  // (negative: inside it).
  inner: number;
  outer: number;
  clippedBy: string[];
  viewport: { width: number; height: number };
}

const WALK_START = "focus-walk-start";

// Runs in the page, so it uses no outer variables: what the focused element
// is, and where its ring is.
function readFocus(): Geometry | null {
  const focused = document.activeElement;
  if (!(focused instanceof HTMLElement) || focused === document.body || focused.id === "focus-walk-start") return null;
  const tag = focused.tagName.toLowerCase();
  const slot = focused.getAttribute("data-slot");
  const ariaLabel = focused.getAttribute("aria-label");
  const name = (ariaLabel ?? focused.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 60);
  let kind = tag;
  if (tag === "a") {
    const inMain = focused.closest("main") !== null;
    const inPanel = focused.closest('[data-slot="accordion-content"]') !== null;
    if (focused.getAttribute("href") === "#main") kind = "skip link";
    else if (!inMain && focused.closest("header") !== null) kind = "header link";
    else if (!inMain && focused.closest("footer") !== null) kind = "footer link";
    else if (focused.closest('[id^="chart-"]') !== null) kind = "card full-size link";
    else if (focused.classList.contains("rounded-full")) kind = "chart pill link";
    else if (inPanel && focused.closest("p") !== null) kind = "narrative chart link";
    else if (inPanel) kind = "panel link (heatmap)";
    else if (focused.closest('[data-testid="stall-notice"]') !== null) kind = "stall link";
    else kind = "page link";
  } else if (slot === "accordion-trigger") kind = "accordion trigger";
  else if (slot === "button") kind = "Button (ui)";
  else if (slot === "input") kind = "Input (ui)";
  else if (slot === "textarea") kind = "Textarea (ui)";
  else if (tag === "button" && focused.hasAttribute("data-row")) kind = "matrix cell";
  else if (tag === "button" && /clipboard/i.test(ariaLabel ?? "")) kind = "code copy button";
  else if (tag === "button" && /chart/i.test(ariaLabel ?? "")) kind = "card expand button";
  else if (focused instanceof HTMLInputElement && focused.type === "radio") kind = "pause option (radio)";
  else if (tag === "pre") kind = "code scroller (pre)";
  else if (tag === "button") kind = "button (plain)";
  else if (focused.getAttribute("role") === "button") kind = `role=button (${tag})`;
  else if (focused.id.startsWith("chart-")) kind = "chart card";

  focused.scrollIntoView({ block: "center", inline: "nearest" });
  const label =
    focused instanceof HTMLInputElement && (focused.type === "radio" || focused.type === "checkbox") ? focused.closest("label") : null;
  const host: HTMLElement = label ?? focused;
  const style = getComputedStyle(host);
  const outlineWidth = Number.parseFloat(style.outlineWidth) || 0;
  const outlineOffset = Number.parseFloat(style.outlineOffset) || 0;
  const hasOutline = style.outlineStyle !== "none" && outlineWidth > 0 && style.outlineColor !== "rgba(0, 0, 0, 0)";
  // Each shadow's four lengths: x, y, blur, spread.
  const lengths = /(-?[\d.]+)px (-?[\d.]+)px (-?[\d.]+)px (-?[\d.]+)px/g;
  let spread = 0;
  for (let match = lengths.exec(style.boxShadow); match !== null; match = lengths.exec(style.boxShadow)) {
    spread = Math.max(spread, Number.parseFloat(match[4]));
  }
  let inner = 0;
  let outer = 0;
  if (hasOutline) {
    inner = outlineOffset;
    outer = outlineOffset + outlineWidth;
  }
  if (spread > 0) {
    inner = hasOutline ? Math.min(inner, 0) : 0;
    outer = Math.max(outer, spread);
  }
  const fragments = Array.from(host.getClientRects())
    .filter((rect) => rect.width > 0 && rect.height > 0)
    .map((rect) => ({ x: rect.x, y: rect.y, width: rect.width, height: rect.height }));
  const reach = Math.max(outer, 0);
  const clippedBy: string[] = [];
  for (let ancestor = host.parentElement; ancestor !== null; ancestor = ancestor.parentElement) {
    const ancestorStyle = getComputedStyle(ancestor);
    if (ancestorStyle.overflowX === "visible" && ancestorStyle.overflowY === "visible") continue;
    const box = ancestor.getBoundingClientRect();
    const left = box.left + ancestor.clientLeft;
    const top = box.top + ancestor.clientTop;
    const right = left + ancestor.clientWidth;
    const bottom = top + ancestor.clientHeight;
    const cut = fragments.some(
      (f) => f.x - reach < left - 0.5 || f.x + f.width + reach > right + 0.5 || f.y - reach < top - 0.5 || f.y + f.height + reach > bottom + 0.5,
    );
    if (cut) {
      const classes = (ancestor.getAttribute("class") ?? "").split(/\s+/).filter(Boolean).slice(0, 3);
      clippedBy.push([ancestor.tagName.toLowerCase(), ...classes].join("."));
    }
  }
  return {
    kind,
    name,
    fragments,
    inner: Math.min(inner, 0) - 2,
    outer: Math.max(outer, 0) + 2,
    clippedBy,
    viewport: { width: window.innerWidth, height: window.innerHeight },
  };
}

// Compares the two renders in a blank page of the same context.
let scratch: Page | null = null;

async function scratchPage(page: Page): Promise<Page> {
  if (scratch === null || scratch.isClosed() || scratch.context() !== page.context()) scratch = await page.context().newPage();
  return scratch;
}

interface Compared {
  strong: number;
  bestRatio: number;
  sidesMissing: string[];
}

// A strip of the band, in crop pixels: x0, y0 (inclusive) to x1, y1 (exclusive).
type Strip = [x0: number, y0: number, x1: number, y1: number];

async function compare(page: Page, focused: Buffer, unfocused: Buffer, fragments: Fragment[], inner: number, outer: number): Promise<Compared> {
  const blank = await scratchPage(page);
  return blank.evaluate(
    async ([focusedSrc, unfocusedSrc, frags, a, b]) => {
      const load = (src: string): Promise<HTMLImageElement> =>
        new Promise<HTMLImageElement>((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve(image);
          image.onerror = () => reject(new Error("a focus crop did not decode"));
          image.src = src;
        });
      const pixels = (image: HTMLImageElement): Uint8ClampedArray => {
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const context = canvas.getContext("2d");
        if (context === null) throw new Error("no 2d canvas");
        context.drawImage(image, 0, 0);
        return context.getImageData(0, 0, image.width, image.height).data;
      };
      const [imageA, imageB] = [await load(focusedSrc), await load(unfocusedSrc)];
      const pa = pixels(imageA);
      const pb = pixels(imageB);
      const width = imageA.width;
      const linear = (v: number): number => {
        const s = v / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      const luminance = (d: Uint8ClampedArray, i: number): number => 0.2126 * linear(d[i]) + 0.7152 * linear(d[i + 1]) + 0.0722 * linear(d[i + 2]);
      // In the band: inside a fragment grown by b, outside the same fragment grown by a (a < 0: shrunk).
      const inBand = (x: number, y: number): boolean =>
        frags.some((f) => {
          const inOuter = x >= f.x - b && x < f.x + f.width + b && y >= f.y - b && y < f.y + f.height + b;
          const inInner = x >= f.x - a && x < f.x + f.width + a && y >= f.y - a && y < f.y + f.height + a;
          return inOuter && !inInner;
        });
      // Each fragment's four sides of the band, each counted over its own span only, between the ring's inner
      // corners, so the ends of the two strokes that cross a corner count for neither side: a ring whose left
      // stroke lies under a sticky header still shows its top and bottom strokes' ends beside it, and fails. For a
      // ring outside the border box that span is the fragment's own extent; an inset ring's corners lie inside the
      // box, so its span is shorter by the inset's depth at each end. A side whose strip, over the band's full
      // length, overlaps another fragment of the same element (a wrapped link's inner edge) is not required.
      // A pixel counts for a side only when it lies wholly inside the span: a box at a fraction of a pixel is
      // painted on the whole pixel rows and columns it rounds to, so a span that ends a fraction past the box's
      // painted edge would otherwise take in the next row, the gap where a hidden stroke's corner shows.
      const depth = Math.max(0, -a - 2);
      type Side = { name: string; x0: number; y0: number; x1: number; y1: number; count: number };
      const sides = frags.flatMap((f, i) =>
        (
          [
            ["top", [f.x - b, f.y - b, f.x + f.width + b, f.y - a], [f.x + depth, f.y - b, f.x + f.width - depth, f.y - a]],
            [
              "bottom",
              [f.x - b, f.y + f.height + a, f.x + f.width + b, f.y + f.height + b],
              [f.x + depth, f.y + f.height + a, f.x + f.width - depth, f.y + f.height + b],
            ],
            ["left", [f.x - b, f.y - b, f.x - a, f.y + f.height + b], [f.x - b, f.y + depth, f.x - a, f.y + f.height - depth]],
            [
              "right",
              [f.x + f.width + a, f.y - b, f.x + f.width + b, f.y + f.height + b],
              [f.x + f.width + a, f.y + depth, f.x + f.width + b, f.y + f.height - depth],
            ],
          ] as Array<[string, Strip, Strip]>
        )
          .filter(([, [x0, y0, x1, y1]]): boolean => !frags.some((g, j): boolean => j !== i && g.x < x1 && g.x + g.width > x0 && g.y < y1 && g.y + g.height > y0))
          .map(([side, , [x0, y0, x1, y1]]): Side => ({ name: frags.length > 1 ? `${side} of line ${i + 1}` : side, x0, y0, x1, y1, count: 0 })),
      );
      let strong = 0;
      let bestRatio = 1;
      for (let i = 0; i < pa.length; i += 4) {
        if (pa[i] === pb[i] && pa[i + 1] === pb[i + 1] && pa[i + 2] === pb[i + 2]) continue;
        const p = i / 4;
        const x = p % width;
        const y = Math.floor(p / width);
        if (!inBand(x, y)) continue;
        const la = luminance(pa, i);
        const lb = luminance(pb, i);
        const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
        if (ratio > bestRatio) bestRatio = ratio;
        if (ratio < 3) continue;
        strong += 1;
        for (const side of sides) if (x >= side.x0 && x + 1 <= side.x1 && y >= side.y0 && y + 1 <= side.y1) side.count += 1;
      }
      return {
        strong,
        bestRatio: Math.round(bestRatio * 100) / 100,
        sidesMissing: sides.filter((side) => side.count === 0).map((side) => side.name),
      };
    },
    [`data:image/png;base64,${focused.toString("base64")}`, `data:image/png;base64,${unfocused.toString("base64")}`, fragments, inner, outer] as const,
  );
}

// Waits until the focused element has stopped fading and moving: its effective
// opacity (its own times every ancestor's) and its box the same for three
// frames in a row. An entry animation (Framer Motion's, which the reduced-motion
// setting does not stop: the stall notice fades in) would otherwise change the
// pixels between the two renders.
async function waitUntilStill(page: Page): Promise<void> {
  await page.evaluate(() => {
    (window as unknown as { __focusStill?: unknown }).__focusStill = undefined;
  });
  await page.waitForFunction(
    () => {
      const element = document.activeElement;
      if (!(element instanceof HTMLElement)) return true;
      let opacity = 1;
      for (let node: Element | null = element; node !== null; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity);
      const r = element.getBoundingClientRect();
      const now = `${opacity} ${r.x} ${r.y} ${r.width} ${r.height}`;
      const state = window as unknown as { __focusStill?: { value: string; frames: number } };
      if (state.__focusStill !== undefined && state.__focusStill.value === now) state.__focusStill.frames += 1;
      else state.__focusStill = { value: now, frames: 0 };
      return state.__focusStill.frames >= 3;
    },
    undefined,
    { polling: "raf", timeout: 5_000 },
  );
}

// Measures the element that has the focus now; null when nothing has it.
export async function measureFocus(page: Page): Promise<FocusStop | null> {
  await page.evaluate(() => {
    const focused = document.activeElement;
    if (!(focused instanceof HTMLElement)) return;
    for (const element of [focused, focused.closest("label")]) {
      if (element === null) continue;
      for (const animation of element.getAnimations()) {
        try {
          animation.finish();
        } catch {
          // An infinite animation cannot finish; the screenshots stop it.
        }
      }
    }
    focused.scrollIntoView({ block: "center", inline: "nearest" });
  });
  await waitUntilStill(page);
  const geometry = await page.evaluate(readFocus);
  if (geometry === null) return null;
  const { fragments, inner, outer, viewport } = geometry;
  if (fragments.length === 0) throw new Error(`The focused ${geometry.kind} "${geometry.name}" has no box to measure.`);
  const x0 = Math.max(0, Math.floor(Math.min(...fragments.map((f) => f.x)) - outer - 1));
  const y0 = Math.max(0, Math.floor(Math.min(...fragments.map((f) => f.y)) - outer - 1));
  const x1 = Math.min(viewport.width, Math.ceil(Math.max(...fragments.map((f) => f.x + f.width)) + outer + 1));
  const y1 = Math.min(viewport.height, Math.ceil(Math.max(...fragments.map((f) => f.y + f.height)) + outer + 1));
  if (x1 <= x0 || y1 <= y0) throw new Error(`The focused ${geometry.kind} "${geometry.name}" is outside the viewport.`);
  const clip = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  const focused = await page.screenshot({ clip, animations: "disabled", caret: "hide" });
  await page.evaluate(() => {
    const element = document.activeElement as HTMLElement;
    (window as unknown as { __focusMeasured: HTMLElement }).__focusMeasured = element;
    element.blur();
  });
  const unfocused = await page.screenshot({ clip, animations: "disabled", caret: "hide" });
  await page.evaluate(() => (window as unknown as { __focusMeasured: HTMLElement }).__focusMeasured.focus({ preventScroll: true }));
  const local = fragments.map((f) => ({ x: f.x - x0, y: f.y - y0, width: f.width, height: f.height }));
  const compared = await compare(page, focused, unfocused, local, inner, outer);
  const required = Math.round(local.reduce((total, f) => total + 2 * (f.width + f.height), 0));
  return {
    kind: geometry.kind,
    name: geometry.name,
    fragments: fragments.map((f) => ({ x: Math.round(f.x), y: Math.round(f.y), width: Math.round(f.width), height: Math.round(f.height) })),
    strong: compared.strong,
    required,
    bestRatio: compared.bestRatio,
    sidesMissing: compared.sidesMissing,
    clippedBy: geometry.clippedBy,
    pass: compared.strong >= required && compared.sidesMissing.length === 0 && geometry.clippedBy.length === 0,
    focused,
    unfocused,
  };
}

export interface Walk {
  stops: FocusStop[];
  // Chart frames the focus entered (they are counted, not measured).
  frames: number;
  // True when the focus came back round to a stop already measured, or left the page.
  complete: boolean;
}

// Tabs from the top of the document, measuring every stop, until the focus
// comes back round or leaves the page. It starts from a node it adds at the top
// (tabIndex -1, so not a stop itself): after a click, Chromium would start the
// next Tab from the clicked element.
export async function tabWalk(page: Page, limit = 400): Promise<Walk> {
  await page.evaluate((id) => {
    let start = document.getElementById(id);
    if (start === null) {
      start = document.createElement("div");
      start.id = id;
      start.tabIndex = -1;
      start.setAttribute("style", "position:absolute;top:0;left:0;width:1px;height:1px;outline:none");
      document.body.prepend(start);
    }
    (window as unknown as { __focusWalkSeen: Element[] }).__focusWalkSeen = [];
    window.scrollTo(0, 0);
    start.focus();
  }, WALK_START);
  const stops: FocusStop[] = [];
  let frames = 0;
  for (let i = 0; i < limit; i += 1) {
    await page.keyboard.press("Tab");
    const step = await page.evaluate((id) => {
      const element = document.activeElement;
      if (element === null || element === document.body || element.id === id) return "left";
      const seen = (window as unknown as { __focusWalkSeen: Element[] }).__focusWalkSeen;
      const isFrame = element.tagName === "IFRAME";
      if (seen.indexOf(element) >= 0) return isFrame ? "in frame" : "seen";
      seen.push(element);
      return isFrame ? "frame" : "stop";
    }, WALK_START);
    if (step === "left" || step === "seen") return { stops, frames, complete: true };
    // Inside a chart's frame: Tab on until the focus leaves it.
    if (step === "in frame") continue;
    if (step === "frame") {
      frames += 1;
      continue;
    }
    const stop = await measureFocus(page);
    if (stop !== null) stops.push(stop);
  }
  return { stops, frames, complete: false };
}

// Every correlation-matrix cell by the keyboard: the matrix's tab stop first
// (focused with a key down, as a Tab would reach it), then the arrow keys, row
// by row, as the matrix's roving tabindex moves the focus.
export async function matrixWalk(page: Page): Promise<FocusStop[]> {
  const cell = (row: number, col: number): Locator => page.locator(`button[data-row="${row}"][data-col="${col}"]`);
  const size = await page.locator('button[data-row="0"]').count();
  expect(size, "the matrix has cells").toBeGreaterThan(0);
  await cell(0, 0).scrollIntoViewIfNeeded();
  await page.keyboard.press("Shift");
  await cell(0, 0).focus();
  const stops: FocusStop[] = [];
  for (let row = 0; row < size; row += 1) {
    for (let col = 0; col < size; col += 1) {
      await expect(cell(row, col)).toBeFocused();
      const stop = await measureFocus(page);
      if (stop === null) throw new Error(`Matrix cell (${row}, ${col}) lost the focus.`);
      stops.push(stop);
      if (col < size - 1) await page.keyboard.press("ArrowRight");
    }
    if (row < size - 1) {
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Home");
    }
  }
  return stops;
}

export function describeStop(stop: FocusStop): string {
  const problems = [`strong ${stop.strong}/${stop.required}`];
  if (stop.sidesMissing.length > 0) problems.push(`no strong pixels on ${stop.sidesMissing.join(", ")}`);
  if (stop.clippedBy.length > 0) problems.push(`cut by ${stop.clippedBy.join(", ")}`);
  return `${stop.kind} "${stop.name}": ${problems.join("; ")}`;
}

// Every stop passes. On a failure the first failing stop of each kind is
// attached (its focused and unfocused crops), and the message names each one.
export async function expectFocusVisible(stops: FocusStop[], info: TestInfo, label: string): Promise<void> {
  const failing = stops.filter((stop) => !stop.pass);
  const attached: string[] = [];
  for (const stop of failing) {
    if (attached.indexOf(stop.kind) >= 0) continue;
    attached.push(stop.kind);
    await info.attach(`${label}, ${stop.kind}, focused`, { body: stop.focused, contentType: "image/png" });
    await info.attach(`${label}, ${stop.kind}, unfocused`, { body: stop.unfocused, contentType: "image/png" });
  }
  expect(failing.map(describeStop), `${label}: every focus stop shows a visible indicator`).toEqual([]);
}

// The walk reached every kind of stop the page has (a guard against a walk
// that ends early). Soft, so the stops are still measured.
export function expectKinds(stops: FocusStop[], kinds: readonly string[], label: string): void {
  const seen = stops.map((stop) => stop.kind);
  expect.soft(
    kinds.filter((kind) => seen.indexOf(kind) < 0),
    `${label}: the walk reaches every kind of stop`,
  ).toEqual([]);
}

// For the build report, only when E2E_SCREENSHOT_DIR is set (as helpers.ts's
// shot()): every stop's numbers, and the focused crop of the first stop of each
// kind.
export function saveFocusReport(stops: FocusStop[], info: TestInfo, name: string): void {
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const base = `focus-${name}-${info.project.name}`;
  const numbers = stops.map((stop) => ({
    kind: stop.kind,
    name: stop.name,
    fragments: stop.fragments,
    strong: stop.strong,
    required: stop.required,
    bestRatio: stop.bestRatio,
    sidesMissing: stop.sidesMissing,
    clippedBy: stop.clippedBy,
    pass: stop.pass,
  }));
  writeFileSync(path.join(dir, `${base}.json`), `${JSON.stringify(numbers, null, 1)}\n`);
  const kinds: string[] = [];
  for (const stop of stops) {
    if (kinds.indexOf(stop.kind) >= 0) continue;
    kinds.push(stop.kind);
    writeFileSync(path.join(dir, `${base}--${stop.kind.replace(/[^a-zA-Z0-9]+/g, "-")}.png`), stop.focused);
  }
}
