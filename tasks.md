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

---

## In Progress

<!-- Move tasks here when actively working on them -->

---

## Backlog

### Backend — Core Infrastructure

- [ ] backend/main.py — FastAPI app, all endpoints — **NEXT**

### Backend — Prompts

- [ ] backend/prompts/profiler.md
- [ ] backend/prompts/cleaner.md
- [ ] backend/prompts/analyzer.md
- [ ] backend/prompts/explainer.md

### Backend — Agents

- [ ] backend/agents/profiler.py
- [ ] backend/agents/cleaner.py
- [ ] backend/agents/analyzer.py
- [ ] backend/agents/explainer.py
- [ ] backend/agents/orchestrator.py

### Frontend

- [ ] Next.js app scaffold (App Router, TypeScript, Tailwind, shadcn/ui)
- [ ] Upload page — file input, drag-and-drop, validation
- [ ] Results page — three-layer output display (executive / analyst / technical)
- [ ] Polling logic — job status updates
- [ ] Charts — Recharts integration for analysis visualizations
- [ ] Mobile viewport testing (320px minimum)

### Infrastructure

- [ ] Supabase RLS policies
- [ ] Supabase Storage bucket for uploaded files
- [ ] Vercel deployment
