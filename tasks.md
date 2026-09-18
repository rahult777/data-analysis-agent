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
- [ ] Fix Cleaner TypeError on bool-dtype (True/False) columns — pre-existing; see errors.md 2026-09-17
- [ ] Fix bool columns taking the random-sample branch of sample_values in build_profiler_message and build_cleaner_message — Code Review follow-up (2) on the row-sampling fix (errors.md 2026-09-17 row-sampling entry); a heavily imbalanced True/False column can still show a homogeneous sample. Separate bug from the Cleaner TypeError line above.
- [ ] Fix build_profiler_message TypeError on Excel files whose header row contains dates — pd.read_excel keeps date header cells as datetime.datetime column labels and json.dumps rejects non-string dict keys, so the upload fails at the Profiler as SYSTEM_ERROR (before its LLM call, no API cost); pre-existing; planned for Build C; see errors.md 2026-09-17
- [ ] Classify user-fixable errors in agent nodes instead of prefixing every exception SYSTEM_ERROR (profiler.py:313, cleaner.py:621, analyzer.py:818, explainer.py:209, orchestrator.py:255) — pre-existing; needs a per-node audit of exception types; see errors.md 2026-09-18. docs/infrastructure.md:61 describes the intended behavior, not the current one.
- [ ] Handle the Cleaner reducing a valid file to 0 rows — the Analyzer runs on the empty frame and compute_data_quality_score (analyzer.py:396) reports 1.0; pre-existing; see errors.md 2026-09-18
- [ ] Fix cleaner.py:61 missingness guard — `missing_pct == 0` is False for the NaN a 0-row frame produces, so every column gets a fabricated "random" label; pre-existing, unreachable from uploads since Build D; see errors.md 2026-09-18

### Frontend

- [x] Next.js app scaffold (App Router, TypeScript, Tailwind, shadcn/ui, Framer Motion, axios, recharts, lucide-react, lib/types.ts, lib/api.ts, dark layout)
- [x] Upload page — file input, drag-and-drop, validation
- [x] Results page — Progress UI (polling, pipeline visualization, error states, complete placeholder). Pause UI deferred to follow-up build.
- [x] Results page — full results display. Completion handoff wired (AnalysisProgress onComplete → page.tsx swaps AnalysisProgress↔AnalysisResults via AnimatePresence). Built CodeBlock, AnalysisResults (header + three-layer output), InsightReport (InsightReportExecutive cards + InsightReportDetail collapsible Analyst/Open Questions/Technical accordion), ChartGrid (agent-generated PNG/HTML charts), QuestionInput (custom-question polling via new GET endpoint). Backend GET question-polling endpoint + tests. Build + lint clean, 95 backend tests pass.
- [ ] Charts — Recharts integration for React-native visualizations (separate from the agent-generated ChartGrid shipped above)
- [ ] Mobile viewport testing (320px minimum) — components built mobile-first (44px tap targets, single-column stacking, 14px min text) but not yet verified in a 320px browser viewport
- [ ] Pause-state UI follow-up (backend pause_data persistence + pause question components) — still deferred per 2026-05-18
- [ ] Show upload USER_ERROR rejections as user errors in FileUpload — the backend detail currently appears, `USER_ERROR:` prefix included, in the red "api" error box; header-only files are the first backend 400 a UI user can hit (since Build D); see errors.md 2026-09-18

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
