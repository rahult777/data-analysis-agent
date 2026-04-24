# Plugins and MCPs — Complete Protocol

This document contains the complete specification for every plugin and MCP active in this project. Load this doc when you need to know when, why, or how to invoke any tool. Do not guess at plugin usage — the rules are explicit and non-negotiable.

---

## The Governing Principle

Plugins and MCPs are not optional enhancements. They are required components of the intelligence architecture. Using them correctly is the difference between building a system that works and building a system that thinks.

Every plugin has a specific trigger condition. When that condition is met, the plugin is invoked. There is no judgment call about whether to use it — the condition determines the action.

---

## Sequential Thinking MCP

**What it does:** Forces structured, step-by-step reasoning before action. Prevents pattern matching to superficially similar situations without thinking through what is actually true about this specific case. When the problem is complex, thinking before acting produces dramatically better outcomes than jumping straight to implementation.

**When to invoke:**
- Before designing any agent's analysis approach for a specific dataset
- Before writing any system prompt for any agent
- Before designing any complex feature that has multiple moving parts
- Before making any architectural decision that will be hard to undo
- Before planning the LangGraph orchestration flow
- Any time you feel tempted to just start writing code without a clear plan

**How to invoke:** Type the design problem into the Sequential Thinking tool. Let it think through all angles. Only proceed to implementation after the thinking is complete.

**What it produces:** A structured plan with reasoning at each step. This plan becomes the basis for the implementation prompt.

**Example trigger:** "I need to design the self-evaluation loop for the Analyzer agent. Before writing any code, use Sequential Thinking to plan how the loop should work, what the checklist should evaluate, and how the loop count should be tracked in LangGraph state."

---

## Superpowers Plugin

**What it does:** Enables parallel hypothesis investigation by spawning sub-agents. Each sub-agent investigates one hypothesis independently. The main agent synthesizes findings. This produces better analysis than investigating one hypothesis at a time.

**When to invoke:**
- When the Analyzer identifies two or more competing explanations for a significant finding
- When a dataset has distinct subsets (by region, product, time period) that appear to behave differently and parallel analysis would reveal interactions
- When debugging a complex error where multiple causes are plausible and investigating them sequentially would take too long
- When designing the system prompt for an agent and multiple philosophical approaches are viable — spawn sub-agents to evaluate each approach before committing

**How to invoke:** Define each hypothesis or sub-task clearly. Spawn one sub-agent per hypothesis. Each sub-agent investigates independently. Synthesize all findings in the main response.

**What it produces:** Parallel investigation results that are synthesized into a single conclusion with explicit reasoning about which hypothesis the evidence supports.

**Example trigger:** "The Analyzer found that revenue dropped in Q3 AND that a new product was launched in Q3 AND that a key account was lost in Q3. Use Superpowers to investigate all three as potential causes simultaneously."

---

## Memory MCP

**What it does:** Provides persistent memory across agent runs within a session. Every agent reads the memory store at the start of its run and writes its key findings and decisions at the end. This enables cumulative intelligence — no agent starts from scratch.

**When to invoke:**
- At the start of every agent run — read the memory store to get context from all previous agents
- At the end of every agent run — write key findings, decisions, and flags for downstream agents
- When the Explainer is answering a custom question — read memory to get full context of what all previous agents found

**What to write to memory:**
- Profiler: domain hypothesis, confidence score, provenance hypothesis, top 3 concerns, top 3 interesting patterns
- Cleaner: key cleaning decisions made, columns excluded, outliers handled, user decisions incorporated
- Analyzer: most important finding, strong correlations found, anomalies identified, charts generated
- Explainer: questions answered, additional patterns noticed during translation

**How to invoke:** At agent start, read the full memory store. At agent end, write structured key-value entries with the agent name as a prefix (e.g., "profiler.domain_hypothesis", "cleaner.excluded_columns").

---

## Code Review Plugin

**What it does:** Reviews code for correctness, completeness, bugs, and CLAUDE.md compliance. Eliminates silent computational errors before they corrupt analysis results. An analysis system that produces wrong numbers with confidence is worse than no analysis at all.

**When to invoke:**
- After completing any agent file (profiler.py, cleaner.py, analyzer.py, explainer.py)
- After completing any tool file (data_tools.py, viz_tools.py, code_executor.py)
- After completing the orchestrator (orchestrator.py)
- After completing the FastAPI backend (main.py)
- After completing any utility file (supabase_client.py, langsmith_client.py, file_handler.py)
- Before committing any file that contains pandas operations
- Before committing any file that contains statistical computations

**What it checks:**
- Correctness of all computations
- Correctness of all pandas operations
- CLAUDE.md rule compliance
- Type hint completeness
- Error handling completeness
- Hardcoded values
- Missing edge case handling

**How to invoke:** After completing a major feature, type: "Use the code-review plugin to review [filename] for correctness, completeness, CLAUDE.md compliance, and any issues before we commit."

---

## Context7 MCP

**What it does:** Provides up-to-date documentation for any library before implementation. Libraries change, APIs deprecate, and behaviors shift between versions. Using outdated knowledge leads to subtle bugs that are hard to detect. Context7 ensures the implementation matches what the installed version actually does.

**When to invoke:**
- Before implementing any function that uses LangGraph
- Before implementing any function that uses LangSmith
- Before implementing any function that uses the Supabase Python client
- Before implementing any pandas function that has version-specific behavior
- Before implementing any statistical method
- Before using any FastAPI feature that might have version-specific behavior
- Any time you are about to write code for a library and are not 100% certain the API is the same in the installed version

**How to invoke:** "Use Context7 MCP to look up the current documentation for [library name] version [version] — specifically [what you need to know]."

**What to look up:** Not the general library overview. The specific function, method, or pattern you are about to implement. Be precise in the query.

---

## LangSmith Tracing

**What it does:** Traces every agent run with full reasoning transparency. Every tool call, every decision, every output is logged as a named trace. This enables debugging, quality auditing, and understanding of agent reasoning without inspecting code.

**When to invoke:** Every agent run. No exceptions. This is CLAUDE.md Rule 8.

**What to trace:**
- Every call to profiler.py — trace name: "profiler"
- Every call to cleaner.py — trace name: "cleaner"
- Every call to analyzer.py — trace name: "analyzer"
- Every call to explainer.py — trace name: "explainer"
- Every custom question run — trace name: "explainer-question"

**How to invoke:** Import `create_tracer` from `backend/utils/langsmith_client.py`. Pass the returned LangChainTracer as a callback in the LangGraph graph.invoke() call.

**Verification:** Before marking any agent complete, verify the trace is visible in the LangSmith dashboard at smith.langchain.com.

---

## GitHub MCP

**What it does:** Handles git operations — commits, pushes, branch management. Ensures every working state is preserved and every commit message is descriptive.

**When to invoke:**
- After every working, tested, verified feature is complete
- Always before modifying any module that currently works (commit the working state first)
- After every session's final working state

**Commit message format:** Descriptive, specific, past tense. Not "update files" or "fix stuff." Examples:
- "Add LangSmith tracing client with connection validation"
- "Implement Profiler agent with domain hypothesis and provenance detection"
- "Add self-evaluation loop to Analyzer with 5-point checklist"

**How to invoke:** "Commit all current changes to GitHub with the message '[descriptive message]'"

---

## Frontend Design Plugin

**What it does:** Generates production-quality, non-generic UI components. Prevents the default AI aesthetic that makes every tool look the same.

**When to invoke:** Every time a new frontend component is built. Every time a UI element is designed. No component is built without it.

**What it produces:** Component code that looks intentional, professional, and specific to this system — not like a default shadcn/ui template.

**How to invoke:** When building any component, prefix the prompt with "Use the Frontend Design plugin to build [component name]" and describe the specific behavior and aesthetic requirements from `docs/ui-and-frontend.md`.

---

## Security Review Plugin

**What it does:** Scans for security vulnerabilities before deployment. Catches issues that are easy to miss during development — exposed secrets, injection vulnerabilities, improper authentication, insecure defaults.

**When to invoke:** Before any deployment push. This is CLAUDE.md Rule 14.

**What it checks:**
- Hardcoded secrets or API keys
- SQL injection or similar vulnerabilities
- Improper session validation
- Insecure file handling
- Exposed internal error details in API responses
- Missing input validation

**How to invoke:** "Use the Security Review plugin to scan the entire backend for vulnerabilities before deployment."

---

## Supabase MCP

**What it does:** Provides direct database access from Claude Code — read schema, run queries, execute migrations, verify data. Eliminates the need to switch to the Supabase dashboard for database work.

**When to invoke:**
- When verifying that a migration ran correctly
- When reading the current schema to confirm column names and types
- When checking that data was written correctly after an agent run
- When designing a new migration — read the current schema first
- When debugging a database-related error

**How to invoke:** Use natural language queries like "Use the Supabase MCP to read the current schema of the analyses table" or "Use the Supabase MCP to check if the cleaned-datasets storage bucket exists."

**Important:** Never modify the schema directly through the MCP. Read-only use for verification and introspection. All schema changes go through migration files per CLAUDE.md Rule 4.

---

## Brave Search MCP

**What it does:** Searches the web for solutions to errors and problems. Surfaces recent community solutions, bug reports, and workarounds that may not be in training data.

**When to invoke:** When stuck on an error after 2 failed attempts to resolve it. This is the last-resort tool before escalating to the human.

**What to search for:** The exact error message, plus the library name and version. Not a general description — the specific error text.

**How to invoke:** "Use Brave Search MCP to search for '[exact error message] [library name] [version]'"

**After finding a solution:** Document it in `errors.md` immediately — Date | Error | Root cause | Solution.

---

## When to Use Each Plugin During Build

This section maps every build task to the specific plugins that must be activated. Claude Code and any new chat window should treat this as an instinctive routing table — when the task matches, the plugin fires.

### Building any utility file (config.py, supabase_client.py, langsmith_client.py, file_handler.py)

| Step | Plugin |
|------|--------|
| Before implementing any library function | Context7 MCP |
| After file is complete | Code Review Plugin |
| After tests pass | GitHub MCP |

### Building any agent file (profiler.py, cleaner.py, analyzer.py, explainer.py)

| Step | Plugin |
|------|--------|
| Before designing the agent's approach | Sequential Thinking MCP |
| Before implementing any library function | Context7 MCP |
| At start of every agent run (runtime) | Memory MCP — read |
| At end of every agent run (runtime) | Memory MCP — write |
| For every agent run (runtime) | LangSmith Tracing |
| After agent file is complete | Code Review Plugin |
| After tests pass | GitHub MCP |

### Writing any system prompt (profiler_system.md, cleaner_system.md, analyzer_system.md, explainer_system.md)

| Step | Plugin |
|------|--------|
| Before writing | Sequential Thinking MCP |
| Switch model | Opus — all system prompts require Opus |
| For competing philosophical approaches | Superpowers Plugin |
| After writing | Code Review Plugin (review the prompt for CLAUDE.md compliance) |

### Building the orchestrator (orchestrator.py)

| Step | Plugin |
|------|--------|
| Before designing the graph | Sequential Thinking MCP |
| Before implementing LangGraph graph construction | Context7 MCP |
| After orchestrator is complete | Code Review Plugin |
| After tests pass | GitHub MCP |

### Building any tool file (data_tools.py, viz_tools.py, code_executor.py)

| Step | Plugin |
|------|--------|
| Before implementing any pandas or plotting function | Context7 MCP |
| After tool file is complete | Code Review Plugin |
| Before any computed value is presented | Code Review Plugin |
| After tests pass | GitHub MCP |

### Building the FastAPI backend (main.py)

| Step | Plugin |
|------|--------|
| Before implementing any FastAPI feature | Context7 MCP |
| After main.py is complete | Code Review Plugin |
| After tests pass | GitHub MCP |

### Building any frontend component

| Step | Plugin |
|------|--------|
| When building the component | Frontend Design Plugin |
| Before implementing any Next.js or React feature | Context7 MCP |
| After component is complete | Code Review Plugin |
| After tests pass | GitHub MCP |

### Analyzing any complex finding or error during agent runtime

| Step | Plugin |
|------|--------|
| Multiple competing hypotheses | Superpowers Plugin |
| Stuck after 2 failed attempts | Brave Search MCP |
| After solving | Document in errors.md, commit with GitHub MCP |

### Before any deployment

| Step | Plugin |
|------|--------|
| Security scan | Security Review Plugin |
| After scan passes | GitHub MCP |

### Any session start

| Step | Plugin |
|------|--------|
| Always | Read CLAUDE.md, tasks.md, decisions.md, errors.md |
| Load specific docs | Only the docs relevant to today's task |
| Library version check | Context7 MCP if working with any library today |

---

## Plugin Usage Violations

These are CLAUDE.md rule violations. They are not judgment calls:

- Running an agent without LangSmith tracing = Rule 8 violation
- Writing pandas code without Code Review = Rule 13 violation
- Using a library without Context7 check = Rule 12 violation
- Committing without a descriptive message = Rule 15 violation
- Building a UI component without Frontend Design plugin = quality violation
- Deploying without Security Review = Rule 14 violation
- Modifying the Supabase schema via MCP instead of migration = Rule 4 violation
