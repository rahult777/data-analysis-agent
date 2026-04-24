# UI and Frontend Specification

This document contains the complete UI design rules, component specifications, and frontend behavior for the Data Analysis Agent system. Load this doc when building, modifying, or designing any frontend component, page, or user-facing interaction. Do not build or modify any UI without reading this document in full first.

---

## Core Design Principles

**Dark mode is the default.** There is no light mode toggle. The system is built for dark mode from the ground up. Every color, shadow, and contrast decision assumes a dark background.

**Zero generic AI aesthetic.** This system must not look like every other AI tool. No gradient blobs. No floating orbs. No "futuristic" typography gimmicks. Clean, precise, data-focused design. The aesthetic should communicate professionalism and trust — the same feeling a senior analyst's polished report gives.

**Every UI component is built using the Frontend Design plugin.** No component is built without it. Generic AI-generated UI is not acceptable for a system at this level.

**Production quality on every component.** Every component is tested at 320px minimum width. Every component has smooth transitions via Framer Motion. Every interactive element has appropriate hover and focus states.

**Color system:** Use shadcn/ui tokens exclusively. Never raw hex values in components. This ensures consistency and makes future theme changes easy.

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
When the pipeline enters a pause state (domain confirmation or missing value decisions), the AnalysisProgress component transitions to a question display:
- Clear visual distinction from the normal progress view
- Shows the specific question with context
- Shows the available options as prominent buttons
- User selects an option and the pipeline resumes
- The interaction is inline — no modal, no page navigation

#### State 2 — Pipeline Complete

When status is `complete`, the full results are displayed.

**Layout:** Single column with collapsible sections. Executive Summary is always expanded by default. Analyst and Technical layers start collapsed but are easy to expand.

**Results Layout Order:**
1. Analysis header (filename, row count, column count, data quality score)
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
- On success: navigates to /analysis/{id} with session_id stored in component state

**Props:** None — self-contained component.

**State:** file, preview, isUploading, error

---

### AnalysisProgress.tsx

**Behavior:**
- Polls `/api/analysis/{id}/status` every 3 seconds using setInterval
- Clears the interval when status is `complete` or `error`
- Displays the 4-stage pipeline with animated active stage
- Handles pause states with inline question display
- Handles error states with the ErrorDisplay pattern (see Error Display section)

**Props:** analysisId (string), sessionId (string), onComplete (callback)

**State:** status, currentAgent, progressPct, errorMessage, pauseData

---

### InsightReport.tsx

**Behavior:**
- Displays all three output layers
- Executive Summary always expanded on load
- Analyst Report and Technical Detail in collapsible AccordionItems (shadcn/ui Accordion)
- Expand/collapse transitions via Framer Motion
- Each section has a header with the layer name and a brief description of who it is for

**Executive Summary display:**
- 5 bullets displayed as cards
- Each card: finding (bold) + context (normal) + recommended action (highlighted, perhaps with an arrow icon)
- Clear visual hierarchy within each card

**Analyst Layer display:**
- Prose with proper typography — headings, paragraphs, lists
- All correlation findings visually distinguished from causal claims
- Confidence level badges on each finding (High / Moderate / Low / Cannot Determine)
- Chart references linked to the ChartGrid below

**Technical Layer display:**
- Monospace font for all code blocks
- Syntax highlighting for pandas code
- Cleaning decisions shown as a structured list, not prose
- Methodological limitations highlighted in a distinct callout style

**Props:** executiveSummary, insightReport, chartPaths, analysisId, sessionId

---

### ChartGrid.tsx

**Behavior:**
- Displays all generated charts in a responsive grid
- 2 columns on desktop, 1 column on mobile
- Each chart: image loaded from `/charts/{filename}` via the StaticFiles endpoint
- Hover overlay on each chart showing the chart type and column name
- Click to expand any chart to full width with a close button
- All charts use the project's color scheme — no default matplotlib colors

**Interactive behavior:**
- Plotly charts (line charts, scatter plots) have full hover tooltips with exact values
- Matplotlib/seaborn charts (histograms, box plots, heatmap) displayed as images with zoom capability

**Props:** chartPaths (string[]), analysisId (string)

**Loading state:** Skeleton grid shown while charts load

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

All animations use Framer Motion. No CSS transitions or keyframe animations — everything goes through Framer Motion for consistency.

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

---

## Technology Stack

- Next.js 14 App Router
- TypeScript strict mode — no `any` types
- Tailwind CSS for all styling
- shadcn/ui for all base components (Button, Card, Accordion, Badge, Input, etc.)
- Recharts for any data visualizations built in React (not the agent-generated charts)
- Framer Motion for all animations
- axios for all API calls — configured with base URL and default headers

**TypeScript interfaces** in `frontend/lib/types.ts` must match the pydantic schemas in `backend/models/schemas.py` exactly. Any schema change in the backend requires a corresponding update in the frontend types.

**API functions** in `frontend/lib/api.ts` wrap every API call. Components never call axios directly — they always go through the api.ts functions. This centralizes error handling and makes the session_id header automatic.
