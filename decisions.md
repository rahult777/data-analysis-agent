# Decisions Log

Append-only. Never edit existing entries. Add new entries at the bottom.
Format: Date | Decision | Reasoning | Alternatives Considered

---

## Project Foundation Decisions

**2026-04-13 | File size limit set to 100MB, not 50MB**
The original CLAUDE.md specified 50MB. Changed to 100MB after reasoning that a CSV with 500,000–1,000,000 rows — a genuinely large real business dataset — typically falls in the 80–150MB range. 50MB was too restrictive for real-world business use. The system's RAM usage at 100MB is well within acceptable bounds for any reasonable server.
Alternatives considered: 50MB (original), 200MB (too permissive for a first version), unlimited (no protection against accidental large uploads).

---

**2026-04-13 | langgraph version changed from 0.1.0 to 0.2.0**
langgraph==0.1.0 does not exist as a published version — pip confirmed this with an error listing available versions which skip from 0.0.x directly to 0.1.1. The closest correct version was 0.2.0.
Alternatives considered: 0.1.1 (too old), 0.2.0 (chosen — stable and compatible).

---

**2026-04-13 | langsmith version changed from 0.1.63 to 0.1.147**
langsmith==0.1.63 caused an irresolvable dependency conflict with langgraph==0.2.0, which requires langsmith>=0.1.112. Pip entered infinite backtracking trying to satisfy both simultaneously. Updated to 0.1.147 which is compatible with langgraph==0.2.0 and all other packages.
Alternatives considered: 0.1.63 (original, caused conflict), 0.1.147 (chosen — resolves conflict, most recent compatible version).

---

**2026-04-13 | supabase version changed from 2.4.0 to 2.28.3**
supabase==2.4.0 had internal dependency conflicts — its sub-packages (gotrue, storage3, supafunc) disagreed on which version of httpx they needed. These conflicts could not be resolved without upgrading supabase itself. 2.28.3 is a self-consistent version where all sub-packages agree on httpx>=0.26,<0.29.
Alternatives considered: 2.4.0 (original, caused conflicts), 2.28.3 (chosen — internally consistent, actively maintained).

---

**2026-04-13 | pip install uses --use-deprecated=legacy-resolver flag during setup**
The new pip dependency resolver entered infinite backtracking due to version conflicts between langsmith, supabase, and their transitive dependencies. The legacy resolver installs packages without this backtracking behavior. The actual packages installed are identical — only the resolution algorithm differs. This flag is a one-time setup decision and does not affect runtime behavior.
Alternatives considered: New resolver (causes infinite backtracking), legacy resolver (chosen — identical packages, no backtracking).

---

**2026-04-13 | Supabase tables created with session_id column for minimal authentication**
Without any authentication, any user who knows an analysis_id could access another user's analysis results. Adding a session_id UUID that is generated on upload and required on all subsequent requests provides a simple, effective first layer of protection without implementing full auth. Full Row Level Security (RLS) will be added before production deployment.
Alternatives considered: No auth (insecure), full JWT auth (too complex for current stage), session_id (chosen — simple, effective, easy to upgrade later).

---

**2026-04-13 | analyses table uses original_filename and stored_filename as separate columns**
If two users upload files with the same name (sales.csv), a single filename column would cause conflicts on disk. stored_filename uses a UUID to guarantee uniqueness. original_filename preserves what the user uploaded so the UI can display it correctly.
Alternatives considered: Single filename column (causes conflicts), UUID only (loses original name for UI display), two columns (chosen).

---

**2026-04-13 | analyses table includes updated_at, file_size, and error_message columns**
updated_at: enables frontend to show "last updated X seconds ago" and helps debug stuck pipelines. file_size: needed to enforce the 100MB limit and display file info in the UI. error_message: without it, pipeline failures are invisible — the frontend needs to know what went wrong and whether it is a user error or system error.
Alternatives considered: Omitting these columns (saves minimal space but loses essential operational data). All three added.

---

**2026-04-14 | Agent file names kept as profiler.py, cleaner.py, analyzer.py, explainer.py. Conceptual names documented in file headers and docs.**
Renaming files to comprehender.py etc. would break every import reference and make the codebase harder to navigate for anyone familiar with standard agent naming conventions. The conceptual names (The Comprehender, The Thoughtful Cleaner, The Deep Investigator, The Translator and Advisor) live in documentation and system prompts — they communicate the agent's intelligence philosophy. The file names are stable, conventional, and importable.
Alternatives considered: Rename files to conceptual names (breaks imports, unconventional), keep file names with conceptual names in docs (chosen).

---

**2026-04-14 | Cleaned dataset persisted to Supabase Storage as parquet, not kept in local memory**
The Analyzer and Explainer both need the cleaned dataset. If it lives only in memory, the pipeline cannot be resumed after a crash. If it lives only in local storage, it cannot be accessed by serverless functions or multiple worker processes. Parquet is compact, fast to read, and preserves dtypes exactly — a cleaned DataFrame round-trips through parquet without any data loss. Supabase Storage provides persistent, accessible cloud storage without requiring a separate service.
Alternatives considered: In-memory only (not resumable), local filesystem only (not scalable), Supabase Storage as parquet (chosen — persistent, accessible, dtype-preserving).

---

**2026-04-14 | pgvector and vector search explicitly removed from the system**
This system does not perform semantic search over analyses or questions. Every query is either a direct database lookup (get analysis by ID) or a pandas computation on a specific dataset. Adding vector search would add complexity, cost, and latency with zero benefit for the current use cases.
Alternatives considered: Add pgvector for semantic question matching (over-engineered for current needs), no vector search (chosen — YAGNI, keep it simple).

---

**2026-04-14 | Domain confidence pause threshold set at 80%**
Below 80% confidence, the Profiler's domain hypothesis is not reliable enough to drive domain-specific cleaning and analysis decisions downstream. At 80% or above, the hypothesis is reliable enough to proceed without interrupting the user. 80% was chosen as the threshold after reasoning that a world-class analyst would seek confirmation when they were less than 80% certain about the domain.
Alternatives considered: 70% (too permissive — allows too much uncertainty), 90% (too strict — would pause too often on clear cases), 80% (chosen — good balance between confidence and flow).

---

**2026-04-14 | Missing value pause threshold set at 30%**
A column with over 30% missing values is a significant data quality issue that changes the meaning and reliability of any analysis involving that column. Below 30%, imputation is a reasonable automated decision. Above 30%, the decision about whether to impute, exclude the column, or exclude the rows has material impact on the analysis — the user must be informed and must choose.
Alternatives considered: 20% (too sensitive — would pause too often on slightly messy data), 50% (too permissive — allows major quality issues to proceed silently), 30% (chosen).

---

**2026-04-14 | Three user types with three simultaneous output layers**
A business owner, a data analyst, and a data scientist all need the same underlying analysis but translated differently. Producing only one output layer means some users get too much jargon or too little depth. Producing separate analyses for each type is too slow. The solution is one analysis, three translation layers produced simultaneously by the Explainer. Users optionally self-identify to prioritize emphasis, but all three layers are always present.
Alternatives considered: Single output for all users (wrong depth for most), separate analyses per type (too slow), three simultaneous layers (chosen).

---

**2026-04-14 | Analyzer self-evaluation checklist has exactly 5 criteria**
The 5 criteria were chosen to cover the complete analytical surface: concerns flagged by the Profiler (a), strong correlations (b), anomaly explanations (c), chart completeness (d), and identification of the most important finding (e). Together these 5 criteria guarantee that no significant analytical gap can pass the self-evaluation loop. More criteria would create redundancy. Fewer would leave gaps.
Alternatives considered: 3 criteria (too few — leaves gaps), 7 criteria (redundant), 5 criteria (chosen — complete coverage without redundancy).

---

**2026-04-14 | USER_ERROR and SYSTEM_ERROR prefixes on error_message column**
The frontend needs to display different UI (yellow warning vs. red error) and different messaging (actionable fix vs. generic failure) depending on whether the error is something the user can fix or something that is a system failure. Prefixing the error message with USER_ERROR: or SYSTEM_ERROR: allows the frontend to make this distinction without a separate error_type column.
Alternatives considered: Separate error_type column (more schema changes), HTTP status codes only (insufficient for nuance), error message prefix (chosen — simple, self-contained, no schema changes needed).

---

**2026-04-14 | Charts served via FastAPI StaticFiles mount at /charts/{filename}**
Charts are generated as files on disk. The frontend needs to display them. Two options: encode them as base64 in the JSON response (bloats the API response), or serve them as static files (clean, standard, cacheable). StaticFiles mount at /charts/ is the standard FastAPI pattern for serving local files over HTTP.
Alternatives considered: Base64 in JSON (bloats responses), separate static file server (unnecessary complexity), FastAPI StaticFiles (chosen — simple, standard, cacheable).

---

**2026-04-14 | Frontend polls status endpoint every 3 seconds**
The pipeline takes 30–120 seconds depending on dataset size. Polling too frequently wastes bandwidth and API calls. Polling too infrequently makes the progress feel laggy. 3 seconds gives a responsive feel (the user sees the agent change within 3 seconds of it actually changing) without excessive server load.
Alternatives considered: WebSockets (more complex, overkill for this use case), 1 second polling (too frequent), 5 second polling (feels laggy), 3 second polling (chosen).

---

**2026-04-15 | 26 pydantic schemas organized in three layers: leaf models, mid-tier models, API layer models**
Complex nested schemas are easier to reason about and maintain when they are built from smaller, single-purpose models. Leaf models have no dependencies on other custom schemas. Mid-tier models compose leaf models into agent outputs. API layer models compose everything into endpoint shapes. This layering mirrors how the data actually flows through the system.
Alternatives considered: Flat schema structure (hard to maintain, lots of repetition), deeply nested schemas (hard to read and debug), three-layer structure (chosen).

---

**2026-04-15 | All pydantic models use ConfigDict(from_attributes=True)**
Supabase returns data as objects with attributes, not as plain dictionaries. Without from_attributes=True, constructing pydantic models from Supabase responses requires manual dictionary conversion. With it, models can be constructed directly from response objects, reducing boilerplate throughout the codebase.
Alternatives considered: Manual dict conversion everywhere (verbose, error-prone), from_attributes=True on all models (chosen — clean, consistent).

---

**2026-04-15 | ExecutiveSummary enforces exactly 5 bullet points at the schema layer**
The intelligence philosophy specifies 5 bullets maximum for the Executive layer. Enforcing this in the pydantic schema (Field(min_length=5, max_length=5)) means the Explainer cannot accidentally produce 4 or 6 bullets even if the system prompt is imperfect. The constraint is architectural, not just instructional.
Alternatives considered: Enforce only in system prompt (can be violated), enforce in schema (chosen — architectural guarantee).

---

**2026-04-16 | CLAUDE.md restructured into lean spine plus 9 dedicated docs under docs/**
The original CLAUDE.md was ~9,000 tokens loaded on every Claude Code session start, including content irrelevant to most sessions. The restructure separates always-needed rules (spine, ~1,500 tokens) from task-specific deep content (docs/, loaded on demand). Estimated savings: ~7,100 tokens per session. All intelligence preserved — only the loading strategy changed.
Alternatives considered: Keep monolithic CLAUDE.md (continues burning tokens), split into spine + docs (chosen — significant token savings, all intelligence preserved).

---

**2026-04-16 | .claudeignore created to prevent Claude Code from scanning venv/, __pycache__/, charts/, fixtures/, *.parquet**
Without .claudeignore, Claude Code scans everything in the project folder including the venv virtual environment (thousands of package files), Python cache files, generated chart images, test CSV fixtures, and any parquet files that land locally during development. None of these are relevant to any build task. Ignoring them reduces token consumption on every session start.
Alternatives considered: No ignore file (continues scanning noise), .claudeignore with the listed entries (chosen).

---

**2026-04-16 | Supabase MCP reconfigured from --supabase-url + --supabase-key to --access-token with Personal Access Token**
The @supabase/mcp-server-supabase package updated its CLI interface. The old flags (--supabase-url and --supabase-key) were deprecated and removed. The new interface requires a Personal Access Token passed via --access-token. Regenerated a PAT with no expiration for development use.
Alternatives considered: Downgrade the MCP package (introduces version lag), update to new interface (chosen — uses current supported API).

---

**2026-04-17 | Model switching strategy: Sonnet 4.6 with high effort for infrastructure, Opus for system prompts**
Sonnet 4.6 with high effort is fast, capable, and token-efficient for code generation tasks. Opus is slower and costs more tokens but produces significantly deeper reasoning — worth it only for the system prompts which are the intelligence of the entire system. Switching to Opus for every task would consume the session limit too quickly.
Alternatives considered: Opus for everything (too slow, too costly), Sonnet for everything (insufficient depth for system prompts), task-based switching (chosen).
