# Tasks

## Status Legend
- [ ] Not started
- [~] In progress
- [x] Complete

---

## Roadmap (M1–M4)

Added 2026-10-05. The goal is a read-only public demo; the owner must never be billed because a stranger uses the system. Interactive mode comes later. Decisions: decisions.md 2026-10-05.

### M1 — Reproducible (2026-10-05)

- [x] Baseline migration for the pre-migration schema and the `cleaned-datasets` bucket (`supabase/migrations/20260413000000_baseline_analyses_questions_bucket.sql`), proved on a fresh project: every catalog comparison identical to live; the live migration history is untouched (decisions.md 2026-10-05).
- [x] Reproducible dependencies: requirements.txt is a full lock of the tested venv (98 packages; the 18 direct ones in its header); requirements-dev.txt adds the test tools; `.python-version` 3.11, `.nvmrc` 24, `engines` node 24.x; `openai`, `langchain` and `OPENAI_API_KEY` removed (decisions.md 2026-10-05).
- [x] LangSmith optional at boot, Rule 8 enforced in code: with tracing off the server is read-only and POST `/api/upload`, `/question` and `/resume` refuse with 503 (`backend/utils/agent_guard.py`); backend/config.py normalizes the tracing switches (decisions.md 2026-10-05).
- [x] Start commands and env examples: docs/infrastructure.md "Run Locally"; the backend refuses to start outside the repository root; `.env.example` updated; new `frontend/.env.example`.
- [x] The test suite runs offline and isolated: 794 passed / 16 skipped; 0 network attempts; no writes under backend/outputs or backend/uploads.
- [x] Six obsolete analyses and one question deleted from the live project after a verified private backup; 77faa166-668b-4001-92e0-94e037de7e3b kept (decisions.md 2026-10-05).
- [x] Logs and docs: the 2026-10-03 audit's unlogged findings in errors.md (security findings in public-safe wording), corrections to superseded decisions, docs/infrastructure.md schema, storage and environment sections, CLAUDE.md Rule 8.

### M2 — Demo hardening

- [ ] UX copy for the 503 read-only refusal (upload, custom question, pause answer).
- [ ] Refuse before the request body is read, with a request-size limit (FastAPI 0.111 parses the body before any dependency runs; decisions.md 2026-10-05).
- [ ] `DEMO_MODE` that refuses agent work by default, independent of tracing.
- [ ] Close the Rule 8 gap: trace custom-question runs (answer_question attaches no tracer; errors.md 2026-10-05).
- [ ] Second refusal layer: run_pipeline and answer_question refuse when tracing is off (or DEMO_MODE is on), not only the routes (M1 code review).
- [ ] Fix `get_session`'s NULL-session check before any seeding (errors.md 2026-10-05).
- [ ] Results header Rows / Columns describe the upload, not the cleaned data (errors.md 2026-10-03; the Frontend line below).
- [ ] The scatter plot's clipped title (errors.md 2026-09-28; the Backend — Tools line below).
- [ ] Pin the Supabase MCP server's version and make its configuration read-only by default.
- [ ] npm audit reports pre-existing findings (seen during M1's npm ci); triage in M2's security scans.

### M3 — Deploy

- [ ] A base image with glibc 2.28 or later (pyarrow 23.0.1 ships only manylinux_2_28 wheels; decisions.md 2026-10-05).
- [ ] Anchor the paths that are relative to the working directory (backend/uploads, the /charts mount, backend/prompts), so the backend no longer has to start from the repository root.
- [ ] Chart serving for the deployed demo (charts live on the server's local disk today).
- [ ] The free plan pauses an idle project; decide how the demo survives that.
- [ ] A separate demo database whose seeded row has a non-NULL, never-published session_id.
- [ ] The Linux install check of the lock on the target image.
- [ ] Before any public URL: the security findings in errors.md 2026-10-05 and the Security Review plugin (Rule 14).
- [ ] Remaining doc drift: docs/architecture.md:78 (session_id is checked only on POST question and resume since 2026-09-21) and :80 (CORS allows every origin, not the frontend's); the docs/infrastructure.md folder tree; tasks.md:87 ("all 26 pydantic models"); errors.md:146 (MAX_FILE_SIZE lives in backend/utils/file_handler.py, not backend/config.py).

### M4 — README

- [ ] A README for the repository (frontend/README.md is the create-next-app boilerplate).

### Tech debt found in M1

- [ ] Per-agent tracers are created and never used: profiler.py:392, cleaner.py:2118, analyzer.py:940, explainer.py:79 and :232. The pipeline is traced through the orchestrator's tracer; the explainer.py:232 one means custom-question runs are not traced at all (errors.md 2026-10-05).
- [ ] `.live/l_live.py:91` `EXPECTED_COUNTS` is 6/1/6 (analyses, questions, Storage objects) but live is now 1/0/1, so the gitignored harness refuses to start until it is updated.
- [ ] The Appendix A items logged without a milestone: errors.md 2026-10-05 ("Status of the 2026-10-03 system audit's Appendix A"), items 8, 9, 10, 12, 13, 14, 16, 17, 18 and 19.
- [ ] The `tracing_on` test fixture (tests/conftest.py) patches `create_tracer` in a fixed list of modules, so a new module that imports it would get a real tracer in tracing-on tests; patch it once at its source instead (maintenance; M1 code review).
- [ ] Nothing configures logging in the backend, so every backend info line (including "LangSmith tracing is on.") never shows; only warnings reach stderr (pre-existing; M1 code review).
- [ ] `LANGCHAIN_ENDPOINT` is hard-coded in backend/utils/langsmith_client.py and set at import, overriding any value from the environment (Rule 1; pre-existing; M1 code review).

---

## Next Build

- [x] **HIGH PRIORITY — Execute the Cleaner's own (model-authored) decisions by structured operation id instead of keyword matching** — Build G, 2026-09-26, committed in 042e798. Every Cleaner decision names an operation from a closed set (convert_type, standardize_values, fill_missing, leave_missing, flag_outliers, note) that Python validates without raising and runs in a fixed order (system duplicate removal, conversions, standardizations, fills, the user's pause choices, flags); Python writes every record from what ran and logs `cleaning_report.operations`; the keyword router is removed (approved, after the pure-move proof: 30 captured F3 inputs + 4,000 random cases, 0 mismatches); the filter keeps a note, a flag where the user answered only the missing-value pause, and a fill or leave_missing where the user answered only the outlier pause (the last approved after Code Review); max_tokens 16000 with a stop_reason check; S6 (the Profiler's semantically_categorical_columns and Python's duplicate count sent, the Profiler's pattern fields not); profiler_concerns_addressed "not assessed". 525 passed / 16 skipped; 66 of 66 mutations caught; Code Review: 9 findings (5 fixed, 2 resolved, 2 declined and logged), second pass 2 more, fixed; the approved filter change's scoped review 1 more, fixed. Live-validated 2026-09-26: R1 22 of 22 checks (LangSmith cb1e4375-73b3-43f4-b96b-876a5747bbe1; $0.1417). See decisions.md 2026-09-26 (Build G) and errors.md 2026-09-25 / 2026-09-26.

**Status update (2026-10-05):** the Build G item above is done. M1 is complete; the next build is M2 (Demo hardening) — see Roadmap (M1–M4) above.

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
- [x] Supabase tables and indexes — Status update (2026-10-05, M1): now reproducible from the repository. The baseline migration `supabase/migrations/20260413000000_baseline_analyses_questions_bucket.sql` creates both tables, their indexes, RLS, the client-role revokes and the `cleaned-datasets` bucket; proved on a fresh project (decisions.md 2026-10-05).
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
- [ ] Guard main.py:147 against a None `file.filename` (currently a 500, should be the USER_ERROR 400) — pass `file.filename or ""`; pre-existing, found by code review during Build E; see errors.md 2026-09-21
- [x] Pause-state backend half — pause_data persistence (2026-09-22, committed in d5e495b). First migration file `supabase/migrations/20260922035037_add_pause_data_to_analyses.sql` (committed ba2f089, then applied via Supabase MCP, confirmed by introspection). Both pause-wait nodes write `pause_data` in the same update as the pause status; GET /status returns it only in pause statuses; GET /api/analysis/{id} never carries it; POST /resume validates the answer against the stored question (`_validate_pause_response`) and clears `pause_data` in the same update, which applies only if that exact pause (status + `updated_at`) is still active, else 409. Code Review found 3 bugs in the first implementation (stranding on a malformed stored question, a KeyError 500, a resume racing a newer pause), and a final scoped review found a 4th (the escape hatch also skipped `column_name`); all fixed in this build (errors.md 2026-09-22). 54 new tests + 1 updated (`test_resume_valid_domain_pause`); full suite 282 passed / 16 skipped; mutation check: the original 7 breaks all caught, plus 7 of 8 for the fixes (the survivor is an equivalent, unreachable mutant). No live validation (deferred to the consumption-fix pass). See decisions.md 2026-09-22 (x4) and errors.md 2026-09-22.
- [x] Shared/reloaded analysis links now open for anyone with the URL (2026-09-21). The four read-only GET routes (`/analysis/{id}`, `/status`, `/question/{qid}`, `/charts`) use the new `get_public_read_access` dependency; POST `/question` and POST `/resume` still use the unchanged `get_session`. Malformed ids return 404 instead of 500, and the frontend shows an "Analysis not found" card instead of spinning. Visitors (no local session_id, including the real owner on another device) see the full results and live progress read-only; QuestionInput renders disabled with an explanation. Backend 228 passed / 16 skipped (7 tests updated, 27 new, incl. a structural route-dependency test); `/status` returns only the error category (USER_ERROR / SYSTEM_ERROR), never the stored detail; Playwright verified visitor complete/errored/running/paused/nonexistent/malformed and owner regression at 320px and 1280px. See decisions.md 2026-09-21 and errors.md 2026-09-21.
- [x] Survive transient Supabase disconnects — Build L.2, 2026-09-28. One injected HTTP/1.1 client shared by the database and Storage clients (a dropped connection now fails one request, not every in-flight one), and `supabase_call` (backend/utils/supabase_retry.py) around every Supabase call: transient transport errors only, 3 attempts; "did it land?" checks for the inserts, /resume's conditional update and the pause write (the previous pause's answer never counts); the pause poll survives 120 s of consecutive failures; Storage uploads upsert; a structural test enforces the wrapper. 758 passed / 16 skipped; 17 of 17 mutations caught; e2e 76; Code Review: 10 findings, 2 fixed, 8 declined; $0 dry runs D1 37/37, D2 49/49, D3 (injected faults) 53/54 — the one failure a pre-existing filename overflow, fixed separately. See decisions.md and errors.md 2026-09-28 (Build L.2)
- [ ] Retry gateway errors (502/503/504, 520–524) that arrive as postgrest `APIError` / `StorageApiError` — at least for reads such as the pause poll, the most exposed site; its own decision; see errors.md 2026-09-28 ("Gateway errors … arrive as postgrest APIError…")
- [ ] Replace the pause's inferred identity (status, column, pause type) with a per-pause id written into `pause_data`, echoed by /resume and required on the stored answer — makes every landed check and the stale-tab check exact; backend + frontend contract; found by Code Review in Build L.2; see errors.md 2026-09-28 ("Every 'did it land?' check…")
- [ ] A failed error write can still strand a run during a longer outage (retried since Build L.2, not solved) — covered by the stranded-run detection item (Frontend section); see errors.md 2026-09-28 ("A failed error write can still strand a run")

### Backend — Prompts

All four agent prompts exist (see Completed). Open prompt-quality work is tracked where the code lives: the Cleaner's structured operation ids (Next Build), and in Backend — Agents the Analyzer's 30-pair confidence floor, Profiler output validation, the two F2 Tier B Profiler findings, and the Analyzer's missing `cleaner.*` inputs.

### Backend — Tools

- [x] backend/tools/__init__.py
- [x] backend/tools/viz_tools.py
- [x] backend/tools/code_executor.py
- [ ] Fix the scatter plot's two-line title, which loses its first line ("x vs") in the card and expanded views — the Build E recipe itself; fix it before copying it to generate_line_chart (next line); see errors.md 2026-09-28 ("The scatter plot's two-line title…")
- [ ] Decide a floor for drawing the highest-correlation scatter (it is drawn even at r = 0.08 on messy_data.csv); with the Analyzer's owner; see errors.md 2026-09-28 ("The scatter is drawn for the highest-correlation pair…")
- [ ] Apply the Build E chart-title fix to generate_line_chart (viz_tools.py:149) — same long-title clipping the scatter plot had, left untreated because it is untested and was out of Build E scope; found during Build E; see errors.md 2026-09-21

### Backend — Agents

- [x] **Build J: the Analyzer's self-evaluation loop** — 2026-09-27, committed 96e01a7. The evaluation's replay found two checker artifacts ((a) looked for a dict repr, (c) for the substring "anomal"), so every run made 3 calls and the stored reports told the Explainer that concerns were "not addressed". `check_self_evaluation` is now structural: (a) by Python-assigned concern_ids, (b) every Python strong pair has a complete Step 4 entry (thresholds only from the prompt), (e) unchanged; (c) removed (logged); (d) recorded, not retried. The loop keeps the first passing response, else the fewest failed criteria (earliest on a tie); a retry that cannot be used ranks worst and keeps the earlier response. Python writes `self_evaluation_loops` and `unmet_criteria`; `self_evaluation_gaps` is dropped. analyzer_system.md Sections 10 and 13, docs/agents/analyzer.md. 627 passed / 16 skipped; 25 of 25 mutations caught; Code Review: two passes (8 + 9 fixed, 1 + 1 declined). Live-validated 2026-09-27: 9 of 9 checks, **1 call, $0.1307** (LangSmith 08747438-942b-4d1d-9f44-ef8b358ed748; Build I: 3 calls, $0.383). See decisions.md 2026-09-27 (Build J) and errors.md 2026-09-27.
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
- [x] REQUIRED BEFORE the frontend pause-state UI (done by Builds F1, F2 and F3, 2026-09-25): fix pause-answer consumption and the option drift — (1) the Profiler ignores a domain-pause answer, (2) the Cleaner sees only the latest answer, so pauses on more than one column likely loop (messy_data.csv), (3) missing-value pauses offer 3 options vs. cleaner.md's required 4. All are LLM-facing prompt work needing one dedicated live-validated pass; see the three errors.md 2026-09-22 entries.
- [x] Build F1: consume the domain-pause answer — code, prompt and 30 tests (13 of 13 mutations caught). FULLY live-validated 2026-09-25 by F2's Tier B: the real confirm and correct resumes both settled the domain, re-derived provenance, recorded `domain_resolution` and never re-paused (LangSmith c989e8ac-f641-49bd-8fe4-e296143bcd7c, a68d2847-54a6-4825-82f3-9652830c28c8). See decisions.md 2026-09-22 (Build F1).
- [x] Build F2: enforce the <80 domain-confidence gate in Python — code, the Section 10 "only" fix and 24 tests (336 passed / 16 skipped; 10 of 10 mutations caught; Code Review: 1 issue, fixed). FULLY live-validated: Tier A (the backstop converted a sub-80 full report into a pause) and Tier B 2026-09-25 (both real resumes, at 22 and 71, were never re-gated; $0.2009). Two non-blocking intelligence-quality findings from the Tier B output are logged in errors.md 2026-09-25. See decisions.md 2026-09-22 (Build F2).
- [x] Build F3: the Cleaner consumes pause answers across multiple pauses — answers accumulate in state, a repeat pause raises, Python checks every pause before it is shown, executes each user choice by option id (report == what ran, attributed to the user), backstops a skipped >30% missing-value pause, and adds an honest 4th option (`preserve_missingness`); cleaner:74 and both "unknown" premises fixed. Built and tested (391 passed / 16 skipped; 25 of 25 mutations caught; two Code Review passes). FULLY live-validated 2026-09-25: the F3 run on messy_data.csv ($0.4109) proved accumulation, the repeat guard, execution by option id and the missing-value backstop; F3b's resume ($0.2329) proved the outlier path. See decisions.md 2026-09-25 (Build F3, Build F3b).
- [x] Build F3b: outlier-pause backstop by model-written routing (`outlier_review`, Python-enforced) plus a system outlier record per column — 428 passed / 16 skipped; 24 of 24 mutations caught; Code Review: 10 findings, 5 fixed, 1 corrected, 4 declined; second pass clean. Live-validated 2026-09-25 (C3 115f25d2-9ac0-4b7b-a237-81323c7e3161, C4 a3140726-428c-4070-b6ce-719021ca0994; $0.2329; 18 of 18 checks; the backstop produced the revenue pause). See decisions.md 2026-09-25 (Build F3b).
- [ ] Make columns after the 50th visible to the Cleaner (no routing, record or backstop for them today); see errors.md 2026-09-25
- [ ] Derive compute_data_quality_score's outlier penalty from structured facts instead of decision-text keywords; see errors.md 2026-09-25 — now possible from `cleaning_report.operations` (Build G); analyzer.py, needs sign-off
- [x] Compute `duplicate_row_count` in Python and overwrite the Profiler's copy (it reported 0 against 15 on messy_data.csv) — Build H, 2026-09-27, committed 5726ae1. `profiler_node` counts exact duplicates over the full uploaded frame (the Cleaner's definition, by the same expression — an import would be circular), sends the count in the message and overwrites the model's copy after `apply_computed_column_stats`, before `apply_domain_resolution` and the save (first run and resume); profiler_system.md Step 4 says copy it verbatim. 536 passed / 16 skipped; 9 of 9 mutations caught; Code Review: 9 findings (3 fixed, 1 resolved, 5 declined), second pass clean. Live-validated 2026-09-27: 4 of 4 checks (LangSmith d9370b8b-1805-48b8-b595-e55e1cdfbd52; $0.1061). No backfill. Two follow-ups logged (errors.md 2026-09-27). See decisions.md 2026-09-27 (Build H) and errors.md 2026-09-25.
- [ ] Compute or drop the Profiler's model-written `profile_report.data_quality_score` (never checked in Python; the Analyzer's separate score is the one shown); see errors.md 2026-09-27
- [ ] Decide what compute_data_quality_score's `df.duplicated()` deduction should mean now that Build G removes every uploaded duplicate (it can fire only on duplicates created by cleaning); analyzer.py, needs sign-off; see errors.md 2026-09-27
- [ ] Compute the Profiler's other structural fields in Python (co_emptiness_patterns, co_completeness_patterns, default_value_frequencies, potential_merge_artifacts) and overwrite or validate its copies — they are whole-table claims from a sample; since Build G the Cleaner does not receive them (it uses its own missingness_patterns and interactions_detected instead); see errors.md 2026-09-26 ("The Cleaner's model never received the Profiler's structural fields")
- [ ] Assess profiler_concerns_addressed for real (Build G replaced the always-false text match with "not assessed"): carry the model's acknowledgments with system-checked references to the decisions they cite; see errors.md 2026-09-26
- [ ] Decide how dates stored as text become datetime for the Analyzer's time-series detection (Analyzer parses, or the Cleaner is required to convert); see errors.md 2026-09-26
- [x] Enforce the Analyzer's 30-pair correlation floor in Python — Build I, 2026-09-27, committed b9d60d0. The evaluation first confirmed that n = 15 was the true count (iris.csv is a 15-row stub), so the defect was the label, and the prompt invited it (lines 195/201/434/185). `compute_correlation_matrix` adds each strong pair's complete-pair `n` (finite and non-missing on both columns, the rows `corr()` uses), which the message sends. `apply_correlation_floor` runs after the final parse and before the single save: it overwrites matched entries' r and n with Python's, lowers them to Cannot Determine below 30 (or when r is undefined) with a `floor_override` record, moves entries for pairs outside the matrix to `correlation.unverified_correlations`, and lowers the parent label when every strong pair has n < 30. The analyzer_system.md contradictions are removed. New fixture tests/fixtures/sparse_pairs.csv. 571 passed / 16 skipped; 18 of 18 mutations caught; Code Review: two passes (pass 1: 10 findings, 4 fixed; pass 2: 9 findings, 5 fixed; the rest declined with reasons). Live-validated 2026-09-27: 11 of 11 checks (LangSmith 7aa4a3f8-8f8c-4e92-bf08-e99047227246; $0.383). The Explainer self-check was deferred (below). No backfill. See decisions.md 2026-09-27 (Build I) and errors.md 2026-09-21 / 2026-09-27.
- [ ] Keep the model's distribution and time-series confidence labels (analyzer.py overwrites both keys wholesale with Python's dicts) and enforce the 50-value and two-cycle floors in Python; fix the analyzer_system.md line-436 anti-pattern (bans only High below 50) with it; needs sign-off; see errors.md 2026-09-27 ("…distribution and time-series confidence labels are discarded…")
- [ ] Fix explainer.py:104-105's Memory-read log (reads top-level `strong_correlations`/`anomalies_found`, which do not exist; log-only); see errors.md 2026-09-27
- [ ] Show each strong pair's complete-pair n in the interactive correlation matrix and mark pairs below the 30-pair floor (frontend; `strong_pairs[].n` exists since Build I); see errors.md 2026-09-27
- [ ] Explainer pass: treat `floor_override.reason` as authoritative over the Analyzer's prose and `unverified_correlations` as "not a finding" (a self-check of numeric claims against the stated floors, deferred from Build I); live-validated; see errors.md 2026-09-27 (the Explainer self-check and unverified_correlations entries)
- [x] Make self-evaluation criterion (b) structural — every `correlation_matrix.strong_pairs` pair must have a `strong_correlations` entry with the same names (a pair the model omits is not enforceable today); with Build J; see errors.md 2026-09-27 — DONE in Build J (2026-09-27, committed 96e01a7)
- [ ] Add a structured `anomalies_found` field to the Analyzer's output and check it structurally (criterion (c) is not enforced since Build J; explainer.py:105 already reads that key); needs sign-off and an Explainer live check; see errors.md 2026-09-27 ("Anomaly explanations are not enforced…")
- [ ] Let an Analyzer retry see its previous response (or its failed parts) instead of regenerating the whole analysis; weigh the extra input tokens; see errors.md 2026-09-27 ("An Analyzer retry regenerates…")
- [ ] Measure the Analyzer on a wide file with many strong pairs (criterion (b) retries, max_tokens) and decide whether to cap the pairs that need a full investigation; see errors.md 2026-09-27 ("Wide files with many strong pairs…")
- [x] Include the Explainer in the next end-to-end live run to check its Technical layer against Build J's Python-written `unmet_criteria` / `self_evaluation_loops`; see errors.md 2026-09-27 ("The Explainer's Technical layer changes…") — judged passed by the user 2026-10-03, run 77faa166; one interpretive overreach logged
- [ ] Remove the remaining in-model-loop wording from analyzer_system.md outside Sections 10 and 13 (lines 13, 216, 353, 460: "limit of three iterations", "`loop_count` is below 3", "The self-evaluation loop … now runs", "the loop has converged"); prompt-only cleanup left out of Build J's approved scope; see decisions.md 2026-09-27 (Build J)
- [ ] Validate the Profiler's output after parsing (exact provenance labels, exactly three top-3 items, required fields; raise, repair or warn per field) and update or delete the stale pydantic `ProfileReport`; see errors.md 2026-09-22 ("The Profiler's output is never validated")
- [ ] Add a `stop_reason == "max_tokens"` check to profiler_node so a truncated response fails as a clear SYSTEM_ERROR, not an opaque JSON error (wide files are a realistic risk); see errors.md 2026-09-22
- [x] Handle domain-pause options whose ids are not "confirm"/"correct" — Build L Phase A, 2026-09-28, committed in 486767b. Not by mapping or rejecting at /resume (rejecting would leave such a pause unanswerable): `profiler_node` decides `model_paused` before the gate and rebuilds a model-emitted pause through the gate's template (`rebuild_model_domain_pause`: exactly confirm/correct, hypothesis verbatim, score kept, non-blank string signals); no hypothesis or no usable score raises before the pause is shown. The gate's synthesized pause is byte-identical (golden test against the live Tier A pause). 671 passed / 16 skipped; 10 of 10 mutations caught; Code Review: 10 findings, 2 fixed, 1 resolved in Phase B (decisions.md), 6 declined (approved design), 1 logged. See errors.md 2026-09-22 and decisions.md 2026-09-28 (Build L)
- [ ] Next Profiler prompt pass — two F2 Tier B intelligence findings: the resume confidence score jumped 22 → 71 on "correct" with no new evidence, and domain-derived meanings for anonymized columns are stated as fact instead of labeled as assumptions; see errors.md 2026-09-25 (both entries)
- [ ] Pass the `cleaner.*` inheritance keys (excluded_columns, outliers_handled, user_decisions_incorporated) to the Analyzer's LLM, or correct analyzer_system.md, which says it reads them; needs sign-off; see errors.md 2026-09-25
- [ ] Compute Cleaner pause counts (and the missingness backstop's threshold check) on the frame after duplicate removal and earlier answers, not the raw upload; see errors.md 2026-09-25 ("Counts in a Cleaner pause describe the raw upload"). With it, decide whether the impute option should show its exact value, computed on that same frame (Build L follow-up chose no value until then; decisions.md 2026-09-28), and whether the numbers in the model's pause prose can be checked or labeled (errors.md 2026-09-25, update 2026-09-28)
- [ ] Merge the Analyzer's four closing saves (analysis_report, chart_paths, data_quality_score, updated_at) into one atomic update, as the Explainer does — they can land partially; each is retried since Build L.2; see errors.md 2026-09-28 ("The Analyzer saves its result in four separate updates…") and decisions.md 2026-05-06
- [ ] Make detect_interactions' inline IQR-bound computation call `_iqr_bounds` / `_iqr_outlier_mask` (the last remaining copy; the OUTLIER FLAG copy went with the keyword router in Build G) — behavior-preserving cleanup with a pure-move check; see errors.md 2026-09-25 ("The IQR outlier bounds are computed in four places")
- [ ] Cut the cost of skipped mandatory Cleaner pauses — each one the model skips is a full report the backstops discard (2 of the Cleaner's 4 calls, $0.2791 of $0.5036, in run 77faa166); low priority, cost only; see errors.md 2026-10-03 ("A skipped mandatory Cleaner pause costs a full extra Cleaner call…")

### Frontend

- [x] Next.js app scaffold (App Router, TypeScript, Tailwind, shadcn/ui, Framer Motion, axios, recharts, lucide-react, lib/types.ts, lib/api.ts, dark layout)
- [x] Upload page — file input, drag-and-drop, validation
- [x] Results page — Progress UI (polling, pipeline visualization, error states, complete placeholder). Pause UI deferred to follow-up build.
- [x] Results page — full results display. Completion handoff wired (AnalysisProgress onComplete → page.tsx swaps AnalysisProgress↔AnalysisResults via AnimatePresence). Built CodeBlock, AnalysisResults (header + three-layer output), InsightReport (InsightReportExecutive cards + InsightReportDetail collapsible Analyst/Open Questions/Technical accordion), ChartGrid (agent-generated PNG/HTML charts), QuestionInput (custom-question polling via new GET endpoint). Backend GET question-polling endpoint + tests. Build + lint clean, 95 backend tests pass.
- [x] Charts — interactive correlation matrix in the Analyst layer (Phase 2, 2026-09-21). Built as a native table of fixed 44×44 button cells instead of Recharts (redirect and reasoning in decisions.md 2026-09-21). Reads `analysis_report.correlation_matrix`, highlights backend `strong_pairs` with color plus outline, and supports hover/keyboard detail on desktop and tap-to-pin on touch. Verified at 320px on 1a96db4a and 7e0797c9 (first accordion open) and on a synthetic 12×12 matrix; zero hex; tsc, ESLint and build clean; backend 201 passed / 16 skipped. Code Review: 2 findings, both fixed and re-verified. Screenshots in .playwright-mcp/corrMatrix/. Committed in 1eadb8c. `recharts` remains installed but unused (separate decision).
- [x] Fix Tailwind v3 color-token mapping (2026-09-21) — `tailwind.config.ts` now maps all 34 color tokens from globals.css through a `cssVarColor()` color-mix helper, so opacity modifiers work, and sets `darkMode: "selector"`. Before the fix, 32 of the 34 produced zero CSS. No component or globals.css changes; v4 upgrade rejected (decisions.md 2026-09-21). Verified by before/after computed-style probes and screenshots at 320px/1280px (upload page, 1a96db4a and 7e0797c9, collapsed and expanded); CorrelationMatrix fills identical; tsc, ESLint and build clean; backend 201 passed / 16 skipped; Code Review no findings. Screenshots in .playwright-mcp/tw-shots/. See errors.md 2026-09-21 (closure plus the new DM Sans / dead v4-imports entry).
- [x] Wire DM Sans into Tailwind (2026-09-22, committed in 9d71407) — `tailwind.config.ts` maps `fontFamily.sans` to `var(--font-sans)` plus v3's default stack as the generic fallback; `font-sans`, the `html` rule and Preflight now resolve to DM Sans (body text), completing decisions.md 2026-05-16. Instrument Serif needed no change (already applied by inline `var(--font-display)`). Verified by computed styles before/after on the upload page and 1a96db4a at 320px/1280px, collapsed and expanded (serif and mono byte-identical, overflow 0); tsc, ESLint and build clean; backend 282/16 unchanged. See decisions.md 2026-09-22 and errors.md 2026-09-21 (status update) / 2026-09-22 (chart font — open question).
- [x] Raise AnalysisProgress.tsx's 3 remaining text-xs sites to text-sm — Build L, 2026-09-28. The sites had drifted to :237/:311/:369 (not the logged :227/:296/:354); :237 was the pause placeholder, replaced by the pause question. See errors.md 2026-09-21
- [ ] Fix FileUpload.tsx's errorRef being nulled by the exiting AnimatePresence banner (missed scroll-into-view on a repeat same-type error) — use a callback ref or a stable wrapper; found by code review during Build E; see errors.md 2026-09-21
- [ ] Gate FileUpload.tsx's "approx. N columns" preview to .csv only — it counts commas in binary for .xlsx; pre-existing, found by code review during Build E; see errors.md 2026-09-21
- [x] Mobile viewport testing (320px minimum) — Build E, 2026-09-21. Verified in a real 320px viewport: page overflow measured 0 on the upload page, the results page, and the expanded Technical Detail layer; 21 sites raised from 12px to 14px with no new text wrapping; chart-reference pills measured exactly 44.00px; desktop (1440px) regression-checked. Screenshots in .playwright-mcp/buildE/. AnalysisProgress.tsx's 3 remaining text-xs sites are a known accepted exception — see errors.md 2026-09-21.
- [x] Pause-state UI — frontend half (Build L, 2026-09-28): `PauseQuestion.tsx` inline in AnalysisProgress (select-then-confirm with native radios; domain / missing-value / outlier renderers; an unrenderable fallback; visitors read-only), `lib/pause.ts` (narrowing, keys, resume body), one `applyStatus(data, seq)` for every status source, the 15-second timeout on /resume only, the stall notice, committed route-mocked Playwright e2e tests (`npm run test:e2e`, 33 tests × 320/1280 px = 66 passed; 10 of 10 frontend mutations caught) and the $0 harness dry run through the real server (23 of 23 checks). Complete only after the one paid live run on messy_data.csv (separate prompt). See decisions.md 2026-09-28 (Build L). Follow-up (2026-09-28): the impute option names no value, Python writes its label and method (2d2d8e8); the model's reasoning sits behind a collapsed disclosure above the options, with guarded display-only capitalization; e2e 74 passed; see decisions.md 2026-09-28 (Build L follow-up). The paid run should confirm that no stored impute label or method carries a number the model wrote. Live-validated 2026-10-03 on messy_data.csv, analysis 77faa166-668b-4001-92e0-94e037de7e3b (LangSmith 59c2f81f-16fb-4a3f-9bc8-a7fc4da1b2b9; HARD 35/35, REPORT 4/4, J1 and J2; $1.1282): three pauses (revenue impute, notes preserve_missingness, revenue flag_as_suspected_error), each /resume 200; 7.N passed: no stored impute label or method carries a number. See decisions.md 2026-09-28 (Build L, live validation update)
- [ ] Detect runs stranded by a server restart (startup reconciliation to SYSTEM_ERROR, or a heartbeat exposed on /status) — the UI's only signal today is a client-side 10-minute notice; needs sign-off; see errors.md 2026-09-28 ("A run stranded by a server restart…")
- [ ] Live-validate the domain pause's real-server path (domain_pause_wait_node's DB write, a real /resume on a domain pause, the pickup) with ambiguous_domain.csv when the next paid run allows; see errors.md 2026-09-28 ("The domain pause's real-server path…")
- [ ] Stop status polls piling up against a hung backend (skip a tick while one is in flight; a long GET timeout); found by Code Review in Build L; see errors.md 2026-09-28 ("Status polls can pile up…")
- [ ] Consider ordering pause-UI responses by a server stamp (`updated_at` on /status) instead of client sequence numbers; backend change; see errors.md 2026-09-28 ("Response ordering in the pause UI…")
- [ ] Trim cleaner_system.md:406 so the model no longer writes the impute method's value (Python writes the label and `method` since 2d2d8e8); needs a live check; see errors.md 2026-09-28 ("cleaner_system.md:406 still asks…")
- [ ] Reject (or replace with the median) mode imputation on a numeric column with no repeated value — it fills the column minimum; see errors.md 2026-09-28 ("Mode imputation is accepted on a numeric column…")
- [ ] Let the pause UI's display capitalization recognize every column name (needs the dataset's column names on the pause, or capitalized model sentences); low priority; see errors.md 2026-09-28 ("The pause UI's display capitalization…")
- [ ] Trim profiler_system.md Section 8 so the model no longer writes the domain pause's options (Python always rebuilds them since Build L); needs a live check; see errors.md 2026-09-28 ("The Profiler prompt still asks…")
- [ ] Remove globals.css's two dead Tailwind v4-only `@import`s (shadcn/tailwind.css, tw-animate-css) and fix the v4-only variants in components/ui that emit nothing (`data-open:`/`data-closed:`, `animate-in`, `no-scrollbar`, `aria-invalid:`, …), plus the unused self-referencing `.theme` block and `font-heading`; the body-font part is done (9d71407); see errors.md 2026-09-21 ("globals.css imports two Tailwind v4-only files")
- [ ] Keep the "100MB" upload-limit copy in sync with the size constants (FileUpload.tsx, file_handler.py:33, docs/ui-and-frontend.md:121) — a shared source of truth, or a per-side test asserting the message matches its own constant; low priority; see errors.md 2026-09-21
- [ ] Make the results header's Rows / Columns describe the cleaned data, or label them as the upload's (they come from the upload: 200 / 9 against 185 × 10 on 77faa166); its own decision, backend and frontend; see errors.md 2026-10-03 ("The results header's Rows / Columns come from the upload…")

- [x] Mobile typography + upload error UX (Build E, Phase 1, 2026-09-21) — text-xs→text-sm at 21 sites across 5 components (ui/badge.tsx and ui/button.tsx primitives untouched); chart-reference pills to `max-sm:min-h-11` (replacing `max-sm:py-2.5`), measured at exactly 44.00px; `classifyUploadError()` + banner-owned "Try Again" whose action branches on `error.type` (reset for user errors, re-invoke `handleUpload` for api errors, added after code review) + `scrollIntoView({block:"nearest"})`; wrong-type and oversized messages aligned to the docs spec wording in both FileUpload.tsx and file_handler.py; `_short_name(name, limit=26)` and the scatter-plot title recipe in viz_tools.py. 9 new tests (tests/test_viz_tools.py), 2 backend string assertions updated; full suite 201 passed / 16 skipped; all 6 deliberate breaks caught. Also fixed a reachability defect found during the build: a wrong-type rejection never renders the file preview, so its reset control was previously unreachable. See decisions.md 2026-09-21 (x3) and errors.md 2026-09-21.

- [ ] Dynamic Open Graph / social-preview metadata for /analysis/{id} links (title, filename-free summary, maybe a chart thumbnail) — separate from the shared-link fix, which it now depends on: `generateMetadata` in a server component can read the public GET /api/analysis/{id}. Needs a small server wrapper because page.tsx is `"use client"`.
- [x] Show upload USER_ERROR rejections as user errors in FileUpload — Build E, 2026-09-21. `classifyUploadError()` strips the `USER_ERROR:`/`SYSTEM_ERROR:` prefix and picks amber (user) vs red (api) styling, with a generic fallback for unprefixed failures (e.g. axios "Network Error"). Live-verified at 320px against a real backend 400 (header-only CSV) and with the backend stopped. See decisions.md 2026-09-21.

- [x] Wrap long uploaded filenames at 320 px — 2026-09-28, found by Build L.2's D3 dry run (check 8c: a 37-character name overflowed the results page by 29 px). The results header's filename span wraps anywhere (`min-w-0 [overflow-wrap:anywhere]`); the upload preview already truncates by design. e2e/filename.spec.ts (60-character name, both widths); e2e 80 passed; 2 of 2 mutations caught. See errors.md 2026-09-28 ("A long uploaded filename overflows…")

### Tests

- [x] tests/fixtures/iris.csv
- [x] tests/fixtures/messy_data.csv
- [x] tests/fixtures/time_series_data.csv
- [x] tests/fixtures/ambiguous_domain.csv
- [x] tests/test_code_executor.py
- [x] tests/test_profiler.py
- [x] tests/test_cleaner.py
- [x] tests/test_analyzer.py
- [x] tests/test_explainer.py
- [x] tests/test_api.py
- [x] tests/test_orchestrator.py
- [x] tests/test_file_handler.py
- [x] tests/test_viz_tools.py

### Infrastructure

- [x] Supabase RLS policies — Build K, 2026-09-28, committed in 9bcff18 (migration applied as remote version 20260927184255). RLS on `analyses` and `questions` with zero policies; all `anon`/`authenticated` privileges revoked (incl. TRUNCATE; closes the GraphQL exposure); `postgres`'s default privileges in `public` no longer grant new tables or sequences to them; `SUPABASE_PUBLISHABLE_KEY` no longer required. Backend unchanged (secret key = `service_role`, BYPASSRLS). 633 passed / 16 skipped; 16 of 16 mutations caught; Code Review: 1 finding, fixed. Verified live at $0: anon 401/42501 on every verb, backend GETs 200, service-key write cycle clean, advisors show only the accepted INFO 0008. See decisions.md 2026-09-28 (Build K) and errors.md 2026-09-21 / 2026-09-28.
- [x] Supabase Storage bucket — cleaned-datasets bucket created as private bucket
- [ ] Vercel deployment
