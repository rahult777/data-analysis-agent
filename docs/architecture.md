# System Architecture

This document describes the high-level architecture of the Data Analysis Agent system. Load this doc when designing new components, planning integrations, or reasoning about how parts of the system connect to each other.

---

## System Overview

The Data Analysis Agent is a multi-agent pipeline that transforms raw uploaded data files into structured, layered intelligence reports. It consists of a Python FastAPI backend, a LangGraph-orchestrated 4-agent pipeline, a Supabase database and storage layer, a LangSmith observability layer, and a Next.js frontend.

The system is designed around one core principle: agents do not just process data, they think about data. Every agent has a conceptual identity that reflects how it reasons, not just what it computes.

---

## High-Level Architecture Diagram

```
User (Browser)
      |
      | HTTP / REST
      v
+---------------------------------------------------------+
|                    FastAPI Backend                       |
|                    (main.py)                             |
|                                                         |
|  POST /api/upload      --> File Handler                 |
|  GET  /api/analysis/   --> Supabase Client              |
|  GET  /api/.../status  --> Supabase Client              |
|  POST /api/.../question--> Explainer Agent              |
|  GET  /api/.../charts  --> Supabase Client              |
|  GET  /charts/{file}   --> StaticFiles Mount            |
+------------------+--------------------------------------+
                   |
                   | LangGraph Orchestration
                   v
+---------------------------------------------------------+
|                 LangGraph Pipeline                       |
|                 (orchestrator.py)                        |
|                                                         |
|  +----------+  +----------+  +----------+  +--------+  |
|  | Profiler |->| Cleaner  |->| Analyzer |->|Explainer| |
|  |(profiler)|  |(cleaner) |  |(analyzer)|  |(explainer| |
|  +----------+  +----------+  +----------+  +--------+  |
|                                                         |
|  Each agent reads Memory MCP at start                   |
|  Each agent writes to Memory MCP at end                 |
|  Every agent run traced in LangSmith                    |
+------------------+--------------------------------------+
                   |
         +---------+---------+
         |                   |
         v                   v
+-----------------+  +-------------------+
|    Supabase     |  |   LangSmith        |
|    Database     |  |   Observability    |
|                 |  |                    |
|  analyses table |  |  Agent run traces  |
|  questions table|  |  Reasoning steps   |
|                 |  |  Tool calls        |
|  Storage:       |  |  Decision logs     |
|  cleaned-datasets|  +-------------------+
|  bucket         |
+-----------------+
```

---

## Component Descriptions

### FastAPI Backend (backend/main.py)

The entry point for all HTTP traffic. Responsibilities:
- Receives file uploads and validates format and size
- Triggers the LangGraph pipeline asynchronously
- Serves analysis results and status from Supabase
- Accepts and routes custom user questions to the Explainer
- Serves generated chart images via StaticFiles mount at `/charts/`
- Validates session_id on every request except upload

All endpoints are async. CORS configured for frontend origin.

### Config Layer (backend/config.py)

Single source of truth for all environment variables. Loaded once at startup. Every other module imports from here — never from os.environ directly. Validates all required variables are present on import, fails fast with a clear error if any are missing.

### Supabase Client (backend/utils/supabase_client.py)

Single shared Supabase client instance for the entire backend. Initialized once, imported everywhere. Handles all reads and writes to the analyses and questions tables. Also used by file_handler.py for Supabase Storage operations.

### File Handler (backend/utils/file_handler.py)

Handles the full lifecycle of uploaded files:
- Validates file format (CSV or Excel only)
- Validates file size (100MB maximum)
- Saves to temporary local storage with a UUID stored_filename
- Uploads cleaned parquet to Supabase Storage bucket `cleaned-datasets`
- Downloads parquet from Storage when Explainer needs it for custom questions
- Deletes local temp files after successful cloud persistence
- cleanup() method called after successful Cleaner run

### LangSmith Client (backend/utils/langsmith_client.py)

Sets up LangSmith tracing for all agent runs. Provides:
- get_langsmith_client() — returns a LangSmith Client instance
- create_tracer(run_name) — returns a LangChainTracer for LangGraph callbacks
- validate_langsmith_connection() — verifies connectivity on import

### Pydantic Schemas (backend/models/schemas.py)

26 pydantic models defining the shape of every piece of data in the system. Built in layers:
- Enums: AnalysisStatus, QuestionStatus
- Leaf models: ColumnProfile, CleaningDecision, DescriptiveStats, etc.
- Mid-tier models: ProfileReport, CleaningReport, AnalysisReport, etc.
- API layer models: UploadResponse, AnalysisResponse, StatusResponse, etc.

All models have `model_config = ConfigDict(from_attributes=True)` for direct construction from Supabase responses.

### LangGraph Orchestrator (backend/agents/orchestrator.py)

Defines the LangGraph graph structure only — no business logic. Wires the 4 agents together with the correct edges, pause states, and conditional routing. The full 23-step flow is documented in `docs/infrastructure.md`.

### The 4 Agents

Each agent is a LangGraph node with a specific role and reasoning identity. Full behavior specifications are in individual docs:

| File | Conceptual Name | Role |
|------|----------------|------|
| backend/agents/profiler.py | The Comprehender | Forms deep understanding of what the data is, where it came from, what it can and cannot tell us |
| backend/agents/cleaner.py | The Thoughtful Cleaner | Makes every cleaning decision in the context of domain understanding |
| backend/agents/analyzer.py | The Deep Investigator | Allocates analytical depth by significance, not uniformity |
| backend/agents/explainer.py | The Translator and Advisor | Produces output at all three user layers, handles custom questions |

### System Prompts (backend/prompts/)

One markdown file per agent. Loaded at runtime — never inline in Python code. These files are the intelligence of the system. They are written against the full intelligence philosophy in `docs/intelligence-philosophy.md`.

### Tools (backend/tools/)

Shared utilities used by agents:
- data_tools.py — pandas operations for loading, profiling, cleaning, analyzing
- viz_tools.py — chart generation with matplotlib/seaborn/plotly, saves to backend/outputs/charts/
- code_executor.py — safely executes pandas code for custom user questions

### Frontend (frontend/)

Next.js 14 App Router with TypeScript strict mode. Two main routes:
- `/` — home page with file upload
- `/analysis/[id]` — results page with three-layer output display

Polls `/api/analysis/{id}/status` every 3 seconds while pipeline is running. Displays agent progress in real time. Serves charts from `/charts/{filename}`. Full UI specification in `docs/ui-and-frontend.md`.

---

## Data Flow

### Upload and Pipeline Flow

```
1. User uploads CSV/Excel via drag-drop zone
2. Frontend POSTs to /api/upload
3. Backend validates format and size
4. Backend creates analyses record in Supabase (status: profiling)
5. Backend returns analysis_id and session_id to frontend
6. Frontend begins polling /api/analysis/{id}/status every 3 seconds
7. LangGraph pipeline starts asynchronously

Pipeline:
  Profiler runs -> saves ProfileReport to Supabase
  [Domain confidence check - pause if below 80%]
  [Missing values check - pause if >30% in any column]
  Cleaner runs -> saves CleaningReport -> uploads parquet to Storage
  [File cleanup]
  Analyzer runs -> saves AnalysisReport -> saves charts
  Explainer runs -> saves ExecutiveSummary + FullInsightReport
  Status set to complete

8. Frontend receives complete status
9. Frontend displays results at all three layers
10. User asks custom questions -> Explainer downloads parquet -> computes -> returns answer
```

### Custom Question Flow

```
1. User types question in QuestionInput component
2. Frontend POSTs to /api/analysis/{id}/question with session_id header
3. Backend validates session_id
4. Backend creates question record (status: pending)
5. Explainer downloads {analysis_id}.parquet from Supabase Storage
6. Explainer translates question to pandas operation
7. Explainer executes pandas operation on real cleaned data
8. Backend saves answer + pandas_code to question record
9. Backend returns QuestionResponse to frontend
10. Frontend displays answer with pandas code shown
```

---

## Authentication Model

Minimal session-based authentication. On upload, a UUID session_id is generated and stored in the analyses record. The frontend stores this session_id and includes it as a header on all subsequent requests for that analysis. The backend validates it matches the record before returning data.

This prevents one user from accessing another user's analysis without implementing full auth. Row Level Security (RLS) will be added to Supabase tables before any production deployment.

---

## Persistence Model

| Data | Where Stored |
|------|-------------|
| Analysis metadata and reports | Supabase analyses table (JSONB columns) |
| Custom questions and answers | Supabase questions table |
| Generated chart images | Local filesystem: backend/outputs/charts/ |
| Cleaned dataset for custom questions | Supabase Storage: cleaned-datasets/{analysis_id}.parquet |
| Uploaded raw files | Local temp storage (deleted after cleaning) |

---

## Observability Model

Every agent run is traced in LangSmith with a named trace. The trace includes:
- Which agent ran
- What tools it called
- What decisions it made
- What it wrote to Supabase
- Any errors encountered

This enables debugging, quality auditing, and understanding of agent reasoning without inspecting code.
