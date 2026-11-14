# UI and Frontend Specification

This document contains the complete UI design rules, component specifications, and frontend behavior for the Data Analysis Agent system. Load this doc when building, modifying, or designing any frontend component, page, or user-facing interaction. Do not build or modify any UI without reading this document in full first.

---

## Core Design Principles

**Dark mode is the default.** There is no light mode toggle. The system is built for dark mode from the ground up. Every color, shadow, and contrast decision assumes a dark background.

**Zero generic AI aesthetic.** This system must not look like every other AI tool. No gradient blobs. No floating orbs. No "futuristic" typography gimmicks. Clean, precise, data-focused design. The aesthetic should communicate professionalism and trust — the same feeling a senior analyst's polished report gives.

**Every UI component is built using the Frontend Design plugin.** No component is built without it. Generic AI-generated UI is not acceptable for a system at this level.

**Production quality on every component.** Every component is tested at 320px minimum width. Animated entrances and layout changes use Framer Motion, and small color and size changes use CSS transitions (see Animation Specification). Every interactive element has appropriate hover and focus states.

**Color system:** Use shadcn/ui tokens exclusively. Never raw hex values in components. This ensures consistency and makes future theme changes easy.

---

## Two Modes

The frontend builds in one of two modes, fixed at build time by `NEXT_PUBLIC_DATA_SOURCE` (decisions.md 2026-10-09):
- **Local mode** (unset; `npm run dev`, `npm run build`): the pages below, backed by the API.
- **Public snapshot** (`npm run build:public`): static pages of saved analyses, with no API at all.
  - "/" is the landing page (M2b.4b; decisions.md 2026-11-12): "Omnalynt" as the h1 and the tagline under it; a lead, what Omnalynt is, with "Open the example analysis" under it; "How it works", the four agents in their order on one vertical line, with a diamond on the two steps where the run can stop and ask a person (the Profiler and the Cleaner, explained by a key sentence) and a dot on the other two; "The example", fixed sentences and one card per analysis with its file name, its size before cleaning and "Open the example analysis"; and the read-only line. A static server component in a 34rem column, with no motion and plain `<a>` links. Its copy states only what the code or the published snapshot shows and never says "upload" or "you" (the pauses ask "the person running it"). No upload UI.
  - `/analysis/[id]` shows the finished results only, already loaded: no progress view, no polling, no localStorage. One line takes the question box's place: "This is a read-only copy of a finished analysis, so you can't ask questions about its data here." Its h1 is "Example analysis" (local mode's results page keeps "Analysis"). Its three layers are in the static HTML and read without JavaScript (InsightReport.tsx below).
  - Between the page's h1 and the results header, an "About this example" section (an h2 and one paragraph) shows the analysis's note from the manifest: the owner's plain text, with no motion, so it reads without JavaScript. Its box keeps to the reading width (29rem of text). Snapshot mode only: local mode and "/" show no note (decisions.md 2026-10-17).
  - Charts come from the site's own `/demo/charts/`.
  - Any other address gets the 404 page.
  - Every page, the 404 included, carries the site's header, footer and skip link (Site Identity, below).
  - On Vercel, `frontend/vercel.json` gives every page and every chart file its response headers (docs/infrastructure.md; decisions.md 2026-11-13).

Both modes serve `public/third-party-notices.txt` at `/third-party-notices.txt`: the third-party notice for plotly.js, whose bundle the interactive chart loads (the static export copies it into `out/`).

---

## Site Identity

The site is Omnalynt (decisions.md 2026-11-11). The root layout (`app/layout.tsx`) sets the head every page shares; a page adds only its own title, description and canonical link.
- **Titles:** "Omnalynt" on "/", "Example analysis · Omnalynt" on a public analysis page, "Analysis · Omnalynt" on local mode's results page and "Page not found · Omnalynt" on the 404 (the layout's template, "%s · Omnalynt"). "Omnalynt" is the h1 of "/" in both modes.
- **Descriptions:** the site's, in both modes: "Four AI agents profile, clean and analyze a spreadsheet, then write one report at three depths, pausing to ask a person about an uncertain domain, missing values and outliers." A public analysis page has its own: "A saved run of Omnalynt's four AI agents, shown read-only: the cleaning decisions, the charts and the report at three depths. Nothing the agents wrote has been corrected." No copy on a public page contains "upload".
- **Canonical links:** per page, never in the layout, where one would reach the 404: "/" as the bare site address and each analysis at its own address. Public build only: they come from `NEXT_PUBLIC_SITE_URL` (docs/infrastructure.md).
- **The link preview:** every page takes it from the layout: Open Graph and a `summary_large_image` Twitter card, with the page's own title and description and the committed card, `app/opengraph-image.png` (1200 × 630: the name, the mark's line run on as a pipeline, and the tagline "An agentic analytics pipeline: LLM reasoning, deterministic execution, human checkpoints."), whose alt text is `app/opengraph-image.alt.txt`. No page sets an `openGraph` of its own: Next merges metadata shallowly, so it would replace the layout's and drop the card.
- **The mark and the icons:** a decision node on a pipeline (a diamond on a line) on a rounded tile: `app/icon.svg`, `favicon.ico` (16, 32 and 48 px) and `apple-icon.png` (180 px), generated with the card by `scripts/brand-assets.mjs` (docs/infrastructure.md, "Brand assets"). The SVG is plain shapes, so a header can draw its path inline with `currentColor`; an `<img>` there would change the chart tests' image counts.
- **Viewport:** a dark color scheme, and the theme color `#0a0a0a`, the dark background token's value in sRGB hex: a meta tag can't read a CSS variable, and some browsers and link-preview apps don't parse oklch. The brand files also carry the dark tokens' values; everything styled still uses the tokens. Next's default `width=device-width, initial-scale=1` stays.
- **robots.txt and sitemap.xml:** in the public build every page is allowed, and the sitemap lists "/" and each analysis at the site's address; local mode disallows everything and lists nothing.
- **Header, footer and skip link** (public build only; decisions.md 2026-11-12): the root layout renders them around every page, the 404 included, as landmarks outside the page's `<main id="main">`. The skip link, "Skip to main content", comes first and is visually hidden until it has focus; it moves the focus to `<main>`, which takes it itself (`tabIndex={-1}`) and draws no ring (`outline-none`). The header: the mark (app/icon.svg's path, drawn inline in `currentColor`) with "Omnalynt", linking home, and "GitHub", the repository. The footer: "Source on GitHub", "Third-party notices" (`/third-party-notices.txt`) and "Built by Rahul Tanikanti", the name linking to the owner's GitHub profile, which lib/site.ts derives from `NEXT_PUBLIC_GITHUB_URL` (its origin plus the owner). `components/SiteHeader.tsx` and `components/SiteFooter.tsx` are server components that import lib/site.ts, which client code never does. Plain `<a>` links of at least 44 px, text of at least 14 px, no motion and no CSS transition. The body is a full-height flex column, so the footer sits at the bottom of a short page. Local mode's pages have none of them.

---

## Page Structure

### Page 1 — Home (/)

The upload page. This is the first thing a user sees.

**Layout:** Single column, centered, generous whitespace. The upload zone is the dominant element on the page.

**Upload Zone:**
- Large drag-and-drop target — minimum 300px tall on desktop, full width on mobile
- Clear visual indication of drag state (border color change, background tint)
- Accepts CSV and Excel files only — enforce this in the UI before the API call
- File format icons shown inside the zone (CSV icon, Excel icon)
- On file selection: show file preview immediately before analysis starts
  - File name
  - File size (human-readable: KB, MB)
  - Column count and row count if quickly detectable
  - A "Looks good — start analysis" button and a "Choose a different file" option

**Optional Context Field:**
- Text input below the upload zone
- Label: "What would you like to understand about this data? (optional)"
- Placeholder: "e.g. Why did our Q3 revenue drop? Which products have the highest return rates?"
- No character limit — let the user write as much as they want
- This field is not required — never block upload because it is empty

**User Type Selection:**
- Three-option selector below the context field
- Label: "What best describes you? (optional)"
- Options: Business Owner, Data Analyst, Data Scientist
- Displayed as card-style toggle buttons, not a dropdown
- No option pre-selected — all three options shown as equal choices
- Subtle description under each option:
  - Business Owner: "I want clear findings and recommended actions"
  - Data Analyst: "I want statistical rigor and full methodology"
  - Data Scientist: "I want complete transparency including all code and decisions"

**Start Analysis Button:**
- Appears after a valid file is selected
- Primary button, prominent
- Label: "Start Analysis"
- Disabled state while upload is in progress

---

### Page 2 — Analysis Results (/analysis/[id])

The results page. This page has two distinct states: pipeline running and pipeline complete.

#### State 1 — Pipeline Running

When status is anything other than `complete` or `error`, the page shows the live progress view.

**AnalysisProgress Component:**
- Full-width component at top of page
- Shows the 4-agent pipeline as a horizontal sequence of stages
- Each stage: icon + agent name + status indicator
  - Stages: Profiler -> Cleaner -> Analyzer -> Explainer
  - Status indicators: waiting (grey), active (animated, brand color), complete (green checkmark), error (red)
- The currently active agent is highlighted and animated — the user can see exactly which agent is running
- Progress percentage shown as a subtle progress bar (20% / 40% / 60% / 80% / 100%)
- Agent descriptions shown below the active agent name:
  - Profiler active: "Examining your data — understanding what it is and where it came from"
  - Cleaner active: "Making intelligent cleaning decisions based on your data's domain"
  - Analyzer active: "Running deep statistical investigation"
  - Explainer active: "Translating findings into insights for you"
- Polling behavior: frontend polls `/api/analysis/{id}/status` every 3 seconds. The `current_agent` field in the response drives which stage is highlighted.

**Pause State Display:**
When the pipeline enters a pause state (domain confirmation, a missing-value decision or an outlier decision), AnalysisProgress shows the question inline below the pipeline (`PauseQuestion.tsx`, Build L):
- Clear visual distinction from the normal progress view (a primary-bordered card). Visible by default: the heading, one fact line (the domain hypothesis and its confidence score; or the column's counts "in the uploaded file"; or the outlier count, the most extreme value and the context chip), the options, the chosen option's details and "Continue with this choice"
- **The model's reasoning is behind a collapsed disclosure, above the options** (Build L follow-up): "Why the Cleaner is asking" — for a missing-value pause with the sub-labels "What this column is", "What the missingness likely means" and "What each choice costs here"; for an outlier pause the domain note — and, for the domain pause, "What it based this on (N)" with the signals as a list. It is a `<button aria-expanded aria-controls>` whose content enters and leaves through Framer Motion (slide up and fade, 300ms), rendered outside the options' fieldset so visitors can open it. Its state resets with each new question
- **Display-only capitalization.** Model fragments (the reasoning blocks, a note, an option's consequence) start with a capital letter only when their first word is plain lowercase letters — not a name with `_` or a digit, not a `code` span — and the text does not start with the pause's own column name. Domain signals are shown as written (they begin with column names). Another column named like an ordinary word cannot be recognized (errors.md 2026-09-28)
- **Select, then confirm.** The options are native radio buttons in a fieldset (no new UI dependency), shown as full-width option cards (min 44px). Choosing one shows what it does (its consequence, or an imputation's method and assumption); nothing is sent until the user presses "Continue with this choice". A domain "correct" answer opens a text field (trimmed, required, max 200 characters)
- **The impute option names no value.** Its label ("Impute the N missing values with the median") and its method line are written by Python, never the model: the value is computed when cleaning runs, after duplicate removal, and the method line says so — and, when the column has values outside the typical range, that the value includes them. A model-written value was once shown as fact (errors.md 2026-09-28)
- The domain question's wording: "Confirm what this data is" with "Yes, it's {hypothesis}" / "No, it's something else"; when the hypothesis is "unknown": "The Profiler couldn't tell what kind of data this is." with "Continue without a specific domain" / "Tell it the domain". "below the 80 needed to continue without asking" appears only when the score is below 80
- After a successful answer the status line says "Answer recorded — the Cleaner is re-running and may ask about another column (this can take a minute or two)." The next question, if any, replaces the card
- **Visitors** (no `session_id_{analysis_id}` in this browser, including the real owner on another device) see the question read-only: "Only the browser that started this analysis can answer. If that's you, open this link in that browser — the analysis is waiting for this answer." A 403 from /resume switches the owner's view to the same read-only state
- Every model-written string is rendered as plain text; the only markup derived from it is `<code>` for backtick spans. A question the UI cannot render or answer (malformed or missing `pause_data`) shows "This question can't be displayed" and polling continues
- The interaction is inline — no modal, no page navigation

#### Not found

Any unknown address, in both modes (`app/not-found.tsx`; the public build exports it as 404.html): "Page not found", "There is nothing at this address." and a plain link, "Go to the home page". Plain and neutral, with no upload wording. In the public build it also carries the site's header and footer.

#### State 2 — Pipeline Complete

When status is `complete`, the full results are displayed.

**Layout:** Single column with collapsible sections. Executive Summary is always expanded by default. Analyst and Technical layers start collapsed but are easy to expand.

**Results Layout Order:**
1. Analysis header (filename, row count, column count, data quality score). The rows and columns are the cleaned data's (`cleaning_report.summary`'s rows_after and columns_after, used only when its before-counts equal the stored row_count and column_count), with the original file's counts on a second line: "after cleaning · 200 × 9 in the original file", or "after cleaning · same as the original file", and a sentence for screen readers ("After cleaning. The original file had 200 rows and 9 columns."). Without a usable summary the header shows the stored counts, labelled "as in the original file". Counts are formatted in en-US whatever the visitor's locale, so the prerendered page and the browser agree (decisions.md 2026-10-18).
2. Executive Summary (always expanded, most prominent)
3. Chart Grid (below summary, interactive)
4. Full Analyst Report (collapsible section)
5. Technical Detail (collapsible section)
6. Custom Question Input (bottom of page, always visible after completion)

---

## Component Specifications

### FileUpload.tsx

**Behavior:**
- Accepts drag-and-drop and click-to-browse
- Validates file type client-side before showing the preview (CSV and Excel only)
- Shows clear error message for wrong file type: "Please upload a CSV or Excel file (.csv, .xls, .xlsx)"
- Shows clear error message for oversized files: "This file is too large. Maximum size is 100MB."
- File preview shown immediately on selection before the API call
- "Start Analysis" button triggers the POST /api/upload call
- Shows upload progress indicator during the API call
- On success: navigates to /analysis/{id} with session_id stored in localStorage under the key `session_id_{analysis_id}`; the Results page reads it back with the same key

**Props:** None — self-contained component.

**State:** file, preview, isUploading, error

---

### AnalysisProgress.tsx

**Behavior:**
- Polls `/api/analysis/{id}/status` every 3 seconds using setInterval
- Clears the interval when status is `complete` or `error`
- Displays the 4-stage pipeline with animated active stage
- Handles pause states with inline question display (`PauseQuestion`), answering through POST /resume (`resumeAnalysis`, which alone has a 15-second request timeout)
- Handles error states with the ErrorDisplay pattern (see Error Display section)
- A visible `aria-live` status line says what is happening; focus moves to the question heading only when a NEW question appears (never on a poll) and to the status line after an answer is sent
- Stall notice: after 10 minutes in the same non-pause status it says the step is taking longer than usual (the server may have restarted, and this analysis can't continue) with a "Start a new analysis" link; the progress view stays visible and the notice clears as soon as the status changes. Client-side only — the backend has no heartbeat and a reload resets the timer

**Props:** analysisId (string), sessionId (string | null — null for a read-only visitor), onComplete (callback)

**State:** status, currentAgent, progressPct, errorMessage, pauseData, notice, stalled, submitting, submitError

---

### InsightReport.tsx

**Behavior:** Two named exports, no default export — split so `ChartGrid` can sit physically between them in the results layout (header → Executive → Charts → Analyst/Open Questions/Technical). See decisions.md, 2026-09-16.

- `InsightReportExecutive` — Executive Summary cards, always expanded on load.
- `InsightReportDetail` — Analyst Report, Open Questions, and Technical Detail as three collapsible AccordionItems (the Base UI Accordion in components/ui/accordion.tsx), all collapsed by default. A panel opens and closes at once: there is no height animation (the Tailwind v4 classes that would have driven one emitted no CSS and were removed in M2c.1).
- Each section has a header with the layer name and a brief description of who it is for
- **Without JavaScript (public build, M2b.4b):** the accordion keeps its closed panels mounted (Base UI's `hiddenUntilFound`), so the three layers are in the static HTML. Once the page has hydrated, each closed panel is `hidden="until-found"`, which the browser's find-in-page opens; before that it is plain `hidden`, and a `<noscript>` style rule in the analysis page, `[data-slot=accordion-content][hidden]{display:block!important}`, shows the panels when scripting is off (unquoted: React escapes quotes inside `<style>`). Local mode mounts a panel only when it is opened.
- **Reading width (both modes, M2b.4b):** long text keeps to 29rem of text, about 65–75 characters a line on a wide screen: the executive bullets' list (29rem plus the cards' padding, so each card hugs its text), the narrative paragraphs, the open questions' list (plus the 1.5rem indent beside the question mark), the cleaning decisions' list, the methodology and the callouts. The blocks sit on the left of the column; the results header, the chart grid and the correlation matrix keep its full width.

**Executive Summary display:**
- 5 bullets displayed as cards
- Each card: finding (bold) + context (normal) + recommended action (highlighted, perhaps with an arrow icon)
- Clear visual hierarchy within each card
- The finding, context and action wrap anywhere (`overflow-wrap: anywhere`), so a long token such as a chart file name never widens the page at 320 px

**Analyst Layer display:**
- Prose with proper typography — headings, paragraphs, lists
- All correlation findings visually distinguished from causal claims
- Confidence level badges on each finding (High / Moderate / Low / Cannot Determine)
- Chart references linked to the ChartGrid below. A chart file name in the narrative becomes a link to its card, labelled as the card is ("Distribution — revenue"); whole names only, the longest first (`splitChartNames` in `lib/results.ts`, with no regex lookbehind or Unicode property escapes, which Next 14's oldest default browsers lack)
- Every text in the three panels wraps anywhere (`overflow-wrap: anywhere`), so a long token never clips inside a panel

**Technical Layer display:**
- Plain monospace display via the shared `CodeBlock` component for all code blocks (no syntax-highlighting library — CLAUDE.md Rule 3 forbids adding a dependency without a stated necessary reason; see decisions.md 2026-09-16)
- One line under the "Code" heading labels the blocks: "Written by the Explainer agent to illustrate each step. It is not the code that ran." (the blocks are the model's reconstructions, errors.md 2026-10-14). A custom question's code, shown by the same `CodeBlock`, is the code that ran and has no label
- Cleaning decisions shown as a structured list, not prose
- Methodological limitations highlighted in a distinct callout style

**Props — InsightReportExecutive:** `executiveSummary: Record<string, unknown> | null`

**Props — InsightReportDetail:** `insightReport: Record<string, unknown> | null`, `cleaningDecisions: CleaningDecision[] | null`, `chartPaths: string[] | null` (used to cross-reference chart mentions in the Analyst narrative)

---

### ChartGrid.tsx

**Behavior:**
- Displays all generated charts in a responsive grid
- 2 columns on desktop, 1 column on mobile
- Each chart: loaded from `chartUrl(filename)` (lib/api.ts): the backend's `/charts/{filename}` (StaticFiles) in local mode, the site's `/demo/charts/` in the public snapshot
- HTML charts render in `<iframe sandbox="allow-scripts">`, never `allow-same-origin`: they run in an opaque origin, and plotly's "Download plot as a png" button and logo link do nothing (owner ruling D1); charts generated since M2b.2 have neither (decisions.md 2026-10-12). Iframes and images are lazy-loaded and render once the card has mounted
- Hover overlay on each chart showing the chart type and column name
- Click to expand any chart to full width with a close button
- All charts use the project's color scheme — no default matplotlib colors

**Interactive behavior:**
- Plotly charts (line charts, scatter plots) have full hover tooltips with exact values
- Matplotlib/seaborn charts (histograms, box plots, heatmap) displayed as images with zoom capability

**Props:** chartPaths (string[]), analysisId (string)

**Loading state:** Skeleton grid shown while charts load

**As built (M2b.4c; decisions.md 2026-11-13):**
- An image renders at once, so it shows without JavaScript; the card checks it after mounting, so an image that loaded before hydration still clears its loading placeholder. An HTML chart's sandboxed frame renders only once the card has mounted: its load state cannot be read afterwards (M2b.1 Code Review #7).
- In the public build without JavaScript, the analysis page's `<noscript>` rule hides the placeholders, which would pulse forever, and shows the HTML chart's line, "This interactive chart needs JavaScript." The line carries no display class, since one would override its `hidden` attribute; the rule makes it a flex box. The expand button does nothing there, like the accordion triggers (a known limitation).
- A card's title shows the whole label, wrapping on a narrow card; no ellipsis.
- A card is a focus target (`tabIndex={-1}`): a narrative link or a "Referenced charts" pill moves the keyboard focus to it, and a focus-visible ring (the pause UI's ring) shows it.
- Every PNG card has an "Open full size" link under its image: a plain link to the same file, opening in the same tab, where the browser's image view can zoom it on a phone. Its spoken name adds the chart's label in parentheses, "Open full size (<label>)". Never on an HTML chart.

---

### QuestionInput.tsx

**Behavior:**
- Always visible at the bottom of the results page after status is `complete`
- Text input with a send button
- Conversational feel — not a form, a chat-like input
- On submit: POSTs to `/api/analysis/{id}/question` with the session_id header
- Shows loading state while the answer is being computed
- Answer displayed inline below the input, not in a separate section
- Answer display includes:
  - The question (restated)
  - The answer in plain language
  - The pandas code in a syntax-highlighted code block with a copy button
  - Any caveats about data limitations

**Multiple questions:** Each new question and answer pair is added to a scrollable history above the input. No questions are removed — the user can scroll up to see all previous questions and answers.

**Props:** analysisId (string), sessionId (string)

**State:** question, isLoading, questionHistory

**As built (M2b.4c, local mode only; decisions.md 2026-11-13):**
- Under the heading: "Ask about the cleaned data. The Explainer writes pandas code for your question, runs it on the data and describes the result. The code that ran is shown with each answer: check it before relying on the answer." It says what `answer_question` does (backend/agents/explainer.py): a model writes the code, the code runs on the cleaned data, and a model describes the result, so the answer's words are the model's.
- The box takes at most 2,000 characters (`MAX_QUESTION_LENGTH`, one constant). In the owner's view a static hint under it says so, "Questions can be up to 2,000 characters.", tied to the box with `aria-describedby`; a visitor's read-only box keeps its note. The backend has no length check of its own yet (tasks.md, M5).

---

## Error Display Specification

Errors come in two categories. The `error_message` field in the analyses table is always prefixed to indicate which type.

### USER_ERROR

Displayed with yellow/amber warning styling.

**When it appears:** Wrong file type, file too large.

**Display format:**
- Amber border and background tint
- Warning icon
- Actionable message telling the user exactly what to fix
- A "Try Again" button that returns them to the upload page

**Example message:** "Your file could not be processed. Please upload a CSV or Excel file (.csv, .xls, .xlsx) under 100MB."

### SYSTEM_ERROR

Displayed with red error styling.

**When it appears:** Analysis pipeline failed for a technical reason.

**Display format:**
- Red border and background tint
- Error icon
- Message: "Your analysis could not be completed. Our system encountered an error."
- A "Try Again" button that returns them to the upload page
- A "Contact Support" link (placeholder for now)

**What is NOT shown:** The raw error message. The internal error details. Stack traces. The user sees a clean, professional error — not a technical crash dump.

---

## Animation Specification

Framer Motion drives the animated entrances and layout changes: the fade-ins below, the chart grid's layout and the pause UI's reveals. CSS transitions are used only for small color and size changes: hover and focus colors (`transition-colors`, `transition-all`) and the results column's widening (`transition-[max-width]` in app/analysis/[id]/AnalysisPageClient.tsx). `animate-pulse` marks loading placeholders. There are no other CSS keyframe animations.

**Exception: no entry animation in the public build (M2b.4b; decisions.md 2026-11-12).** There the results header, the executive bullets and the chart cards start from their final state (`initial={false}`), so the prerendered page reads without JavaScript; local mode keeps the fade-ins below. The landing page, the header and the footer are static server components with no motion and no CSS transition: hover and focus states change at once.

**Page transitions:** Fade in on route change. Duration 200ms.

**Section reveals:** Slide up + fade in when a collapsible section is expanded. Duration 300ms, ease-out.

**Agent progress transitions:** Each stage animates from waiting -> active -> complete. Active state has a subtle pulse animation on the indicator dot.

**Chart grid load:** Each chart card fades in with a 50ms stagger between cards — the grid appears to populate progressively rather than all at once.

**Question/answer reveal:** Answer fades in from below once received. Duration 250ms.

---

## Mobile Responsiveness

Minimum supported width: 320px.

Every component is tested at 320px before it is considered complete.

**Mobile-specific behavior:**
- Upload zone: full width, reduced height (200px minimum)
- Chart grid: single column on mobile
- Results layout: all sections full width, stacked vertically
- Navigation: no horizontal overflow anywhere
- Text: all body text minimum 14px, headings scale down but remain readable
- Buttons: minimum 44px tap target height on mobile

---

## Polling Behavior

The frontend polls `/api/analysis/{id}/status` every 3 seconds while the pipeline is running.

**When to poll:** Status is not `complete` and not `error`.

**When to stop polling:** Status is `complete` or `error`, OR component unmounts.

**Implementation:** Use setInterval in useEffect. Clear the interval on cleanup. Do not use recursive setTimeout — setInterval is cleaner for fixed-interval polling.

**On each poll response:**
- Update the current agent display in AnalysisProgress
- If status changed to `complete`: clear interval, trigger onComplete callback, render full results
- If status changed to `error`: clear interval, render error display
- If status is a pause state: render the pause question inline

**Out-of-order responses (Build L).** Every status source — the first fetch, the interval, the resume response and each refetch after a failed answer — goes through one `applyStatus(data, seq)` in AnalysisProgress. Each request is numbered when it is sent, and a response older than the last one applied is dropped, so a slow earlier poll can never overwrite a newer status. The resume response keeps its send number (so polls sent after the answer still win) and is not applied at all when a read sent after the answer already shows the next question or a later stage. A question's key is its status plus `column_name`; once answered (a 200, or a refetch after a failure that shows the pause moved on) that key is never shown again. This is safe because the Cleaner never asks the same (pause type, column) twice (F3's repeat guard) and there is at most one domain pause.

**After a failed answer:** the status is refetched. If the pause moved on: "This question was already answered or has changed." If it is the same pause: friendly retry text — for a 400/409, a server error, or a network error/timeout, each worded for its cause (an API detail is never shown). "Sending…" belongs to the question being sent, not to whichever question a poll swaps in. A 403 switches to the read-only view.

---

## Technology Stack

- Next.js 14 App Router
- TypeScript strict mode — no `any` types
- Tailwind CSS for all styling
- components/ui for the base components, from the shadcn scaffold: Accordion, Button and Input on Base UI (`@base-ui/react`), and Label and Textarea as plain elements. The shadcn CLI, its components.json and the unused Card and Badge were removed in M2c.1.
- No chart library: visuals built in React are plain components (the correlation matrix is a native table, decisions.md 2026-09-21); the agent-generated charts are PNG images and sandboxed HTML.
- Framer Motion for animated entrances and layout (see Animation Specification)
- axios for all API calls — configured with base URL and default headers

**TypeScript interfaces** in `frontend/lib/types.ts` must match the pydantic schemas in `backend/models/schemas.py` exactly. Any schema change in the backend requires a corresponding update in the frontend types.

**API functions** in `frontend/lib/api.ts` wrap every API call. Components never call axios directly — they always go through the api.ts functions. This centralizes error handling and makes the session_id header automatic.

---

## End-to-End Tests (Playwright)

The pause-state UI is covered by committed, route-mocked Playwright tests (`frontend/e2e/`, Build L). They need no backend and cost nothing: `playwright.config.ts` starts `next dev` on port 3100 with `NEXT_PUBLIC_API_URL` set to an unreachable address (a process env value takes precedence over `frontend/.env.local`), and `e2e/mockApi.ts` answers every API call with `page.route`; any call it does not handle fails the test. Every test runs at 320px and at 1280px.

- One-time setup (downloads Chromium): `cd frontend && npx playwright install chromium` (`npm install` of `@playwright/test` downloads no browser).
- Run: `npm run test:e2e`. It is separate from `npm run build`, `npm run lint` and pytest, none of which need a browser. Run it and `npm run build` one after the other — both use `.next`.
- `e2e/results.spec.ts` covers the results view: the header with and without a usable cleaning summary, the narrative's chart links, a long chart file name in an executive bullet (no page overflow at 320 px), the Code label (and none on a custom question's answer) and the correlation matrix's column order under a Danish locale. Since M2b.4c each accordion trigger has an explicit id, so the panels keep their names under `next dev` too and these tests find a panel by its name; a test pins it (errors.md 2026-10-18).
- `e2e/local-mode.spec.ts` checks that local mode keeps what the public build changed in M2b.4b: no header, footer or skip link, the results header's fade-in and closed panels that are not in the page until opened; and that it has the same reading width (decisions.md 2026-11-12).
- Mock data: `e2e/fixtures/captured_*.json` are real stored pause questions (the `pause_data` payloads only, from the F2 and F3/F3b live validations); `synthetic_*.json` are hand-written variants (a medical outlier, a 2-option missing-value pause, null statistics, malformed payloads).
- Screenshots for a build report: set `E2E_SCREENSHOT_DIR` (e.g. to the gitignored `.playwright-mcp/<build>/`); test output (`test-results/`, `playwright-report/`) is gitignored.
- `npm run lint` covers `app`, `components`, `lib`, `e2e`, `e2e-public` and `e2e-snapshot`.
- `e2e/question.spec.ts` checks local mode's question box (M2b.4c): its copy, its 2,000-character limit, the owner's hint tied to the box, and a visitor's read-only note without a hint.
- The public snapshot build has its own suite: `npm run test:e2e:public` (`playwright.public.config.ts`, specs in `e2e-public/`). Its web server runs `npm run build:public` from the synthetic fixture `e2e/fixtures/snapshot/` (the only place that sets `SNAPSHOT_ALLOW_FIXTURE=1`) and serves `out/` the way Vercel serves a static export. At 320 and 1280 px it asserts that every request stays on the site's origin and none goes to `/api`, that no upload, question or progress UI renders, the exact header (the counts, the second line and what a screen reader reads), the exact chart attributes, the sandboxed chart's opaque origin, the 404s, no horizontal overflow and the "About this example" note (its exact text, its place between the h1 and the results header, and, with JavaScript off, an effective opacity of 1: the product of its own and every ancestor's, since `toBeVisible()` counts opacity 0 as visible); one project checks the exported files, the third-party notice among them. Since M2b.4b it also checks the landing page (its exact copy in order, its two links to the example, no "upload" and no "you"), the header, footer and skip link on "/", the analysis page and the 404 (`chrome.spec.ts`: landmarks, links, the inline mark, 44 px tap targets, 14 px text, the skip link by keyboard, into `<main>` itself), and the pages without JavaScript (`nojs.spec.ts`: no entry animation's start in the served HTML, the three layers shown by the `<noscript>` rule, every text displayed at full opacity, skipping visually hidden text and the chart cards' loading placeholders until M2b.4c), and the reading width's mechanism on its seven blocks. Since M2b.4c it runs under frontend/vercel.json's headers, which serve-static.mjs applies (`headers.spec.ts`: exactly one header set on every response, no Content Security Policy violation in the page or a chart frame, a control that proves the listener reports one, and the 308 for a trailing slash), and it checks the chart cards: an image that loads before hydration still clears its placeholder, the full-size link, the hidden no-JavaScript line, the keyboard focus from a "Referenced charts" pill, and without JavaScript the image drawn, no pulse and the line.
- The committed snapshot has a suite too: `npm run test:e2e:snapshot` (`playwright.snapshot.config.ts`, specs in `e2e-snapshot/`, port 3201). It builds `frontend/snapshot/` with `SNAPSHOT_DIR` and `SNAPSHOT_ALLOW_FIXTURE` set empty and checks the exported files byte for byte against it, that the hidden charts and the dropped keys appear nowhere in `out/`, the manifest with its note, the third-party notice (byte for byte, with the version and copyright lines read from the bundle's own header), the real scatter in its sandbox, that every request stays on the site's origin, and, at 320 and 1280 px, the note on the page (as in the public suite), the header, no raw chart file name outside the code blocks, nothing clipped sideways (no element whose overflow-x is hidden or clip has content wider than its box, apart from horizontal scroll containers and visually hidden text; the rule's own controls run on synthetic boxes), the Code label, the page under en-US, fa-IR and ar-SA (no hydration error, Latin digits, each closed panel `hidden="until-found"`) and that the three layers render from the real data (DoD item 14, on the narrative as rendered, with its chart links). Since M2b.4b it also checks the real landing page, whose sentences about the example are pinned to the snapshot's JSON and whose three thresholds are pinned to the backend's constants (`landing.spec.ts`), the header and footer, the page without JavaScript, and the reading width in characters per laid-out line (`nojs.spec.ts`: the named texts' median lines within 62–76 at 1280 px, no line over 85; at 320 px the note keeps its 13 lines). Since M2b.4c it runs under vercel.json's headers too (`headers.spec.ts`: the same checks, and the scatter's 185 points in its frame and opened directly), checks every card's whole title, the full-size links on the 13 PNG cards, the keyboard focus from each of the narrative's 10 chart links (`layers.spec.ts`), and without JavaScript every image drawn, no pulse and the scatter's line; its locale runs wait for the scatter's frame, a real hydration signal.
- The site's identity has a metadata spec in each suite. `e2e-public/metadata.spec.ts` and `e2e-snapshot/metadata.spec.ts` check each page's title, description and canonical link, the link preview (the same card, with its alt text, on "/" and on the analysis page), the icons, the viewport and the dark color scheme, and the 404's noindex and missing canonical link; the public suite also checks the theme color and the types the icons, the card, `robots.txt` and `sitemap.xml` are served with. `e2e/metadata.spec.ts` checks local mode's titles and the h1 of "/", that "/" has no canonical link, and that its `robots.txt` disallows everything and its `sitemap.xml` lists nothing while `playwright.config.ts` sets both site settings to invalid values. Both build-output specs check `out/robots.txt` and `out/sitemap.xml` exactly, the icons and the card byte for byte with their pixel sizes, and that no exported file contains `localhost:3000` or the old name; since M2b.4b also that no file under `out/_next/static` holds either site setting's value (client code never imports lib/site.ts) while `index.html` holds both. The expected texts are literals in `e2e-public/site.ts`, never read from the app.
- `npm run test:unit` runs the snapshot rules', the mode flag's, the site settings' (`lib/site-settings.mjs`), the results view helpers' (`lib/results.ts`), vercel.json's (`lib/vercel-config.test.mjs`) and the export script's unit tests (Node's built-in runner), and `npm run test:builds` builds five broken snapshots, each of which must fail with its own message.
