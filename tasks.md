# Tasks

## Status Legend
- [ ] Not started
- [~] In progress
- [x] Complete

---

## Completed

- [x] CLAUDE.md — restructured into lean spine + 9 deep docs
- [x] .claudeignore — created
- [x] docs/intelligence-philosophy.md
- [x] docs/architecture.md
- [x] docs/agents/profiler.md
- [x] docs/agents/cleaner.md
- [x] docs/agents/analyzer.md
- [x] docs/agents/explainer.md
- [x] docs/infrastructure.md
- [x] docs/ui-and-frontend.md
- [x] docs/plugins-and-mcps.md
- [x] backend/config.py
- [x] backend/utils/supabase_client.py
- [x] backend/utils/langsmith_client.py
- [x] backend/models/schemas.py — all 26 pydantic models
- [x] Supabase tables and indexes
- [x] backend/utils/file_handler.py
- [x] backend/main.py — FastAPI app, all endpoints
- [x] backend/prompts/profiler_system.md
- [x] backend/prompts/cleaner_system.md
- [x] backend/prompts/analyzer_system.md
- [x] backend/prompts/explainer_system.md
- [x] backend/agents/profiler.py
- [x] backend/agents/cleaner.py
- [x] backend/agents/analyzer.py
- [x] backend/agents/explainer.py
- [x] tests/test_cleaner.py

---

## Backlog

### Backend — Core Infrastructure

- [x] Update main.py — wire question endpoint to explainer.py + add POST /api/analysis/{id}/resume endpoint for pause state responses
- [x] GET /api/analysis/{id}/question/{question_id} — question polling endpoint (main.py) + 2 unit tests (test_api.py, Group 5)
- [x] Fix empty-file upload handling (Build D, Phase 1) — validate_file (backend/utils/file_handler.py) now rejects 0-byte and zero-data-row CSV/XLSX uploads with a USER_ERROR 400 before any DB record, temp file, or LLM call. Fail-open for files pandas cannot read; an empty Excel peek is confirmed with a full read (blank-second-row layouts); main.py runs validation via asyncio.to_thread. 17 new tests (14 in test_file_handler.py, 3 in test_api.py); full suite 128 passed / 16 skipped. Completed 2026-09-18. Deferred issues found along the way are logged in errors.md 2026-09-18.
- [ ] Fix .xls uploads — xlrd is not installed or in requirements.txt, so every .xls upload fails in the Profiler as SYSTEM_ERROR although the UI and validate_file accept .xls (add xlrd with a stated reason, or stop advertising .xls); pre-existing, found during Build D; see errors.md 2026-09-18
- [ ] Handle corrupted and non-UTF-8 files at upload (Definition of Done item 4) — Build D's fail-open check passes them through and the Profiler fails them as SYSTEM_ERROR; see errors.md 2026-09-18
- [ ] Handle files whose only data row is entirely empty (e.g. `a,b\n,\n`) — passes Build D's check as 1 all-missing row; narrow edge case; see errors.md 2026-09-18

### Backend — Prompts

(complete)

### Backend — Tools

- [x] backend/tools/__init__.py
- [x] backend/tools/viz_tools.py
- [x] backend/tools/code_executor.py

### Backend — Agents

- [x] backend/agents/explainer.py
- [x] backend/agents/orchestrator.py
- [x] Fix Profiler/Cleaner row-sampling bug — build_profiler_message (and build_cleaner_message's sample_values) under-sample via head(5)/head(3), causing wrong full-dataset statistics when the uploaded file is sorted/grouped by a categorical column. Implemented and unit-tested 2026-09-17 (compute_column_stats + `computed_column_stats` message key, sample_values fix in both agents, profiler_system.md Step 3, plus the overwrite guarantee — apply_computed_column_stats replaces the LLM's copied column stats with Python's values before the profile_report save, closing Code Review follow-up (1); full suite 111 passed / 16 skipped). Live-validated on iris.csv 2026-09-18 (analysis_id 1a96db4a-3c88-460d-a39a-820b619536a4) and committed in 976200b.
- [x] Fix Cleaner TypeError on bool-dtype (True/False) columns — Build A, Phase 1, 2026-09-19. `and not is_bool_dtype(...)` added inline to cleaner.py's three numeric filters (IQR block, detect_interactions, OUTLIER FLAG). Tested (test_cleaner.py Groups 6-7, including the first mocked cleaner_node test); full suite 139 passed / 16 skipped; all 5 edits mutation-checked; Code Review: no findings. Committed in 4961e9f. See errors.md 2026-09-17 and decisions.md 2026-09-19.
- [x] Fix bool columns taking the random-sample branch of sample_values in build_profiler_message and build_cleaner_message — Build A, Phase 1, 2026-09-19, shipped with the line above. Bool columns now take the distinct-values branch in both agents (test_profiler.py Group 9, test_cleaner.py Group 6). Committed in 4961e9f.
- [x] Fix analyzer.py's "id"-substring numeric-column exclusion (Build B, Phase 1, 2026-09-19) — classify_columns dropped any numeric column whose name merely contained "id" (width, valid, paid_amount, humidity…; 2 of 4 iris measurements). Now uses the private helper `_is_id_column` (standalone "id" name component only). 37 new test items plus 1 flipped (test_analyzer.py); full suite 176 passed / 16 skipped; all 5 deliberate breaks caught. Live validation deliberately deferred (optional; not a blocker). Committed in 4b980d3. See errors.md 2026-05-15 and decisions.md 2026-09-19.
- [ ] Pass numeric_columns into generate_correlation_heatmap (viz_tools.py) so a genuine numeric ID column the Cleaner failed to convert no longer appears in the heatmap; found during Build B; see errors.md 2026-09-19
- [ ] Handle Excel True/False columns with blank cells, which load as float64 1.0/NaN/0.0 and are treated as continuous numeric (misleading random sample, IQR/mean stats); found during Build A; see errors.md 2026-09-19
- [x] Fix build_profiler_message TypeError on Excel files whose header row contains dates — Build C, Phase 1, 2026-09-20. Both upload loaders (profiler.load_dataframe, cleaner.load_dataframe_from_uploads) now normalize column labels with `df.columns = df.columns.map(str)` after the read. Fixed three more problems from the same cause: the identical independent crash in build_cleaner_message; integer headers silently making execute_cleaning_operations skip every cleaning decision; and cross-agent name agreement (map(str) matches parquet, astype(str) does not). 16 new tests (test_profiler.py Group 10, test_cleaner.py Groups 8-9, test_analyzer.py Group 11); full suite 192 passed / 16 skipped; all 5 deliberate breaks caught. The evaluation's separate claim that these headers also crash the Analyzer did not reproduce — see errors.md 2026-09-20 and decisions.md 2026-09-20.
- [ ] Fix Excel header cells that are themselves a literal boolean (TRUE/FALSE as a boolean value, not text) — json.dumps renders the bool key as "true" while the loaders' str() renders it "True", so execute_cleaning_operations skips every decision for that column while the cleaning_report claims it was applied; the crash class is fixed, this is the residual correctness gap; found during Build C; see errors.md 2026-09-20
- [ ] Classify user-fixable errors in agent nodes instead of prefixing every exception SYSTEM_ERROR (profiler.py:313, cleaner.py:621, analyzer.py:818, explainer.py:209, orchestrator.py:255) — pre-existing; needs a per-node audit of exception types; see errors.md 2026-09-18. docs/infrastructure.md:61 describes the intended behavior, not the current one.
- [ ] Handle the Cleaner reducing a valid file to 0 rows — the Analyzer runs on the empty frame and compute_data_quality_score (analyzer.py:396) reports 1.0; pre-existing; see errors.md 2026-09-18
- [ ] Fix cleaner.py:61 missingness guard — `missing_pct == 0` is False for the NaN a 0-row frame produces, so every column gets a fabricated "random" label; pre-existing, unreachable from uploads since Build D; see errors.md 2026-09-18

### Frontend

- [x] Next.js app scaffold (App Router, TypeScript, Tailwind, shadcn/ui, Framer Motion, axios, recharts, lucide-react, lib/types.ts, lib/api.ts, dark layout)
- [x] Upload page — file input, drag-and-drop, validation
- [x] Results page — Progress UI (polling, pipeline visualization, error states, complete placeholder). Pause UI deferred to follow-up build.
- [x] Results page — full results display. Completion handoff wired (AnalysisProgress onComplete → page.tsx swaps AnalysisProgress↔AnalysisResults via AnimatePresence). Built CodeBlock, AnalysisResults (header + three-layer output), InsightReport (InsightReportExecutive cards + InsightReportDetail collapsible Analyst/Open Questions/Technical accordion), ChartGrid (agent-generated PNG/HTML charts), QuestionInput (custom-question polling via new GET endpoint). Backend GET question-polling endpoint + tests. Build + lint clean, 95 backend tests pass.
- [x] Charts — interactive correlation matrix in the Analyst layer (Phase 2, 2026-09-21). Built as a native table of fixed 44×44 button cells instead of Recharts (redirect and reasoning in decisions.md 2026-09-21). Reads `analysis_report.correlation_matrix`, highlights backend `strong_pairs` with color plus outline, and supports hover/keyboard detail on desktop and tap-to-pin on touch. Verified at 320px on 1a96db4a and 7e0797c9 (first accordion open) and on a synthetic 12×12 matrix; zero hex; tsc, ESLint and build clean; backend 201 passed / 16 skipped. Code Review: 2 findings, both fixed and re-verified. Screenshots in .playwright-mcp/corrMatrix/. Not committed yet, pending review. `recharts` remains installed but unused (separate decision).
- [ ] Apply the Build E chart-title fix to generate_line_chart (viz_tools.py:149) — same long-title clipping the scatter plot had, left untreated because it is untested and was out of Build E scope; found during Build E; see errors.md 2026-09-21
- [ ] Raise AnalysisProgress.tsx's 3 remaining text-xs sites (:227, :296, :354) to text-sm as part of the pause-state UI build — known accepted 12px/14px inconsistency; see errors.md 2026-09-21
- [ ] Fix FileUpload.tsx's errorRef being nulled by the exiting AnimatePresence banner (missed scroll-into-view on a repeat same-type error) — use a callback ref or a stable wrapper; found by code review during Build E; see errors.md 2026-09-21
- [ ] Guard main.py:147 against a None `file.filename` (currently a 500, should be the USER_ERROR 400) — pass `file.filename or ""`; pre-existing, found by code review during Build E; see errors.md 2026-09-21
- [ ] Gate FileUpload.tsx's "approx. N columns" preview to .csv only — it counts commas in binary for .xlsx; pre-existing, found by code review during Build E; see errors.md 2026-09-21
- [x] Mobile viewport testing (320px minimum) — Build E, 2026-09-21. Verified in a real 320px viewport: page overflow measured 0 on the upload page, the results page, and the expanded Technical Detail layer; 21 sites raised from 12px to 14px with no new text wrapping; chart-reference pills measured exactly 44.00px; desktop (1440px) regression-checked. Screenshots in .playwright-mcp/buildE/. AnalysisProgress.tsx's 3 remaining text-xs sites are a known accepted exception — see errors.md 2026-09-21.
- [ ] Pause-state UI follow-up (backend pause_data persistence + pause question components) — still deferred per 2026-05-18

- [x] Mobile typography + upload error UX (Build E, Phase 1, 2026-09-21) — text-xs→text-sm at 21 sites across 5 components (ui/badge.tsx and ui/button.tsx primitives untouched); chart-reference pills to `max-sm:min-h-11` (replacing `max-sm:py-2.5`), measured at exactly 44.00px; `classifyUploadError()` + banner-owned "Try Again" whose action branches on `error.type` (reset for user errors, re-invoke `handleUpload` for api errors, added after code review) + `scrollIntoView({block:"nearest"})`; wrong-type and oversized messages aligned to the docs spec wording in both FileUpload.tsx and file_handler.py; `_short_name(name, limit=26)` and the scatter-plot title recipe in viz_tools.py. 9 new tests (tests/test_viz_tools.py), 2 backend string assertions updated; full suite 201 passed / 16 skipped; all 6 deliberate breaks caught. Also fixed a reachability defect found during the build: a wrong-type rejection never renders the file preview, so its reset control was previously unreachable. See decisions.md 2026-09-21 (x3) and errors.md 2026-09-21.

- [ ] **⚠ NEEDS ITS OWN EVALUATION ROUND — shared/reloaded analysis links are unrecoverable.** `session_id` lives only in the uploading browser's localStorage, so an /analysis/{id} link opened on another device, in a private window, or after clearing site data can never load its results, with no recovery path in the UI. Deliberately excluded from Build E. The fix is a product decision (bearer token in the URL vs per-browser only vs real auth), not a code change — evaluate the tradeoff before writing anything. See errors.md 2026-09-21.
- [x] Show upload USER_ERROR rejections as user errors in FileUpload — Build E, 2026-09-21. `classifyUploadError()` strips the `USER_ERROR:`/`SYSTEM_ERROR:` prefix and picks amber (user) vs red (api) styling, with a generic fallback for unprefixed failures (e.g. axios "Network Error"). Live-verified at 320px against a real backend 400 (header-only CSV) and with the backend stopped. See decisions.md 2026-09-21.

### Tests

- [x] tests/fixtures/iris.csv
- [x] tests/fixtures/messy_data.csv
- [x] tests/fixtures/time_series_data.csv
- [x] tests/test_code_executor.py
- [x] tests/test_profiler.py
- [x] tests/test_cleaner.py
- [x] tests/test_analyzer.py
- [x] tests/test_explainer.py
- [x] tests/test_api.py

### Infrastructure

- [ ] Supabase RLS policies
- [x] Supabase Storage bucket — cleaned-datasets bucket created as private bucket
- [ ] Vercel deployment
