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

### Backend — Prompts

(complete)

### Backend — Tools

- [x] backend/tools/__init__.py
- [x] backend/tools/viz_tools.py
- [x] backend/tools/code_executor.py

### Backend — Agents

- [x] backend/agents/explainer.py
- [x] backend/agents/orchestrator.py

### Frontend — **NEXT** ← START HERE

- [ ] Next.js app scaffold (App Router, TypeScript, Tailwind, shadcn/ui)
- [ ] Upload page — file input, drag-and-drop, validation
- [ ] Results page — three-layer output display (executive / analyst / technical)
- [ ] Polling logic — job status updates
- [ ] Charts — Recharts integration for analysis visualizations
- [ ] Mobile viewport testing (320px minimum)

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
