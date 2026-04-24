# Data Analysis Agent — CLAUDE.md

This is the spine document. It is intentionally lean so Claude Code does not burn tokens on every session start. Deep context lives in dedicated docs under `docs/` and is loaded only when the current task needs it.

---

## What This System Is

This system is an investigator, not a responder. It treats data as evidence to be reasoned about. It thinks about data the way the world's best analyst would — with domain awareness, calibrated confidence, intellectual honesty, and the ability to surface what the user didn't know to ask. Every existing AI tool responds to what you ask. This system investigates what matters.

For the full intelligence philosophy including the Investigator Mindset, Domain Intelligence, Data Provenance Intelligence, Causality Reasoning, Calibrated Confidence Framework, Progressive Revelation, Honest Limitation Acknowledgment, User Types, and Output Layers, read `docs/intelligence-philosophy.md`.

---

## Document Map — Load On Demand

| Topic | File |
|-------|------|
| Full intelligence philosophy, user types, output layers | `docs/intelligence-philosophy.md` |
| System architecture diagram, component relationships | `docs/architecture.md` |
| Profiler (Agent 1) full behavior specification | `docs/agents/profiler.md` |
| Cleaner (Agent 2) full behavior specification | `docs/agents/cleaner.md` |
| Analyzer (Agent 3) full behavior specification | `docs/agents/analyzer.md` |
| Explainer (Agent 4) full behavior specification | `docs/agents/explainer.md` |
| LangGraph flow, API endpoints, Supabase schema, folder structure | `docs/infrastructure.md` |
| UI design rules, three-layer display, error UX, polling | `docs/ui-and-frontend.md` |
| Plugin and MCP invocation protocol (when/why/how) | `docs/plugins-and-mcps.md` |

Only load the doc relevant to the current task. Do not load every doc on every session.

---

## Active Plugins and MCPs

Installed and available. For invocation details see `docs/plugins-and-mcps.md`.

- Sequential Thinking MCP — structured reasoning before complex decisions
- Superpowers Plugin — parallel hypothesis investigation
- Memory MCP — cumulative intelligence across agents
- Code Review Plugin — verify computations and pandas code
- Context7 MCP — verify library docs before implementation
- LangSmith Tracing — every agent run traced
- GitHub MCP — version control
- Frontend Design Plugin — UI components
- Security Review Plugin — pre-deployment scanning
- Supabase MCP — database introspection and migrations
- Brave Search MCP — last-resort error resolution

---

## Tech Stack Summary

Backend: Python 3.11, FastAPI, Uvicorn, LangChain, LangGraph, LangSmith, Supabase client, pandas, numpy, matplotlib, seaborn, plotly, pydantic, pyarrow.

Frontend: Next.js 14 App Router, TypeScript strict, Tailwind, shadcn/ui, Recharts, Framer Motion, axios.

Exact versions pinned in `requirements.txt`. Never install packages without stating the reason.

---

## Non-Negotiable Rules

1. NEVER hardcode API keys, URLs, passwords. Always `os.getenv()`. Zero exceptions.
2. NEVER delete working code without asking explicitly first.
3. NEVER install a package without stating the exact reason it is needed.
4. NEVER modify Supabase schema directly. Migration files only.
5. NEVER mark any task complete without running tests.
6. NEVER write a new function without checking if it already exists.
7. NEVER put system prompts inline in Python. Load from `backend/prompts/` folder always.
8. NEVER run an agent without LangSmith tracing attached.
9. NEVER present a correlation as an explanation. Always label correlations as correlations and reason about causality separately.
10. NEVER remove an outlier without domain-appropriate reasoning documented in the cleaning report.
11. NEVER produce a statistic that looks authoritative but cannot be reliably computed from the available data. State limitations explicitly.
12. ALWAYS use Context7 MCP to check latest docs before using any library.
13. ALWAYS run Code Review plugin after completing each major feature.
14. ALWAYS run Security Review plugin before any deployment.
15. ALWAYS commit after every working feature with a descriptive message.
16. ALWAYS commit before modifying any module that currently works.
17. ALWAYS explain plan before writing code. Wait for approval on anything non-trivial.
18. ALWAYS use type hints on every function.
19. ALWAYS use async/await for all FastAPI endpoints.
20. ALWAYS handle errors explicitly with meaningful messages.
21. ALWAYS invoke Sequential Thinking MCP before designing any complex feature or agent decision.
22. ALWAYS produce output at all three user layers (executive, analyst, technical) for every analysis.
23. ALWAYS log every major architectural or design decision to `decisions.md` the moment it is made.

---

## Session Start Protocol

Every session, without exception:

1. Read `CLAUDE.md` (this file)
2. Read `tasks.md` — current build state
3. Read `decisions.md` — accumulated design decisions
4. Read `errors.md` — known issues and their solutions
5. Load the specific `docs/` file(s) relevant to the current task, if any
6. Check Context7 for library version updates relevant to the current task
7. Output: `Current state: [what exists]. Next task: [what we are doing]. Known issues: [from errors.md]. Relevant decisions loaded: [which decisions apply].`
8. Wait for confirmation before writing any code.

---

## Error Protocol

- Cannot solve in 2 attempts: STOP. Explain the error, what was tried, probable cause.
- After solving: add to `errors.md` immediately.
- Format: `Date | Error | Root cause | Solution`
- Session start: read `errors.md` before any code.

---

## Definition of Done

A feature is complete only when ALL of the following are true:

1. Code written and working
2. Empty file handled gracefully
3. Wrong file type handled gracefully
4. Corrupted data handled gracefully
5. File above 100MB handled gracefully
6. Tests written and passing using appropriate fixture from `tests/fixtures/`
7. LangSmith traces visible in dashboard
8. Code Review plugin run and issues resolved
9. No hardcoded values
10. Committed to GitHub with descriptive message
11. `tasks.md` updated
12. Any new design decision logged to `decisions.md`
13. If UI feature: tested on mobile viewport (320px minimum)
14. Intelligence layers verified: domain hypothesis stated, calibrated confidence applied to all findings, progressive revelation structure followed, all three user layers present in output

---

## Where Deep Context Lives

This spine is intentionally brief. If you need depth on any topic listed in the Document Map above, load the specific file. Do not ask for content that already exists in a dedicated doc — load it and read it.
