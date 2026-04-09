# Data Analysis Agent — CLAUDE.md

## Complete Tech Stack

### Backend Python Packages
- fastapi==0.111.0
- uvicorn==0.29.0
- anthropic==0.25.0
- openai==1.30.0
- langchain==0.2.0
- langgraph==0.1.0
- langsmith==0.1.63
- supabase==2.4.0
- pandas==2.2.0
- numpy==1.26.0
- matplotlib==3.8.0
- seaborn==0.13.0
- plotly==5.20.0
- python-multipart==0.0.9
- python-dotenv==1.0.0
- pydantic==2.7.0
- openpyxl==3.1.0

### Frontend
- Next.js 14 App Router
- TypeScript strict mode
- Tailwind CSS
- shadcn/ui components
- Recharts for all data charts
- Framer Motion for all animations
- axios for API calls

---

## Claude Code Plugins and MCPs Active In This Project

### Plugins Installed
- **Superpowers**: use for brainstorming, sub-agent development, systematic debugging, code review
- **Frontend Design**: use for all UI generation to ensure production quality non-generic output
- **Code Review**: use after completing each major feature before committing
- **Security Review**: use before any deployment push to scan for vulnerabilities

### MCP Servers Active
- **Supabase MCP**: use to directly query database, read schema, run migrations
- **GitHub MCP**: use to create commits, push code, manage branches
- **Context7 MCP**: use to get up to date documentation for any library before writing code using it
- **Brave Search MCP**: use to search for solutions when stuck on an error
- **Memory MCP**: use to remember project decisions and patterns across sessions
- **Sequential Thinking MCP**: use before designing any complex feature to think through it step by step before writing code

---

## Project Folder Structure

```
backend/
  main.py                        # FastAPI app entry point
  config.py                      # all environment variables loaded here, nowhere else
  agents/
    __init__.py
    profiler.py
    cleaner.py
    analyzer.py
    explainer.py
    orchestrator.py              # LangGraph graph definition only
  tools/
    __init__.py
    data_tools.py
    viz_tools.py
    code_executor.py
  models/
    __init__.py
    schemas.py
  prompts/
    profiler_system.md
    cleaner_system.md
    analyzer_system.md
    explainer_system.md
  utils/
    __init__.py
    supabase_client.py
    langsmith_client.py
    file_handler.py
  outputs/
    charts/
frontend/
  app/
    page.tsx
    analysis/[id]/page.tsx
    layout.tsx
  components/
    FileUpload.tsx
    AnalysisProgress.tsx
    InsightReport.tsx
    ChartGrid.tsx
    QuestionInput.tsx
  lib/
    api.ts
    types.ts
tests/
  test_profiler.py
  test_cleaner.py
  test_analyzer.py
  test_explainer.py
  test_api.py
CLAUDE.md
architecture.md
tasks.md
decisions.md
errors.md
.env
.env.example
.gitignore
requirements.txt
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/upload | Upload CSV or Excel file |
| GET | /api/analysis/{id} | Get full analysis result |
| GET | /api/analysis/{id}/status | Poll analysis status |
| POST | /api/analysis/{id}/question | Ask a follow-up question |
| GET | /api/analysis/{id}/charts | Retrieve chart paths |

---

## Supabase Database Schema

### Table: analyses
| Column | Type | Default |
|--------|------|---------|
| id | uuid primary key | gen_random_uuid() |
| created_at | timestamptz | now() |
| filename | text not null | — |
| status | text not null | profiling |
| profile_report | jsonb | — |
| cleaning_report | jsonb | — |
| cleaning_decisions | jsonb | — |
| analysis_report | jsonb | — |
| insight_report | jsonb | — |
| executive_summary | jsonb | — |
| chart_paths | text[] | — |
| row_count | integer | — |
| column_count | integer | — |
| data_quality_score | numeric | — |

### Table: questions
| Column | Type | Default |
|--------|------|---------|
| id | uuid primary key | gen_random_uuid() |
| analysis_id | uuid | references analyses(id) |
| created_at | timestamptz | now() |
| question | text not null | — |
| answer | text | — |
| pandas_code | text | — |
| status | text | pending |

---

## Non-Negotiable Rules

1. NEVER hardcode API keys, URLs, passwords anywhere. Always `os.getenv()`. Zero exceptions.
2. NEVER delete working code without asking explicitly first.
3. NEVER install a package without stating the exact reason it is needed.
4. NEVER modify Supabase schema directly. Migration files only.
5. NEVER mark any task complete without running tests.
6. NEVER write a new function without checking if it exists already.
7. NEVER put system prompts inline in Python. Load from `prompts/` folder always.
8. NEVER run an agent without LangSmith tracing attached.
9. ALWAYS use Context7 MCP to check latest docs before using any library.
10. ALWAYS run Code Review plugin after completing each major feature.
11. ALWAYS run Security Review plugin before any deployment.
12. ALWAYS commit after every working feature with a descriptive message.
13. ALWAYS commit before modifying any module that currently works.
14. ALWAYS explain plan before writing code. Wait for approval on anything non-trivial.
15. ALWAYS use type hints on every function.
16. ALWAYS use async/await for all FastAPI endpoints.
17. ALWAYS handle errors explicitly with meaningful messages.
18. ALWAYS use Sequential Thinking MCP before designing any complex feature.

---

## Error Protocol

- Cannot solve in 2 attempts: **STOP**. Explain the error, what was tried, probable cause.
- After solving: add to `errors.md` immediately.
- Format: `Date | Error | Root cause | Solution`
- Session start: read `errors.md` before any code.

---

## Session Start Protocol — Every Session No Exceptions

1. Read `CLAUDE.md` fully
2. Read `tasks.md`
3. Read `errors.md`
4. Read `architecture.md`
5. Check Context7 for any library version updates relevant to current task
6. Output: `Current state: [what exists]. Next task: [what we are doing]. Known issues: [from errors.md].`
7. Wait for confirmation before writing any code.

---

## UI and Design Rules

- Dark mode default. Zero generic AI aesthetic.
- Agent pipeline shown as live progress indicator — user sees each agent activate in real time.
- Upload: large drag and drop zone, accepts CSV and Excel, shows file preview before analysis starts.
- Results: executive summary prominent at top, full report in collapsible sections below.
- All charts interactive with hover tooltips showing exact values.
- Custom question input at bottom of results page, conversational feel.
- Mobile responsive at 320px minimum width.
- Smooth transitions using Framer Motion on all route changes and section reveals.
- Color system: use shadcn/ui tokens, never raw hex values in components.

---

## Definition of Done

A feature is **complete** only when ALL of the following are true:

1. Code written and working
2. Empty file handled gracefully
3. Wrong file type handled gracefully
4. Corrupted data handled gracefully
5. Very large file (above 50MB) handled gracefully
6. Tests written and passing
7. LangSmith traces visible in dashboard
8. Code Review plugin run and issues resolved
9. No hardcoded values
10. Committed to GitHub with descriptive message
11. `tasks.md` updated
12. If UI feature: tested on mobile viewport
