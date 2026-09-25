# Infrastructure — LangGraph Flow, API Endpoints, Supabase Schema, Folder Structure

This document contains the complete infrastructure specification for the Data Analysis Agent system. Load this doc when building or modifying the FastAPI backend, LangGraph orchestrator, API endpoints, database schema, or folder structure. Do not build or modify infrastructure without reading this document in full first.

---

## LangGraph Orchestration Flow — All 23 Steps

The pipeline is defined in `backend/agents/orchestrator.py`. This file contains the LangGraph graph definition only — no business logic. Business logic lives in the individual agent files.

The complete pipeline executes as follows:

**Step 1:** User uploads file via the frontend drag-and-drop zone with an optional context field (what they want to understand) and optional user type selection (Business Owner, Data Analyst, Data Scientist).

**Step 2:** Backend validates file format. CSV and Excel only (`.csv`, `.xls`, `.xlsx`). If the format is invalid, return immediately with `USER_ERROR: Unsupported file type. Please upload a CSV or Excel file.` Do not create a database record for invalid files. **Known gap:** `.xls` passes this check but currently fails later in the Profiler, because xlrd is not installed (errors.md, 2026-09-18).

**Step 3:** Backend validates file size, then content. All checks live in `validate_file` (`backend/utils/file_handler.py`), which the upload endpoint runs in a worker thread via `asyncio.to_thread`, because reading a large Excel workbook can take seconds. Maximum size is 100MB; if exceeded, return immediately with `USER_ERROR: File too large. Maximum supported file size is 100MB.` The size check runs before the file is parsed. A 0-byte file returns `USER_ERROR: This file is empty. Please upload a file with data.` A file with no data rows (header only, blank lines only, or an empty workbook) returns `USER_ERROR: This file has no data rows. Please upload a file with at least one row of data.` The data-row check reads only the first data row (`nrows=1`) with the same pandas defaults the Profiler uses (first sheet, first row as header). For Excel, an empty result is confirmed with a full read before rejecting: the `nrows=1` read drops a blank second row, so without the full read a valid workbook laid out as title row, blank row, table would be rejected. In the data-row check, only an empty result or pandas' `EmptyDataError` rejects the file; any other read failure (bad encoding, corrupted file, `.xls` without xlrd) is logged and the file continues unchanged to the Profiler, which reports it as `SYSTEM_ERROR` (decisions.md, 2026-09-18). Do not create a database record for any rejected file.

**Step 4:** Generate a UUID session_id. Create an analyses record in Supabase with status `profiling`, storing: session_id, original_filename, stored_filename (UUID-based to prevent conflicts), file_size, created_at, updated_at.

**Step 5:** Return UploadResponse to the frontend containing analysis_id and session_id. The frontend stores session_id in localStorage (`session_id_{analysis_id}`) on the uploading browser; it is sent only on the state-changing requests (POST question, POST resume).

**Step 6:** The LangGraph pipeline starts asynchronously. The frontend begins polling `/api/analysis/{id}/status` every 3 seconds.

**Step 7:** Comprehender (profiler.py) runs. It reads data provenance signals, forms a domain hypothesis with a confidence score, examines every column completely, examines dataset structure, produces a capability assessment, and flags the top 3 concerns and top 3 interesting patterns.

**Step 8:** Save ProfileReport to `analyses.profile_report`. Update `analyses.row_count` and `analyses.column_count`. Update `analyses.updated_at`.

**Step 9:** Evaluate domain confidence score from ProfileReport.
- If below 80%: enter PAUSE state. Present the domain hypothesis and its supporting signals to the user. Offer two options: confirm the hypothesis or provide the correct domain. Wait for user response. Update ProfileReport with the confirmed domain before proceeding.
- If 80% or above: proceed directly to Step 10.

**Step 10:** Update `analyses.status` to `cleaning`.

**Step 11:** Check if any column has over 30% missing values OR if any domain-sensitive outlier decision is needed (medical data with extreme values, financial data with potential fraud signals). If yes: enter PAUSE state, one question per run. Present the specific decisions needed to the user with the options available for each. Wait for user responses. If no: proceed directly to Step 12. The Cleaner's LLM asks the question, but Python checks it before it is stored or shown (cleaner.py `validate_cleaner_pause`): the exact option ids, an executable imputation method, counts recomputed by Python, a fourth missing-value option (`preserve_missingness`) written by Python, and a loud error rather than a loop if an answered (pause type, column) pair is asked again. If the LLM returns a full report while a column is still over 30% missing and unanswered, Python turns it into that column's pause (`apply_missingness_backstop`); outlier pauses have no such backstop. Every answer accumulates in pipeline state (`answered_cleaner_pauses`) and is sent to each later Cleaner run.

**Step 12:** Thoughtful Cleaner (cleaner.py) executes with all user inputs incorporated. Python, not the LLM, executes each user choice by its option id (`apply_user_decisions`) and writes that decision, attributed to the user; the LLM's own decisions on what the user decided are dropped. It makes every cleaning decision in the context of the confirmed domain. It writes every decision in plain English before executing. After executing, it re-profiles to verify.

**Step 13:** Save CleaningReport to `analyses.cleaning_report`. Save the decisions list separately to `analyses.cleaning_decisions`. Update `analyses.updated_at`.

**Step 14:** Serialize the cleaned DataFrame to parquet format. Upload to Supabase Storage bucket `cleaned-datasets` with key `{analysis_id}.parquet`. Verify the upload succeeded by reading back the file size.

**Step 15:** After successful upload verification, delete the original uploaded file from temporary local storage. If deletion fails, log the error to `errors.md` but do not fail the pipeline. The parquet file in Supabase Storage is now the authoritative cleaned dataset.

**Step 16:** Update `analyses.status` to `analyzing`.

**Step 17:** Deep Investigator (analyzer.py) runs on the cleaned data. It runs all mandatory analysis, investigates every concern flagged by the Profiler, investigates all correlations above 0.7, explains every anomaly, generates all required charts. The self-evaluation loop runs with maximum 3 iterations against the 5-point checklist.

**Step 18:** Save AnalysisReport to `analyses.analysis_report`. Save chart paths to `analyses.chart_paths`. Update `analyses.data_quality_score`. Update `analyses.updated_at`.

**Step 19:** Update `analyses.status` to `explaining`.

**Step 20:** Translator and Advisor (explainer.py) runs with the full context of all previous agents. It leads with the single most practically important finding. It produces output at all three layers simultaneously — Executive (5 bullets), Analyst (full narrative), Technical (complete methodology).

**Step 21:** Save ExecutiveSummary to `analyses.executive_summary`. Save FullInsightReport to `analyses.insight_report`. Update `analyses.status` to `complete`. Update `analyses.updated_at`.

**Step 22:** Frontend receives `complete` status on the next poll. It stops polling and renders the full results at all three layers.

**Step 23 (Custom Questions — runs on demand after Step 21):** User types a question in the QuestionInput component. Frontend POSTs to `/api/analysis/{id}/question` with the session_id header. Backend validates session_id. Backend creates a question record in the questions table with status `pending`. Explainer downloads `{analysis_id}.parquet` from Supabase Storage. Explainer translates question to a pandas operation. Executes on real cleaned data. Saves answer and pandas_code to the question record. Updates question status to `complete`. Returns QuestionResponse to the frontend. Frontend displays answer with pandas code shown.

**If any step fails:** Update `analyses.status` to `error`. Write the error message to `analyses.error_message` with the appropriate prefix — `USER_ERROR:` for user-fixable errors (wrong file type, file too large), `SYSTEM_ERROR:` for pipeline failures. Update `analyses.updated_at`. The frontend detects the error status on the next poll and displays the appropriate error UI.

---

## Pause State Design

The pipeline has two pause states — domain confirmation (Step 9) and missing value / outlier decisions (Step 11). Both pause states follow the same pattern:

1. Pipeline halts and waits
2. Frontend receives a special status indicating a pause is active
3. Frontend displays the question and options to the user
4. User responds via the frontend
5. Frontend POSTs the response to the backend
6. Backend resumes the pipeline with the user's input incorporated

The pause states are **DB-polling nodes**, not LangGraph `interrupt()` — the installed LangGraph 0.2.0 does not support `interrupt()` (decisions.md, 2026-05-08). Each pause-wait node clears `user_pause_response` in Supabase, sets `status` to the specific pause value, then polls every 3 seconds until a response appears. They are not timeouts — the pipeline waits indefinitely for user input.

**Pause question persistence:** the pause-wait node writes the active question — the Profiler's or Cleaner's raw pause-signal JSON — to `analyses.pause_data` in the same single update that sets the pause status. `pause_data` is non-null only while `status` is `domain_pause`, `missing_value_pause` or `outlier_pause`. GET `/status` returns it in those statuses only; GET `/api/analysis/{id}` never carries it. POST `/resume` validates the answer against it (`pause_type`, `option_id`, and `column_name` or `corrected_domain`) and clears it in the same update that restores the status. Contract and shapes: decisions.md 2026-09-22. The frontend still shows a placeholder naming the pause type. The pause UI is a separate later build, blocked on pre-existing answer-consumption bugs (errors.md 2026-09-22): the Profiler ignores a domain answer, and pauses on more than one column likely loop.

---

## API Endpoints

Read-only GET endpoints are public by analysis_id: the UUID4 id is the access capability, and no `session-id` header is required or checked (dependency `get_public_read_access` in backend/main.py, which also returns 404 for a malformed id). Endpoints that change state or can trigger an LLM call — POST question and POST resume — require a `session-id` header matching the `session_id` stored in the analyses record (dependency `get_session`). POST /api/upload has no auth. See decisions.md 2026-09-21.

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/upload` | Upload CSV or Excel. Returns analysis_id and session_id. | No |
| GET | `/api/analysis/{id}/status` | Get current pipeline status and current_agent name. | No (public by id) |
| GET | `/api/analysis/{id}` | Get full analysis result including all agent outputs. | No (public by id) |
| POST | `/api/analysis/{id}/question` | Submit a custom question. Returns question_id with status pending. | Yes |
| GET | `/api/analysis/{id}/question/{question_id}` | Poll a submitted question for its computed answer and pandas code. Filters on both ids. | No (public by id) |
| POST | `/api/analysis/{id}/resume` | Submit the user's response to an active pause state (`{"response": {...}}`). Only valid when status is `domain_pause`, `missing_value_pause`, or `outlier_pause`; returns 400 before any write unless `response.pause_type` matches the status and `option_id` (plus `column_name`, or `corrected_domain` for a domain `correct`) matches the stored `pause_data` (if no usable option ids are stored, `option_id` is skipped but `column_name` is still checked — decisions.md 2026-09-22), which is what rejects a stale tab's answer when the active pause is on a different column; restores status to `profiling` or `cleaning` and clears `pause_data` in one update that applies only if the pause read by this request (status and `updated_at`) has not changed before the write, else 409; the polling pause-wait node then picks it up. | Yes |
| GET | `/api/analysis/{id}/charts` | Get list of chart file paths for this analysis (not currently called by the frontend). | No (public by id) |
| GET | `/charts/{filename}` | Serve chart image file. Handled by FastAPI StaticFiles mount. | No |

### POST /api/upload

**Request:** multipart/form-data with fields:
- `file`: the CSV or Excel file
- `context` (optional): string — what the user wants to understand
- `user_type` (optional): string — "business_owner", "data_analyst", or "data_scientist"

**Response:** UploadResponse
````
{
  "analysis_id": "uuid",
  "filename": "original_filename.csv",
  "status": "profiling",
  "message": "Analysis started. Use analysis_id to poll for results.",
  "session_id": "uuid"
}
````

### GET /api/analysis/{id}/status

**Response:** StatusResponse
````
{
  "analysis_id": "uuid",
  "status": "analyzing",
  "current_agent": "analyzer",
  "progress_pct": 60.0,
  "error_message": null
}
````

`current_agent` values: `"profiler"`, `"cleaner"`, `"analyzer"`, `"explainer"`, `null` (when complete or error).

`progress_pct` values: profiling=20, cleaning=40, analyzing=60, explaining=80, complete=100.

### GET /api/analysis/{id}

**Response:** AnalysisResponse — all fields are optional since the response is valid at any pipeline stage.

### POST /api/analysis/{id}/question

**Request body:** QuestionRequest
````
{
  "question": "Which product category had the highest return rate in Q3?"
}
````

**Response:** QuestionResponse
````
{
  "question_id": "uuid",
  "analysis_id": "uuid",
  "question": "Which product category had the highest return rate in Q3?",
  "answer": "Electronics had the highest return rate in Q3 at 14.3%, compared to the overall average of 6.1%.",
  "pandas_code": "df[df['quarter']=='Q3'].groupby('category')['returned'].mean().sort_values(ascending=False).head(1)",
  "status": "complete"
}
````

---

## Supabase Database Schema

### Table: analyses

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| id | uuid | gen_random_uuid() | Primary key |
| created_at | timestamptz | now() | |
| updated_at | timestamptz | now() | Updated on every status change |
| session_id | uuid | gen_random_uuid() | Minimal auth token |
| original_filename | text NOT NULL | — | The name the user uploaded |
| stored_filename | text NOT NULL | — | UUID-based name on disk |
| file_size | integer | — | Bytes |
| status | text NOT NULL | 'profiling' | See AnalysisStatus enum |
| error_message | text | — | Prefixed USER_ERROR: or SYSTEM_ERROR: |
| profile_report | jsonb | — | Full ProfileReport object |
| cleaning_report | jsonb | — | Full CleaningReport object |
| cleaning_decisions | jsonb | — | Just the decisions list for easy frontend display |
| analysis_report | jsonb | — | Full AnalysisReport object |
| insight_report | jsonb | — | Full FullInsightReport object (all 3 layers) |
| executive_summary | jsonb | — | ExecutiveSummary (5 bullets) |
| chart_paths | text[] | — | Array of chart file paths |
| row_count | integer | — | Populated after profiling |
| column_count | integer | — | Populated after profiling |
| data_quality_score | numeric | — | 0.0 to 1.0, populated after analyzing |

**Correction note:** `profile_report`, `analysis_report`, `insight_report`, and `executive_summary` are stored as raw LLM-contract dicts, not validated instances of the pydantic models named above — the model field names above do not match the actual stored keys. See decisions.md `2026-05-07 | Raw dict save to Supabase JSONB...` and `2026-06-04 | AnalysisResponse relaxes profile_report, analysis_report, insight_report, executive_summary to dict...` for the authoritative stored shapes and rationale. `cleaning_report` and `cleaning_decisions` are unaffected — they validate cleanly against their pydantic models.

### Table: questions

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| id | uuid | gen_random_uuid() | Primary key |
| analysis_id | uuid | — | References analyses(id) |
| created_at | timestamptz | now() | |
| question | text NOT NULL | — | The user's question |
| answer | text | — | The computed answer in plain language |
| pandas_code | text | — | The exact pandas code used |
| status | text | 'pending' | See QuestionStatus enum |

### Indexes

````
CREATE INDEX idx_analyses_status ON analyses(status);
CREATE INDEX idx_analyses_created_at ON analyses(created_at);
CREATE INDEX idx_questions_analysis_id ON questions(analysis_id);
````

### Supabase Storage

Bucket: `cleaned-datasets`

Keys follow the pattern: `{analysis_id}.parquet`

The bucket must exist before the Cleaner runs. Create it manually in the Supabase dashboard or via migration before the first pipeline run.

### Schema Migrations

**Rule 4 in CLAUDE.md is absolute:** Never modify the Supabase schema directly from Claude Code or by hand in the dashboard. All schema changes go through migration files. Migration files are committed to the repository before being applied.

---

## Complete Project Folder Structure

````
backend/
  main.py                         FastAPI entry point. Mounts StaticFiles
                                  at /charts -> backend/outputs/charts/
  config.py                       All environment variables. Single source
                                  of truth. Every other module imports from
                                  here.
  agents/
    __init__.py
    profiler.py                   The Comprehender
    cleaner.py                    The Thoughtful Cleaner
    analyzer.py                   The Deep Investigator
    explainer.py                  The Translator and Advisor
    orchestrator.py               LangGraph graph definition only.
                                  No business logic here.
  tools/
    __init__.py
    data_tools.py                 Pandas operations: load, profile,
                                  clean, analyze
    viz_tools.py                  Chart generation with matplotlib,
                                  seaborn, plotly. Saves to
                                  backend/outputs/charts/
    code_executor.py              Safe execution of pandas code for
                                  custom user questions
  models/
    __init__.py
    schemas.py                    All 26 pydantic models
  prompts/
    profiler_system.md            System prompt for The Comprehender
    cleaner_system.md             System prompt for The Thoughtful Cleaner
    analyzer_system.md            System prompt for The Deep Investigator
    explainer_system.md           System prompt for The Translator and
                                  Advisor - write this one last, on Opus
  utils/
    __init__.py
    supabase_client.py            Single shared Supabase client instance
    langsmith_client.py           LangSmith tracing setup
    file_handler.py               Local file ops + Supabase Storage
                                  upload/download + cleanup()
  outputs/
    charts/                       Generated chart images saved here.
                                  Listed in .claudeignore.

frontend/
  app/
    page.tsx                      Home page - file upload
    analysis/[id]/page.tsx        Results page - three-layer output
    layout.tsx                    Root layout, dark mode, fonts
  components/
    FileUpload.tsx                Drag-and-drop upload zone
    AnalysisProgress.tsx          Live agent pipeline progress indicator
    InsightReport.tsx             Three-layer report display
    ChartGrid.tsx                 Interactive chart grid
    QuestionInput.tsx             Custom question input and answer display
  lib/
    api.ts                        All API call functions
    types.ts                      TypeScript interfaces matching schemas

tests/
  test_profiler.py
  test_cleaner.py
  test_analyzer.py
  test_explainer.py
  test_api.py
  fixtures/
    iris.csv                      150 rows, 5 columns, clean.
                                  Basic functionality tests.
    messy_data.csv                30% missing values, duplicate rows.
                                  Cleaning tests.
    time_series_data.csv          Date column, numeric values over time.
                                  Time series tests.

docs/
  intelligence-philosophy.md
  architecture.md
  agents/
    profiler.md
    cleaner.md
    analyzer.md
    explainer.md
  infrastructure.md               (this file)
  ui-and-frontend.md
  plugins-and-mcps.md

CLAUDE.md                         Lean spine - always loaded
decisions.md                      Append-only decision log
tasks.md                          Current build progress
errors.md                         Error log
.claudeignore                     Token conservation
requirements.txt
.env
.env.example
.gitignore
````

---

## Environment Variables Required

All loaded via `backend/config.py`. All required — system fails fast on import if any are missing.

| Variable | Purpose |
|----------|---------|
| ANTHROPIC_API_KEY | Claude API access for all agents |
| OPENAI_API_KEY | OpenAI API access (fallback or embedding use) |
| SUPABASE_URL | Supabase project URL |
| SUPABASE_PUBLISHABLE_KEY | Supabase anon key for client operations |
| SUPABASE_SECRET_KEY | Supabase service role key for server operations |
| LANGSMITH_API_KEY | LangSmith tracing |
| LANGSMITH_PROJECT | LangSmith project name (data-analysis-agent) |
| LANGCHAIN_TRACING_V2 | Must be set to "true" |
| GITHUB_TOKEN | GitHub MCP authentication |

---

## StaticFiles Mount

In `backend/main.py`, charts are served via FastAPI's StaticFiles:

````
from fastapi.staticfiles import StaticFiles
app.mount("/charts", StaticFiles(directory="backend/outputs/charts"), name="charts")
````

Charts are then accessible at `/charts/{filename}` from the frontend. The frontend references charts using this path, not the filesystem path.
