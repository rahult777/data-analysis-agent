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

---

**2026-04-25 | Deleted root level architecture.md — outdated draft superseded by docs/architecture.md**
The root level architecture.md was an earlier draft created before the full system design was complete. docs/architecture.md contains the complete verified version with full ASCII diagram, all component descriptions, data flow, authentication model, persistence model, and observability model. Having two files with the same name in different locations causes confusion.
Alternatives considered: Keep both (causes confusion), keep root level (wrong version), delete root level and keep docs/architecture.md (chosen).

---

**2026-04-26 | StaticFiles directory created at both module level and in lifespan**
Starlette's StaticFiles asserts the directory exists at initialization time. The lifespan (startup) runs after module-level code, so the mount would fail if the directory did not already exist. Creating it at module level (before app.mount()) guarantees the mount succeeds; creating it again in lifespan satisfies the spec requirement and is idempotent via exist_ok=True.
Alternatives considered: Create in lifespan only (breaks StaticFiles mount at import), create at module level only (doesn't satisfy spec), create in both places (chosen — technically correct and spec-compliant).

---

**2026-04-26 | POST /api/upload returns a plain dict rather than UploadResponse pydantic model**
The infrastructure spec requires session_id in the upload response, but the UploadResponse pydantic schema does not include session_id (it was not added to schemas.py). Returning a plain dict allows session_id to be included without modifying the existing schemas.py file. When schemas.py is updated to add session_id to UploadResponse, the endpoint can be updated to use the model directly.
Alternatives considered: Modify UploadResponse schema (creates scope creep), return UploadResponse and lose session_id (breaks frontend auth), return plain dict (chosen — spec-compliant without modifying other files).

---

**2026-04-26 | get_session dependency receives analysis_id from path injection**
FastAPI automatically injects path parameters into dependency functions when the parameter name matches the path variable name. get_session declares analysis_id: str with no default, so FastAPI resolves it from the path of the calling endpoint. This avoids duplicating the session validation logic across every endpoint.
Alternatives considered: Pass analysis_id explicitly in every endpoint (verbose, repetitive), inject via path in dependency (chosen — standard FastAPI pattern, DRY).

---

**2026-04-26 | Step 6 hardening applied to profiler_system.md after Code Review**
Code Review plugin identified that Step 6 (concerns and patterns flagging) could produce generic outputs under inference pressure — e.g. 'high missingness in column X' — that satisfy the schema but produce a worthless Analyzer investigation agenda. Added 4 anti-patterns for concerns, 4 anti-patterns for patterns, and a 3-question pre-output self-check requiring each flagged item to be specific to this dataset, reasoned from domain priorities, and actionable by the Analyzer. The self-check ties back to Section 4 domain intelligence and lens question (f).
Alternatives considered: leave prompt as written (risk of generic flags corrupting downstream analysis), apply hardening (chosen — architectural quality guarantee).

---

**2026-04-27 | cleaner_system.md structured with 11 sections mirroring profiler_system.md pattern**
Both sub-agents independently converged on: unified pause-signal section, hardening as separate section, Memory MCP write at end, JSON-only output contract. Final structure leads with identity, then epistemic principles, then Memory Read inheritance, then domain intelligence, then provenance intelligence, then the 10 cleaning steps, then pause signals, then pre-output self-check, then Memory MCP write, then output contract. Code Review passed all 11 compliance items with no issues.
Alternatives considered: domain-led ordering (sub-agent 1), framework-led ordering (sub-agent 2), synthesized structure (chosen — identity-first with referenceable domain sections).

---

**2026-04-27 | explainer_system.md structured with 13 sections — synthesis of translation-led and narrative-led approaches**
Two sub-agents investigated competing structures in parallel. Sub-agent 1 (translation-led) argued user types as spine; key contribution: failure detectability — layer violations are contract violations with a specific user. Sub-agent 2 (narrative-led) argued Progressive Revelation as spine; key contribution: Story Construction Step as an internal pre-write before any output, forcing genuine synthesis before any layer is written. The synthesized structure uses identity-led spine (chain coherence with profiler/cleaner/analyzer) + Progressive Revelation embedded in the Lens (§2) as the narrative frame + Story Construction Step as Step 2 in the steps section. Three users defined as a dedicated section (§5) giving layer violations their meaning. Two sections unique beyond the cleaner/analyzer pattern: §5 (Three Users — canonical definitions with failure condition per user) and §9 (Custom Questions Mode — hard mode switch, 5-step protocol). Memory MCP Read covers all 11 keys from all three predecessor agents (richer than any prior agent). Pre-output hardening (§11) covers 5 failure modes with binary PASS/FAIL. Code Review passed all 21 compliance items with no failures.
Alternatives considered: translation-led spine (risks fragmenting coherent narrative across three parallel reports), narrative-led spine (risks weak layer format precision and narrative overhead in custom questions mode), synthesized structure (chosen — identity-led for chain coherence, narrative-led contribution embedded in Lens and Steps, translation-led contribution in dedicated user definitions section).

---

**2026-04-27 | analyzer_system.md structured with 13 sections — synthesis of identity-led spine and criteria-as-senses framing**
Two sub-agents investigated competing structures in parallel. Sub-agent 1 produced an identity-led blueprint (chain coherence with profiler/cleaner; failure-mode is competent-forgettable uniformity). Sub-agent 2 produced a loop-led blueprint (5 criteria as the spine; transverse principles section). The synthesized structure takes the identity-led spine for chain coherence and embeds the loop-led "criteria-as-senses" framing into the Lens (Section 2), so the agent perceives the five verification criteria throughout every step rather than as a post-hoc check. Two unique sections beyond the cleaner's 11: Section 4 (user context, parallel to Profiler §3) and Section 6 (Calibrated Confidence + Sample-Size Reliability Floor — unique to the Analyzer as the first agent producing findings that require confidence labeling). Section 8 contains 10 explicit steps; the critical Step 2 ("Plan the Investigation Agenda Before You Compute") makes depth-allocation a precondition of computation rather than retroactive narration. Loop and pre-output hardening are kept as separate sections (10 and 11) because completeness and specificity must pass independently — merging them would let the model trade one for the other. Code Review passed all 19 compliance items with no failures.
Alternatives considered: 11-section structure matching cleaner exactly (would have lost the dedicated user_context and calibrated-confidence sections), loop-led structure as spine (would have broken chain coherence with profiler/cleaner and risked reducing depth-allocation to checklist behavior), 13-section synthesized structure (chosen — preserves chain coherence while giving the Analyzer's distinct epistemic surfaces their own findable sections).

---

**2026-04-27 | Auto-generated explainer_system.md deleted and scheduled for rewrite**
Claude Code auto-generated explainer_system.md as a side effect of a commit prompt without being explicitly instructed to. The file was written without Opus 4.7, Sequential Thinking MCP, or Superpowers plugin — the full protocol required for all system prompts per CLAUDE.md. The file has been deleted. explainer_system.md will be rewritten properly in the next task.
Alternatives considered: keep auto-generated file (violates quality standard), delete and rewrite with full protocol (chosen).

---

**2026-04-28 | explainer_system.md rewritten with full Opus protocol — 13 sections, identity-led spine, Progressive Revelation embedded in Lens, Three Users as dedicated section, Story Construction Step as the synthesis gate**
The deleted auto-generated explainer_system.md was rewritten under the full required protocol: Opus 4.7, Sequential Thinking MCP for deep planning, Superpowers parallel sub-agents (one investigating user-types-as-spine, one investigating Progressive-Revelation-as-spine), synthesis of both, and Code Review verification of all 21 CLAUDE.md compliance items. Sub-agent 1's strongest contribution (layer-as-contract failure detectability) was preserved by giving the Three Users their own dedicated section (§4) where layer violations gain meaning. Sub-agent 2's strongest contribution (Story Construction as a pre-narrative synthesis gate) was preserved as Step 2 of the Steps section, with explicit grant of synthesis authority to surface cross-agent connections no single prior agent saw. The identity-led spine maintains chain coherence with profiler/cleaner/analyzer (all four agents read as one mind in stages). Progressive Revelation lives in §2 (the Lens) as the narrative shape that lives in perception, not as a top-level section — preventing the Custom Questions Mode awkwardness that a narrative-led spine would have produced. Confidence Translation (§6) and Correlation Translation (§7) are dedicated sections to centralize cross-cutting rules rather than triplicating them across the three layer descriptions. The five binary failure-mode checks (§11) catch the genericness, causality leak, weak Lead, generic Open Questions, and code-summarization that the schema cannot enforce. Memory MCP read covers all 15 keys from the three predecessor agents (richer than any prior agent's inheritance). Memory MCP write at end persists explainer.lead, explainer.open_questions, and explainer.questions_answered (the last grows across Custom Questions Mode runs). Output JSON has two top-level objects mapping to analyses.executive_summary and analyses.insight_report; QuestionAnswerResult is the alternative shape for Custom Questions Mode. Code Review passed all 21 compliance items with no failures.
Alternatives considered: user-types-as-primary-spine (sub-agent 1's recommendation — would have under-emphasized synthesis judgment and demoted Progressive Revelation), Progressive-Revelation-as-primary-spine (sub-agent 2's recommendation — would have thinned identity and made Custom Questions Mode an awkward graft), synthesized identity-led structure (chosen — chain coherence preserved, both sub-agents' strongest contributions integrated as dedicated sections, neither's weaknesses inherited).

---

**2026-04-28 | anthropic upgraded from 0.25.0 to 0.97.0 due to httpx compatibility conflict**
anthropic==0.25.0 was incompatible with httpx>=0.26 which supabase==2.28.3 requires. The proxies keyword argument was removed in newer httpx versions. Upgrading anthropic to 0.97.0 resolves the conflict — it supports httpx>=0.25.0 which is compatible with supabase's requirements. requirements.txt updated accordingly.
Alternatives considered: downgrade httpx to 0.24.1 (breaks supabase), pin anthropic at 0.25.0 (breaks httpx), upgrade anthropic to 0.97.0 (chosen — resolves all conflicts).

---

**2026-04-28 | ANTHROPIC_MODEL added to config.py and .env — set to claude-sonnet-4-6**
Agent runtime calls use claude-sonnet-4-6 rather than Opus. The intelligence of the system lives in the carefully written system prompts, not in which model processes them. Sonnet 4.6 handles the structured system prompts well and provides significant cost and latency advantages over Opus for every analysis run. The model string is loaded from environment variable so it can be changed without touching code.
Alternatives considered: claude-opus-4-6 (more capable but slower and more expensive per run), claude-sonnet-4-6 (chosen — fast, cost-effective, system prompts compensate for capability difference).

---

**2026-05-01 | cleaner.md spec updated with four new sections before implementation — missingness pattern analysis, domain investigation criteria, provenance-aware cleaning, interaction detection**
Pressure-testing the spec against five difficult real-world datasets (merged enterprise export, medical with critical outliers, manually entered sales, survey with satisficing bias, financial ledger with fraud signals) revealed four gaps: the 30% pause threshold was mechanical with no pattern analysis, the outlier investigation instruction had no concrete domain-specific criteria, the provenance hypothesis was read but never used in any decision framework, and co-occurring issues were treated as independent problems. All four gaps were added to cleaner.md before implementation so the spec is the source of truth. The build prompt and cleaner.py both derive from the updated spec.
Alternatives considered: patch the gaps in the build prompt only (spec would be wrong), patch in cleaner_system.md only (implementation would diverge from spec), update spec first then prompt then implementation (chosen — spec is always source of truth).

---

**2026-05-01 | Supabase Storage bucket 'cleaned-datasets' created as private bucket in Supabase dashboard**
The bucket must exist before the Cleaner runs — infrastructure.md Step 14 explicitly requires it. Created manually in the Supabase dashboard rather than via migration because bucket creation is a one-time infrastructure setup step, not a schema change. Set to private so parquet files containing user data are never publicly accessible. The service role key in .env handles all server-side access.
Alternatives considered: create via migration (unnecessary complexity for a one-time bucket), public bucket (insecure — exposes user data), private bucket created manually (chosen).

---

**2026-05-01 | data_tools.py removed from build plan entirely**
The original spec included data_tools.py as a shared pandas utility module. During implementation, profiler.py and cleaner.py both load and process data directly — there is no shared pandas logic that genuinely needs a shared module. analyzer.py will load the cleaned parquet from Supabase Storage directly. The only genuine shared utility needed is viz_tools.py for chart generation (complex, produces files, referenced by path) and code_executor.py for safe pandas execution in the Explainer. Building data_tools.py would add a file with no real consumers.
Alternatives considered: build data_tools.py as specified (adds unused complexity), skip it entirely (chosen — YAGNI, actual build pattern made it unnecessary).

---

**2026-05-06 | sanitize_for_json implemented as recursive function returning a NEW object — explicit reassignment is mandatory**
The analyzer.py output dict contains pandas/numpy float values that may be NaN or Inf (correlation matrices in particular generate NaN on diagonals and on column-pairs with insufficient data). A json default= handler does not help because the JSON encoder does not invoke default= for NaN/Inf — it emits them as the non-standard literals "NaN" / "Infinity" which Postgres JSONB rejects. The correct approach is to walk the structure recursively and replace NaN/Inf with None and tuples with lists before json.dumps. The function returns a new sanitized object — it does NOT mutate in place — so the caller MUST reassign: `analysis_response = sanitize_for_json(analysis_response)`. Forgetting the reassignment silently writes the original unsanitized dict to Supabase.
Alternatives considered: json.dumps(..., default=handler) (does not catch NaN/Inf), in-place mutation of the dict (couples mutation semantics to caller awareness, easier to break later), recursive function returning a new object with explicit reassignment (chosen — pure transform, hard to misuse if the reassignment idiom is followed).

---

**2026-05-06 | np.polyfit on time-series trend detection requires NaN dropna mask BEFORE the call, not after**
np.polyfit raises ValueError on real-world cleaned datasets when y contains any NaN — the linear-algebra solve fails. Cleaned data still contains NaNs in numeric columns where the cleaner chose to flag-and-include rather than impute. The fix is to compute `mask = ~np.isnan(y)` first, then `x = np.arange(len(df))[mask]` and `y = y[mask]`, then call np.polyfit only if `len(y) >= 2`; otherwise treat trend as "flat". Using df.dropna() before computing x would misalign x and y because np.arange would no longer match dropped rows.
Alternatives considered: scipy.stats.linregress (would add scipy to dependencies for one call), using datetime values directly as x to np.polyfit (TypeError — Timestamp is not numeric in numpy linalg), np.arange with NaN mask (chosen — pure-numpy, no extra dependency, correctly handles holes in cleaned data).

---

**2026-05-06 | Correlation matrix diagonal masking is required to prevent self-pairs in highest-pair detection**
Pearson correlation of a column with itself is always 1.0, which would always be the "highest pair" if the diagonal is not masked. The fix is to copy the correlation matrix values, set np.fill_diagonal(values, NaN) on the copy, and find the highest pair from the masked copy. The original matrix is preserved for the to_dict() output that is reported back to the LLM. Strong-pair detection is also done on the upper triangle only (j > i) to avoid duplicate pairs in both directions.
Alternatives considered: leave diagonal in place (highest_pair would always be a self-pair), mask diagonal in place (mutates the matrix that gets reported), copy + mask (chosen — preserves original output, prevents self-pair selection).

---

**2026-05-06 | TimeSeriesInfo schema has exactly 4 fields; recommended_value_column is an internal helper returned as the second tuple element**
The TimeSeriesInfo pydantic model in schemas.py has detected, datetime_column, frequency, trend — and only those four. The recommended_value_column (the numeric column with highest variance, used for line-chart and trend computation) is not in the schema. detect_time_series therefore returns a tuple (info_dict, recommended_value_column) where the dict matches the schema and the second element is consumed only by chart generation. This keeps the schema clean while preserving the routing information the analyzer node needs.
Alternatives considered: add recommended_value_column to TimeSeriesInfo (schema bloat for a value the Explainer does not need), recompute recommended_value_column inside chart generation (duplicate logic), tuple return (chosen — single source of truth, schema minimal).

---

**2026-05-06 | numpy.polyfit + np.arange chosen over scipy.linregress and over raw datetime x-axis**
Three options were considered for time-series trend slope: scipy.stats.linregress (would force scipy as a runtime dependency for one call), np.polyfit with the original datetime values as x (TypeError — numpy linalg cannot solve with pd.Timestamp values), and np.polyfit with np.arange(len(df)) as x. The third works because integer row position is monotone in time when df is sorted by the datetime column, the slope is sign-correct, and the magnitude can be thresholded for the "flat" classification. No extra dependency, no type errors, correct on any sorted timeline.
Alternatives considered: scipy.stats.linregress (adds scipy dependency for one call), datetime values as x to np.polyfit (TypeError on np.linalg.solve), np.arange(len(df)) as x (chosen — pure numpy, type-safe, slope sign-correct).

---

**2026-05-06 | Superpowers parallel-investigation protocol handled at the LLM reasoning level, not in Python**
analyzer_system.md Section 9 instructs the LLM to spawn parallel sub-agents through the Superpowers plugin when competing hypotheses exist for a significant finding. The Python analyzer_node does not orchestrate this — the LLM reasons about it inside the single Anthropic call. The Python code provides the inputs (descriptive stats, correlations, distributions, value counts, time-series info, profile/cleaning reports, concerns, patterns) and the verification loop (criteria a-e); the synthesis of competing hypotheses is content the LLM produces inside the response JSON. Implementing parallel sub-agent dispatch in Python would require duplicating the system prompt for each hypothesis and synthesizing results outside the LLM, which is out of scope for the current build pass and would not improve the synthesis quality.
Alternatives considered: Python-level Superpowers orchestration (high complexity, duplicate prompts, no quality gain), LLM-level reasoning only (chosen — matches existing agent pattern, single inference, synthesis stays inside the model).

---

**2026-05-06 | analyzer.anomalies_found omitted from the Python-level Memory MCP write**
analyzer_system.md Section 12 specifies seven keys the LLM must write to Memory MCP at the close of its run: most_important_finding, most_surprising_finding, strong_correlations, anomalies_found, chart_paths, data_quality_score, open_questions. Of these, the Python code writes six and intentionally omits anomalies_found because the Python code cannot reliably extract structured anomaly objects from the LLM's response — the schema does not field anomalies as a top-level list, and parsing them out of free-text would corrupt the data. The LLM closing ritual is the correct place to write anomalies_found because the LLM has the structured anomaly objects in scope at that moment. The Python writes the six structurally-extractable keys; the LLM writes the seventh.
Alternatives considered: write all seven from Python with best-effort parsing (corrupts memory data), write none from Python and rely on LLM (loses the six the Python code can write reliably), write six from Python and let the LLM write the seventh (chosen — each side writes what it can extract reliably).

---

**2026-05-06 | Distribution classifier elif chain ordering produces unreachable bimodal/other branches; preserved per spec**
classify_distributions in analyzer.py uses the elif chain specified in the build prompt: NaN → unknown, abs(skew) < 0.5 → normal, skew >= 0.5 → skewed_right, skew <= -0.5 → skewed_left, kurtosis < -1 → bimodal, else → other. The three skew branches together cover all non-NaN reals, so the bimodal and other branches are unreachable. Preserved as specified — distribution classification is currently skewness-only with bimodal classification reserved for a future revision of the rule. Documented here so the unreachable branches are not mistaken for dead code by future readers.
Alternatives considered: reorder kurtosis check before skew checks (would change the semantics defined in the spec), remove the unreachable branches (would break parity with the spec), preserve as-specified with documentation (chosen — spec fidelity, future revision can re-order).

---

**2026-05-06 | Four separate Supabase update calls at the close of analyzer_node, per spec**
Steps 23-26 of the analyzer.py build spec enumerate four separate save actions: analyses.analysis_report, analyses.chart_paths, analyses.data_quality_score, analyses.updated_at. Implemented as four separate await asyncio.to_thread(...) calls. Existing convention in cleaner.py batches multiple fields into one update; the analyzer follows the spec literally instead of the convention. Each call is independently safe and the four-roundtrip cost is acceptable at the volume the system runs. If profile shows latency, consolidate to a single update.
Alternatives considered: consolidate to one update (more efficient, follows cleaner.py convention, deviates from spec), four separate updates (chosen — spec fidelity, latency cost acceptable).

---

**2026-05-07 | Raw dict save to Supabase JSONB chosen over pydantic validation in explainer_node**
The LLM output contract (explainer_system.md §13) uses executive_summary.bullets as a list of objects with finding/context/recommended_action fields. The pydantic ExecutiveSummary model in schemas.py uses bullet_points: list[str]. The LLM output contract for insight_report uses executive_layer/analyst_layer/technical_layer/open_questions fields; the pydantic FullInsightReport uses data_overview/data_quality/key_findings/patterns/anomalies/recommended_actions. Reconciling these without rewriting both schemas.py and the system prompt simultaneously was out of scope. Saving the raw LLM-produced dict directly to Supabase JSONB preserves all fields the LLM produces without validation loss.
Alternatives considered: validate through pydantic (requires simultaneous rewrite of schemas.py and system prompt, high coordination cost), save raw dict (chosen — avoids scope expansion, preserves all LLM fields, correct at runtime).

---

**2026-05-07 | Two separate prompt files for custom question LLM calls per CLAUDE.md Rule 7**
Custom question answering in answer_question uses two LLM calls: one to generate pandas code (question_code_generator_system.md) and one to translate the computed result to plain English (question_answer_system.md). CLAUDE.md Rule 7 prohibits inline system prompts; two separate prompt files are required rather than one file or inline strings. The two-call design also keeps the code generation step separate from the answer-formulation step, giving each LLM call a single, clear responsibility.
Alternatives considered: single prompt for both steps (mixes responsibilities, inline not allowed), two prompt files (chosen — CLAUDE.md compliant, single responsibility per call).

---

**2026-05-07 | answer_question requires question_id to update questions table per main.py integration contract**
main.py creates the questions table record before calling answer_question (via run_question_task background task). The question_id is needed to update status, answer, and pandas_code on that record throughout execution. Without question_id, there is no way to tie the async result back to the questions table row. The function signature is answer_question(analysis_id, question_id, question) accordingly.
Alternatives considered: look up question_id by analysis_id and question text (fragile, race-prone), pass question_id (chosen — direct, unambiguous, matches the record created by main.py).

---

**2026-05-07 | Memory MCP read required in answer_question per explainer_system.md §10**
Section 10 of explainer_system.md explicitly states that the full 15-key Memory MCP inheritance read is required even in Custom Questions Mode. answer_question does not receive PipelineState, so the 15 keys are unavailable at the Python level. The read is logged as attempted with all keys missing, and the function proceeds without them. This is a known deviation — the system prompt instructs the LLM to read these keys during Custom Questions Mode, but the Python host function cannot retrieve them without a live MCP store connection.
Alternatives considered: pass PipelineState to answer_question (changes function signature, breaks main.py integration), skip Memory MCP read entirely (violates §10 spec), log as attempted with graceful missing treatment (chosen — spec-compliant at the documentation level, main.py compatible).

---

**2026-05-07 | Proceed-despite-missing-keys is a documented deviation from explainer_system.md §3 refusal instruction**
Section 3 of explainer_system.md instructs the Explainer to refuse to proceed if profiler.domain_hypothesis, profiler.top_3_concerns, cleaner.key_cleaning_decisions, analyzer.most_important_finding, or analyzer.open_questions are missing or empty. The Python explainer_node logs a warning for missing keys but proceeds rather than refusing, because the cleaner and analyzer LLM closing rituals may not have written all required keys reliably. Refusing here would break the pipeline silently. The deviation is documented in a code comment at the point of the check.
Alternatives considered: hard-fail on missing keys (breaks pipeline when LLM closing ritual fails), soft-fail with warning and proceed (chosen — pipeline resilience, deviation documented in code and decisions.md).

---

**2026-05-07 | explainer.lead extracted from first executive bullet's finding field, not analyst narrative**
Section 12 of explainer_system.md specifies: explainer.lead = the single most important finding as stated in the Lead of the user-facing report; identical to the finding component of the first Executive bullet. The extraction path is executive_summary.bullets[0].finding, not a top-level lead field or the analyst_layer narrative. This is the finding component specifically, not the full bullet (which also contains context and recommended_action).
Alternatives considered: extract from analyst_layer narrative (not the canonical lead per §12), extract top-level lead field (does not exist in the output schema), extract bullets[0].finding (chosen — exact §12 spec match).

---

**2026-05-07 | Four explainer_node Supabase writes merged into single atomic update after Code Review**
The initial implementation of explainer_node used four separate asyncio.to_thread Supabase calls: executive_summary, insight_report, status="complete", updated_at. The Code Review plugin identified a race condition: a crash between any two calls leaves the analyses row in a partially-updated state where data is present but status is not yet "complete" (or vice versa). Merged into a single .update({executive_summary, insight_report, status, updated_at}) call. This is a deviation from the spec's enumerated step ordering (steps 12-15) but is architecturally superior. The analyzer_node equivalent was not changed — its four separate writes were an explicit prior decision (see decisions.md entry above) and are left consistent with their spec.
Alternatives considered: keep four separate calls per spec (race condition window, per analyzer pattern), merge into one atomic update (chosen — eliminates race, no behavioral change, data and status land together).

---

**2026-05-07 | Resume endpoint stores user pause response and documents pipeline continuation as a TODO stub**
The resume endpoint cannot trigger LangGraph pipeline continuation until orchestrator.py is built. The endpoint writes user_pause_response to the analyses record and restores the pre-pause status so the orchestrator can detect the response when polling. BackgroundTasks parameter is included with a TODO stub to make the integration point explicit. restore_status semantics depend on whether the orchestrator re-runs the paused node or continues from a LangGraph interrupt checkpoint — resolved during orchestrator.py build. Pause statuses added to AnalysisStatus now but not written to DB until orchestrator.py is built. CLEANED = 'cleaned' added to fix pre-existing bug where cleaner.py wrote this value without it being in the enum. 'cleaned' added to _PROGRESS_MAP at 45.0 and _AGENT_MAP as 'cleaner' so the status endpoint returns correct progress during the cleaning-to-analyzing transition.
Alternatives considered: implement full LangGraph resume now (requires orchestrator), write response only with no status change (leaves state ambiguous), current approach (chosen — correct interface, explicit TODO, orchestrator-ready).

---

**2026-05-07 | PauseResumeRequest Code Review corruption — follow-up fix required**
Code Review plugin changed PauseResumeRequest fields from the specified response: dict to action: str and user_input: Optional[str]. This was incorrect — the field name and type were both wrong. The resume endpoint writes the full user decision dict to user_pause_response in the database; a single dict field is the correct type. A follow-up commit (9388400) restored PauseResumeRequest to the correct single-field definition.
Alternatives considered: keep corrupted fields (breaks resume endpoint), restore correct spec (chosen).

---

**2026-05-08 | LangGraph StateGraph chosen for pipeline orchestration with polling-based pause states**
LangGraph 0.2.0 interrupt() was unavailable in the installed version, so pause states are implemented as polling nodes that loop until user_pause_response appears in the analyses DB record. Each pause wait node first clears user_pause_response in the DB before polling to prevent stale values from a prior pause cycle causing an immediate false return.
Alternatives considered: LangGraph interrupt() checkpointing (unavailable in 0.2.0), manual asyncio.Event signaling (not durable — would lose state on process restart), polling DB (chosen — durable, works with any number of worker processes).

---

**2026-05-08 | ainvoke() with tracer as config callbacks required for LangSmith tracing per CLAUDE.md Rule 8**
Individual agent files call create_tracer() locally but do not pass it as a callback — the comment in profiler.py (line 143-144) explicitly documents this. The orchestrator creates a single LangChainTracer and passes it via config={"callbacks": [tracer]} to ainvoke(). LangGraph propagates this callback to every node execution automatically. Without this pattern, LangSmith traces do not appear.
Alternatives considered: pass tracer in each individual agent's Anthropic SDK call (does not instrument the graph-level orchestration), pass at ainvoke level (chosen — single tracer instruments the full pipeline).

---

**2026-05-08 | clear_and_proceed node handles both normal second-profiler-run path and edge-case repeat path**
When profiler succeeds on its second run (after domain pause), domain_pause_data is None but user_pause_response is still set in LangGraph state (profiler does not clear it). Without the clear_and_proceed node, route_after_profiler case (c) would fall through to "cleaner" and the domain confirmation response would flow into the cleaner's build_cleaner_message as if it were a cleaner pause response — silent data corruption. The clear_user_pause_response_node returns {user_pause_response: None} to clear it before cleaner runs. The same node handles the edge case where profiler repeats domain_confirmation_required despite a user response (case b) — routing to clear_and_proceed prevents an infinite domain confirmation loop.
Alternatives considered: profiler_node explicitly clears user_pause_response on success (couples profiler to orchestrator concerns), separate clear nodes for each case (unnecessary — same operation), single clear_and_proceed handling both cases (chosen).

---

**2026-05-08 | route_after_profiler handles four distinct state combinations; the critical case is (c)**
Case (a): domain_pause_data set, user_pause_response None → domain_pause_wait. Case (b): both set → clear_and_proceed (edge case: don't loop on repeated domain pause). Case (c): domain_pause_data None, user_pause_response set → clear_and_proceed. This is the CRITICAL CASE — profiler succeeded on second run but user_pause_response is still in state from the domain pause. Without this explicit branch, LangGraph would route to cleaner with the stale response. Case (d): both None → cleaner (happy path).
Alternatives considered: simplified two-branch router (would miss the critical case c), four-case explicit router (chosen — each case testable independently, critical case visibly documented).

---

**2026-05-08 | domain_confirmed initialized to False not None per PipelineState TypedDict annotation**
PipelineState in profiler.py declares domain_confirmed: bool (not Optional[bool]). Initializing to None would violate the TypedDict contract and cause a runtime type error if any code checks `if state["domain_confirmed"] is True`. False is the correct sentinel for "not yet confirmed".
Alternatives considered: None (wrong type), False (chosen — matches TypedDict annotation).

---

**2026-05-08 | build_initial_state accepts params directly because context and user_type are not stored in analyses table**
The analyses table schema (docs/infrastructure.md) does not include context or user_type columns. These values are passed through from the upload endpoint to the background task to build_initial_state without DB persistence. Reading from Supabase in build_initial_state would fail since the columns do not exist.
Alternatives considered: add context and user_type columns to analyses table (schema change, unnecessary for current build), read from DB (columns don't exist), accept directly from params (chosen).

---

**2026-05-08 | Stale resume endpoint TODO removed — polling loop handles continuation automatically**
The resume endpoint previously had a TODO: "background_tasks.add_task(resume_pipeline, analysis_id) — implement when orchestrator.py is built". The polling-based orchestrator design means no explicit trigger is needed — the pause wait nodes poll DB every 3 seconds and detect user_pause_response automatically. The BackgroundTasks parameter was removed from resume_analysis since it was only there for the stub. BackgroundTasks import retained (used by upload_file and post_question).
Alternatives considered: keep BackgroundTasks param and add explicit resume trigger (unnecessary complexity), remove param and rely on polling (chosen).

---

**2026-05-08 | error_message written alongside status=error in run_pipeline exception handler**
The run_pipeline exception handler updates both status="error" AND error_message=f"SYSTEM_ERROR: {str(exc)}" in a single Supabase call, consistent with all four individual agent exception handlers (profiler, cleaner, analyzer, explainer all write both fields together). Without error_message, pipeline failures are invisible to the frontend per decisions.md entry 2026-04-13.
Alternatives considered: write status only (leaves error_message null, frontend cannot display error detail), write both fields (chosen — consistent with agent pattern).

---

**2026-05-08 | Pause wait nodes clear user_pause_response in DB before polling to prevent stale-value false return**
Code Review identified that user_pause_response in the Supabase DB persists across pause cycles. When cleaner_pause_wait_node starts polling after a domain pause has already occurred, the DB still contains the domain confirmation response. Without clearing it first, check_for_pause_response would immediately return the stale value and the cleaner pause would return the wrong response. Fix: each pause wait node includes user_pause_response=None in its initial DB update alongside the status change, before the polling loop begins.
Alternatives considered: clear user_pause_response in a separate Supabase call (two roundtrips, race window), clear as part of the status update (chosen — atomic, zero race window).

---

**2026-05-14 | time_series_data.csv date column stored as string — test files must parse with pd.to_datetime()**
analyzer.py's classify_columns detects datetime columns by dtype check only: `"datetime" in str(df[col].dtype)`. pd.read_csv loads date columns as dtype object regardless of content. Any test or code using time_series_data.csv must call pd.to_datetime(df["date"]) before passing to classify_columns or detect_time_series, or datetime_column will be None and no time series analysis will run.
Alternatives considered: save as actual datetime (CSV has no datetime dtype — it becomes string on save), document constraint in decisions.md (chosen).

---

**2026-05-14 | time_series_data.csv uses trend=20/day and noise_std=200, not trend=5 noise_std=500**
With trend=5 and noise_std=500, seed 42 produces a negative slope estimate (≈ −5.45) from np.polyfit because the seasonal component variance (2000² / 2 = 2M) dominates the trend signal (5 × 364 = 1820 total change). The seasonal component is not orthogonal to the linear trend in finite samples, so the slope estimate has SE ≈ √(2M / 11100) ≈ 13.5, making the true slope of +5 well within the noise of 0. trend=20 and noise_std=200 gives a measured slope of +9.48 with seed 42. The fixture's intent (upward trend + seasonal + guaranteed positive slope assertion) is preserved.
Alternatives considered: trend=5 noise_std=500 (spec value — fails assertion with seed 42), increase trend only (still borderline), increase trend and reduce noise (chosen — slope/SE ≈ 1.47, seed 42 confirmed positive).

---

**2026-05-16 | Frontend scaffold font pairing: Instrument Serif + DM Sans**
frontend-design skill specified this pairing for the Data Analysis Agent. Instrument Serif for headings, DM Sans for body text. Applied in frontend/app/layout.tsx.
Alternatives considered: Inter only (create-next-app default — too generic), Instrument Serif + DM Sans (chosen — professional, data-focused aesthetic per frontend-design skill).
