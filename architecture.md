# Architecture

## Overview

Data Analysis Agent is a full-stack application that accepts CSV/Excel uploads, runs a multi-agent LangGraph pipeline to profile, clean, analyze, and explain the data, then surfaces results and charts through a Next.js frontend.

---

## System Diagram

```
User (browser)
    │
    ▼
Next.js Frontend (App Router)
    │  REST via axios
    ▼
FastAPI Backend
    │
    ├── POST /api/upload         → stores file, creates analysis row in Supabase
    ├── GET  /api/analysis/{id}  → returns full result
    ├── GET  /api/analysis/{id}/status
    ├── POST /api/analysis/{id}/question
    └── GET  /api/analysis/{id}/charts
         │
         ▼
    LangGraph Orchestrator (agents/orchestrator.py)
         │
         ├── Profiler Agent   → generates profile_report
         ├── Cleaner Agent    → generates cleaning_report + cleaning_decisions
         ├── Analyzer Agent   → generates analysis_report + chart_paths
         └── Explainer Agent  → generates insight_report + executive_summary
              │
              ▼
         Supabase (analyses + questions tables)
```

---

## Agent Pipeline

| Step | Agent | Input | Output stored |
|------|-------|-------|---------------|
| 1 | Profiler | raw DataFrame | `profile_report` |
| 2 | Cleaner | raw DataFrame + profile | `cleaning_report`, `cleaning_decisions` |
| 3 | Analyzer | cleaned DataFrame | `analysis_report`, `chart_paths` |
| 4 | Explainer | analysis report | `insight_report`, `executive_summary` |

---

## Key Design Decisions

<!-- Cross-reference decisions.md for rationale -->

- LangGraph used for orchestration (stateful, inspectable pipeline)
- All agent system prompts loaded from `prompts/` — never inline
- LangSmith tracing required on every agent run
- Supabase as primary persistence — all state written between each agent step
- Charts saved to `outputs/charts/` and paths stored in DB

---

## Technology Choices

| Layer | Technology |
|-------|------------|
| Backend framework | FastAPI |
| Agent orchestration | LangGraph |
| LLM | Claude (Anthropic) |
| Database | Supabase (Postgres) |
| Observability | LangSmith |
| Frontend | Next.js 14 App Router |
| Styling | Tailwind CSS + shadcn/ui |
| Charts | Recharts |
| Animations | Framer Motion |
