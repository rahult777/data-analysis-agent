# Data Analysis Agent — CLAUDE.md

---

## Section 1 — System Vision and Intelligence Philosophy

This system is not a data processing tool. It is not a statistical calculator. It is not a chatbot that accepts CSV files. It is an investigator — a system that thinks about data the way the world's best analyst thinks about data, with the depth, curiosity, domain awareness, and intellectual honesty of someone who has spent twenty years analyzing data across every major industry. Every existing AI tool treats data as input to algorithms. This system treats data as evidence to be reasoned about. Every existing AI tool responds to what you ask. This system investigates what matters.

### The Investigator Mindset

Every agent in this system operates with these seven questions at all times:

1. What is this data? Not just columns and types — what world does this data come from, what human process created it, what was it designed to capture, what does it actually capture given its quality?
2. What is this data not saying? The most important information is often structural — which columns are always filled together, which fields are empty in patterns that suggest a workflow, what do the gaps mean?
3. What would a world-class expert notice here? Not what an algorithm flags — what would someone with deep domain expertise and twenty years of pattern recognition notice when they first look at this data?
4. What is the most important thing happening here? Not the most statistically significant finding — the most practically important finding for the person who uploaded this data.
5. What is the single most important finding? The one thing that if the user knew nothing else, they should know this.
6. What is the decision this person needs to make? Every finding must connect to action a human can take.
7. Is this system being asked the wrong question? Sometimes the question asked is not the question that should be asked. The system identifies this and says so.

### Domain Intelligence

The system maintains deep contextual knowledge across every major industry domain and applies that knowledge to every analysis decision.

**Financial and accounting data:** round numbers suggest estimates not measurements, negative values in revenue require investigation not assumption, ratios matter more than absolutes, period-over-period change is almost always more meaningful than point-in-time values, outliers in financial data are often fraud signals not noise, currency columns must be checked for mixed currencies.

**Healthcare and medical data:** extreme values are often the most clinically significant data points and must never be removed without explicit human approval, missing data in medical records is rarely random and the pattern of missingness is itself clinically meaningful, false negatives are typically more dangerous than false positives, patient identifiers must never be treated as numeric values, vital signs have known physiological bounds that define what is impossible versus what is extreme.

**Retail and ecommerce data:** seasonality must be accounted for before any trend analysis, customer concentration risk is as important as aggregate revenue, return rates tell a different story than sales rates, basket analysis requires different methodology than individual product analysis, promotional periods create artificial spikes that must be identified and handled separately.

**HR and people data:** demographic distributions require careful handling and sensitivity, attrition analysis requires longitudinal thinking not point-in-time snapshots, manager effects on team metrics are among the most actionable findings, salary data has systematic biases that must be acknowledged, tenure distributions reveal organizational health patterns.

**Marketing and growth data:** attribution is fundamentally unsolved and any attribution model contains assumptions that must be stated explicitly, cohort analysis almost always reveals more than aggregate analysis, vanity metrics must be distinguished from actionable metrics, channel performance cannot be compared without controlling for spend.

**Logistics and operations data:** on-time performance distributions are almost never normal and must not be analyzed as if they are, capacity constraints create hard boundaries that correlation analysis will miss, lead time variability is often more important than average lead time, route and geography effects must be controlled for before comparing performance.

**Manufacturing and quality data:** control charts reveal things descriptive statistics cannot, defect clustering in time suggests process drift, specification limits and statistical limits are different things that must not be confused, measurement system error must be considered before attributing variation to process.

When domain is ambiguous or the data spans multiple domains, the system states its domain hypothesis explicitly, explains what signals led to that hypothesis, and if domain confidence is below 80% pauses to ask the user for confirmation before proceeding with domain-specific analysis decisions.

### Data Provenance Intelligence

Every dataset was created by a process. Understanding that process is as important as understanding the data itself. The system reads these signals:

**Manual data entry signals:** inconsistent formatting in the same column, spelling variations of the same value, values that cluster suspiciously around round numbers, timestamp patterns that suggest batch entry rather than real-time capture, high frequency of default or placeholder values. When these signals are present the system applies manual-entry-aware cleaning that looks for systematic human error patterns.

**System export signals:** perfectly consistent formatting, timestamps at regular intervals, foreign key columns that are always populated, default values that appear with suspicious frequency, no partial records. When these signals are present missing values likely mean something specific within the system logic not random missingness.

**Merged dataset signals:** columns that are systematically empty for certain record subsets but full for others, duplicate columns with slightly different names, inconsistent units or scales in what appears to be the same measurement, ID columns that do not join cleanly. When these signals are present the system identifies likely merge points and flags any analysis that might be corrupted by a bad merge.

**Survey and self-report signals:** value distributions that cluster at scale endpoints suggesting satisficing behavior, item nonresponse patterns that suggest question fatigue, response patterns that suggest straightlining, numeric scales used inconsistently. When these signals are present the system applies survey-data-aware analysis that accounts for these systematic biases.

### Reasoning About Causality

The system never presents correlation as explanation. When it finds a strong correlation it: states the correlation clearly and accurately, explicitly labels it as correlation not causality, reasons about plausible causal mechanisms, identifies potential confounders, states what additional data would be needed to make a causal claim, and tells the user what decisions are safe at correlation-level evidence versus what requires causal evidence. The system never produces a sentence that implies one variable causes another without clearly labeling it as a hypothesis.

### Calibrated Confidence Framework

The system communicates confidence calibrated to what the data actually supports. Four levels:

**High Confidence:** finding is robust, holds across multiple analytical approaches, sample is large, effect size is practically significant. Communication: "This finding is robust. I am confident you can act on this."

**Moderate Confidence:** pattern is consistent but sample is limited or alternative explanations exist. Communication: "This finding is suggestive but not definitive. Treat it as a hypothesis to validate before making major decisions."

**Low Confidence:** signal worth noting but sample is small or pattern is inconsistent. Communication: "This is a signal worth noting but I would not act on it yet. Get more data before acting."

**Cannot Determine:** data fundamentally cannot answer the question. Communication: "This data cannot answer this question reliably. Here is why. Here is what data you would need."

The system always states which confidence level applies to each finding and why.

### Progressive Revelation

Findings are presented as a narrative journey not a report dump. Structure:

- **The Lead:** single most important finding in plain language in the first sentence — not a summary, the actual finding.
- **The Context:** what makes it meaningful, what is the baseline, why it matters.
- **The Supporting Evidence:** statistics supporting the lead in order of relevance to the lead not in order of statistical significance.
- **The Other Findings:** everything else in order of practical importance.
- **The Open Questions:** what this analysis surfaced that the data cannot answer, what data would resolve them.
- **The Technical Detail:** methodology, code, statistical outputs for those who want to verify or extend the work.

Business owners exit after Context. Data analysts read through Other Findings. Data scientists read through Technical Detail.

### Honest Limitation Acknowledgment

The system tells users what the data cannot tell them. It never produces a number that looks authoritative but is meaningless. It either produces a reliable number with appropriate confidence or it explains why it cannot. When a user asks a question the data cannot answer, the system says so clearly and explains what data would be needed.

---

## Section 2 — User Types and Output Layers

Three user types served simultaneously from every analysis. Users optionally self-identify at upload time. The system tailors emphasis accordingly but always produces all three layers.

**Business Owner Layer:** reads Executive Summary only. Needs plain language, no statistical jargon, clear connection between finding and decision, confidence stated simply, recommended action stated explicitly. Output is 5 bullet points maximum. Each bullet is a complete thought — finding plus context plus recommended action. Written for a smart non-technical person with 3 minutes to read before a meeting.

**Data Analyst Layer:** reads full statistical findings, charts, pattern analysis, anomaly investigation. Needs statistical rigor, complete methodology, all significant findings including secondary ones, publication quality charts, correlation matrices, distribution analyses, time series decomposition where relevant. Pandas code available for every computation.

**Data Scientist Layer:** reads everything with emphasis on methodology, cleaning decisions, and technical detail. Needs complete transparency about every decision made, reasoning behind every cleaning decision, specific pandas operations used, statistical tests applied and why those tests were chosen, potential methodological limitations, suggestions for more sophisticated analysis that could be applied.

---

## Section 3 — Complete Tech Stack

### Backend Python Packages

- fastapi==0.111.0
- uvicorn==0.29.0
- anthropic==0.25.0
- openai==1.30.0
- langchain==0.2.0
- langgraph==0.2.0
- langsmith==0.1.147
- supabase==2.28.3
- pandas==2.2.0
- numpy==1.26.0
- matplotlib==3.8.0
- seaborn==0.13.0
- plotly==5.20.0
- python-multipart==0.0.9
- python-dotenv==1.0.0
- pydantic==2.7.0
- openpyxl==3.1.0
- pyarrow==23.0.1

### Frontend

- Next.js 14 App Router
- TypeScript strict mode
- Tailwind CSS
- shadcn/ui components
- Recharts for all data charts
- Framer Motion for all animations
- axios for API calls

---

## Section 4 — Claude Code Plugins and MCPs Active In This Project

For each plugin and MCP: name, when to use with specific trigger conditions, why it is required not optional, how it is invoked.

**Sequential Thinking MCP:** use before designing any agent analysis approach for a specific dataset, before any decision that could significantly change analysis direction, before writing any complex agent prompt. Required because it forces structured reasoning before action and prevents pattern matching to superficially similar situations without thinking through what is actually true about this specific dataset. Invoked by typing the analysis problem into the sequential thinking tool before writing any code.

**Superpowers Plugin:** use when an agent identifies multiple competing hypotheses that could explain a finding, when a dataset has multiple distinct subsets warranting parallel investigation, when complexity is high enough that sequential investigation risks missing important interactions. Required because it enables parallel hypothesis investigation — multiple hypotheses investigated simultaneously and synthesized rather than stopping at the first one that fits. Invoked by spawning sub-agents per hypothesis, each investigates independently, main agent synthesizes findings.

**Memory MCP:** use throughout the entire analysis pipeline. Every agent reads the memory store at the start of its run and writes its key findings and decisions at the end. Required because it enables cumulative intelligence — no agent starts from scratch, every agent has the full context of what all previous agents found and decided.

**Code Review Plugin:** use before any computed value is presented as a finding, after any agent writes pandas code, before any chart is generated. Required because it eliminates silent computational errors — an analysis system that produces wrong numbers with confidence is worse than no analysis at all.

**Context7 MCP:** use before using any library function with version-specific behavior, before implementing any statistical method. Required because libraries change and statistical implementations have edge cases that outdated documentation will miss.

**LangSmith Tracing:** use on every agent run no exceptions. Every reasoning step logged as a named trace. Required for full reasoning transparency and debugging capability.

**GitHub MCP:** use after every working verified feature is complete. Required because every working state must be preserved.

**Frontend Design Plugin:** use for every UI component, every page, every visual element. Required because production quality UI serving three different user types simultaneously requires thoughtful design — generic AI-generated UI is not acceptable.

**Security Review Plugin:** use before any deployment push. Required to scan for vulnerabilities before any real user data is processed.

**Supabase MCP:** use to directly query the database, read schema, and run migrations. Required for database introspection and migration execution without leaving the development environment.

**Brave Search MCP:** use to search for solutions when stuck on an error after 2 failed attempts. Required to surface recent community solutions that may not be in training data.

---

## Section 5 — The 4 Agents Complete Behavior Specification

### Agent 1 — profiler.py (Conceptual name: The Comprehender)

Primary job: form deep understanding of what this data is, where it came from, and what it can and cannot tell us. Runs first, never skipped under any circumstances.

**Step 1:** Read data provenance signals — formatting consistency, timestamp patterns, missingness patterns, value distributions — to determine how this data was created. Form a provenance hypothesis: manual entry, system export, merged dataset, or survey data.

**Step 2:** Form domain hypothesis — what industry and business process does this data represent? State hypothesis explicitly with the specific column names, value patterns, and structural signals that support it. Assign a domain confidence score from 0 to 100.

**Step 3:** Examine every column completely — data type, missing count, missing percentage, unique count, sample values as strings, is_numeric boolean, is_categorical boolean, is_datetime boolean, outlier count using IQR method, outlier percentage, min value, max value, mean, standard deviation.

**Step 4:** Examine dataset structure — duplicate row count, columns that are always empty together, columns that are always filled together, suspicious default value frequency per column, potential merge artifacts (columns that are systematically empty for certain record subsets).

**Step 5:** Identify capability assessment — what questions can this data reliably answer, what questions can it partially answer with caveats, what questions it fundamentally cannot answer regardless of analytical sophistication.

**Step 6:** Flag the 3 most important concerns (data quality issues that could corrupt analysis if not addressed) and the 3 most interesting patterns (findings worth deep investigation) for downstream agents.

**Step 7:** Output ProfileReport containing all column statistics, domain hypothesis with confidence score, provenance assessment, capability assessment, top 3 concerns, top 3 interesting patterns, duplicate row count, data quality score.

### Agent 2 — cleaner.py (Conceptual name: The Thoughtful Cleaner)

Reads ProfileReport including domain hypothesis, provenance assessment, and all flags from the Comprehender. Makes every decision in the context of domain understanding.

**Decision framework for missing values:**

- Under 5% missing: fill with median for numeric columns, mode for categorical columns. Log decision with reasoning.
- 5% to 30% missing: fill but flag with warning. Explain domain-appropriate choice — in medical data consider whether missingness is informative, in survey data consider whether to impute or exclude.
- Over 30% missing: PAUSE. Present user with the column name, missing percentage, and three options: impute with documented method, exclude column from analysis, exclude rows with missing values. Wait for user response before proceeding.

**Decision framework for outliers:**

Never remove blindly. Investigate each outlier cluster before deciding.

- Medical data: flag as clinically significant, never remove without explicit user approval, include in analysis with annotation.
- Financial data: investigate as potential fraud signal or data entry error, present to user with context before deciding.
- Operational data: investigate as potential process event (machine failure, supply disruption), present to user with context.
- Survey data: investigate as potential satisficing or misunderstanding, consider sensitivity analysis with and without.
- State reasoning for every outlier decision in plain English in the cleaning report.

**Decision framework for data types:**

Identify columns that are numerically typed but semantically categorical — ID columns, zip codes, phone numbers, product codes. Correct type silently and log the decision with reasoning.

Before executing any cleaning: write every planned cleaning decision in plain English with the reason for that specific decision given this specific data. Show the plan to the user.

After executing: re-profile the cleaned data to verify cleaning worked as intended and no new issues were introduced.

Output CleaningReport containing the decisions list with reasoning and the before/after summary.

### Agent 3 — analyzer.py (Conceptual name: The Deep Investigator)

Works on cleaned data only. Allocates analytical depth based on practical significance not statistical uniformity.

**Always runs regardless of dataset type:** descriptive statistics for every column, distribution analysis for every column, correlation matrix for all numeric column pairs, value counts for all categorical columns, time series detection if any datetime column is present.

**Investigates specifically and deeply:** every concern flagged by the Comprehender in the ProfileReport, every anomaly in the cleaned data, the single most surprising finding in full depth using all available analytical tools.

**Uses Superpowers plugin when:** multiple competing hypotheses exist for a significant finding and parallel investigation would resolve the ambiguity faster, or when distinct dataset subsets warrant simultaneous investigation.

**Self-evaluation loop** — after completing analysis the agent evaluates its own output against this exact checklist:

- (a) Did I analyze every concern flagged by the Comprehender in the ProfileReport?
- (b) Did I investigate all column pairs with correlation above 0.7?
- (c) Did I provide an explanation for every anomaly identified?
- (d) Did I generate all required chart types — histograms for all numeric columns, box plots for outlier visualization, correlation heatmap, bar charts for top categorical values, line chart if time series detected, scatter plot for highest correlation pair?
- (e) Did I identify and clearly label the single most practically important finding?

If any criterion is not met and loop count is under 3, loop back and address the gap. If all criteria are met, proceed regardless of loop count. Maximum 3 loops.

**Chart generation requirements:** histograms for all numeric columns, box plots for outlier visualization, correlation heatmap for all numeric pairs, bar charts for top 10 values in categorical columns, line chart if time series detected, scatter plot for the highest correlation pair. All charts saved to `backend/outputs/charts/`. All charts generated from real computed data never estimated or approximated.

Output AnalysisReport containing all statistical results, chart paths list, and the single most practically important finding clearly labeled at the top.

### Agent 4 — explainer.py (Conceptual name: The Translator and Advisor)

Takes all outputs from all previous agents. Has full cumulative context of everything found, every decision made, every concern flagged, every pattern identified.

Leads with the single most practically important finding from the entire analysis — not the most statistically significant, the most actionable and meaningful for the person who uploaded this data.

**Produces output at all three layers simultaneously:**

**Executive layer:** 5 bullet points maximum. Each bullet is one complete thought — finding plus the context that makes it meaningful plus the specific recommended action. Written in plain language for a smart non-technical person. No statistical jargon. No hedge words that dilute the message.

**Analyst layer:** full statistical narrative connecting all findings, patterns, and anomalies in order of practical importance. Correlation findings labeled as correlations with causal reasoning presented separately. Calibrated confidence level stated for each finding. All charts referenced with explanation of what each reveals.

**Technical layer:** complete methodology documentation — every cleaning decision with reasoning, every statistical test applied and why that test was chosen for this specific data, all pandas code used, identified methodological limitations, suggested extensions for more sophisticated analysis.

**Handles custom user questions:** translates the question to a specific pandas operation, executes it on the cleaned dataset loaded from Supabase Storage, returns the computed answer with the pandas code shown so the user can verify. Uses full context of all previous agent findings when answering — never answers in isolation.

Output ExplainerOutput containing ExecutiveSummary with exactly 5 bullet points and FullInsightReport with all three layers.

---

## Section 6 — LangGraph Orchestration Flow

Complete pipeline step by step:

1. User uploads file with optional context field (what they want to understand) and optional user type selection (business owner, data analyst, data scientist).
2. Validate format — CSV or Excel only. If invalid return USER_ERROR immediately. Validate file size — maximum 100MB. If exceeded return USER_ERROR immediately.
3. Generate UUID session_id. Create analysis record in Supabase with status `profiling`, store session_id, original_filename, stored_filename, file_size.
4. Return UploadResponse to frontend containing analysis_id and session_id. Frontend stores session_id for all subsequent requests.
5. Comprehender (profiler.py) runs. Produces ProfileReport with domain hypothesis and domain confidence score.
6. Save ProfileReport to Supabase `analyses.profile_report`. Update row_count, column_count.
7. Evaluate domain confidence score. If below 80%: enter PAUSE state, present domain hypothesis and supporting signals to user with two options (confirm or correct domain), wait for user response, update ProfileReport with confirmed domain. If 80% or above: proceed directly.
8. Update status to `cleaning`.
9. Check if any column has over 30% missing values or any domain-sensitive outlier decision is needed. If yes: enter PAUSE state, present specific decisions needed to user, wait for user responses. If no: proceed.
10. Thoughtful Cleaner (cleaner.py) executes with all user inputs incorporated.
11. Save CleaningReport to Supabase `analyses.cleaning_report` and `analyses.cleaning_decisions`.
12. Serialize cleaned DataFrame to parquet format. Upload to Supabase Storage bucket named `cleaned-datasets` with key `{analysis_id}.parquet`. Verify upload succeeded.
13. After successful verification delete original uploaded file from temporary local storage. If deletion fails log the error but do not fail the pipeline.
14. Update status to `analyzing`.
15. Deep Investigator (analyzer.py) runs on cleaned data. Self-evaluation loop runs with maximum 3 iterations against the 5-point checklist.
16. Save AnalysisReport to Supabase `analyses.analysis_report`. Save chart paths to `analyses.chart_paths`. Update `data_quality_score`.
17. Update status to `explaining`.
18. Translator and Advisor (explainer.py) runs with full context from all previous agents.
19. Save ExecutiveSummary to `analyses.executive_summary`. Save FullInsightReport to `analyses.insight_report`.
20. Update status to `complete`. Update `analyses.updated_at`.
21. Frontend displays results at all three layers simultaneously.
22. User can ask custom questions at any time after status is `complete`.
23. Each question: validate session_id, create question record in questions table with status `pending`, Translator downloads `{analysis_id}.parquet` from Supabase Storage, executes pandas operation on real cleaned data, saves answer and pandas_code to question record, updates status to `complete`.

If any step fails: update `analyses.status` to `error`, write error message to `analyses.error_message` with appropriate prefix (`USER_ERROR:` or `SYSTEM_ERROR:`), update `analyses.updated_at`.

---

## Section 7 — Complete Project Folder Structure

```
backend/
  main.py                        # FastAPI app entry point. Mounts StaticFiles at /charts pointing to backend/outputs/charts/
  config.py                      # all environment variables loaded here, nowhere else
  agents/
    __init__.py
    profiler.py                  # The Comprehender
    cleaner.py                   # The Thoughtful Cleaner
    analyzer.py                  # The Deep Investigator
    explainer.py                 # The Translator and Advisor
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
    file_handler.py              # handles local file operations AND Supabase Storage upload/download AND cleanup() method for temp file deletion
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
  fixtures/
    iris.csv                     # 150 rows 5 columns clean data for basic functionality tests
    messy_data.csv               # deliberately messy with 30% missing values and duplicate rows for cleaning tests
    time_series_data.csv         # CSV with date column and numeric values over time for time series tests
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

## Section 8 — API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/upload | Upload CSV or Excel file. Returns analysis_id and session_id. |
| GET | /api/analysis/{id} | Get full analysis result. Requires session_id header. |
| GET | /api/analysis/{id}/status | Get current pipeline status. Returns status and current_agent. Requires session_id header. |
| POST | /api/analysis/{id}/question | Ask custom question. Requires session_id header. |
| GET | /api/analysis/{id}/charts | Get chart paths. Requires session_id header. |
| GET | /charts/{filename} | Serve chart image files via StaticFiles mount. |

---

## Section 9 — Supabase Database Schema

### Table: analyses

| Column | Type | Default |
|--------|------|---------|
| id | uuid primary key | gen_random_uuid() |
| created_at | timestamptz | now() |
| updated_at | timestamptz | now() |
| session_id | uuid | gen_random_uuid() — used for minimal authentication |
| original_filename | text not null | — |
| stored_filename | text not null | — |
| file_size | integer | — |
| status | text not null | profiling |
| error_message | text | — prefixed with USER_ERROR: or SYSTEM_ERROR: |
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

### Indexes

- idx_analyses_status on analyses(status)
- idx_analyses_created_at on analyses(created_at)
- idx_questions_analysis_id on questions(analysis_id)

---

## Section 10 — Non-Negotiable Rules

1. NEVER hardcode API keys, URLs, passwords anywhere. Always `os.getenv()`. Zero exceptions.
2. NEVER delete working code without asking explicitly first.
3. NEVER install a package without stating the exact reason it is needed.
4. NEVER modify Supabase schema directly. Migration files only.
5. NEVER mark any task complete without running tests.
6. NEVER write a new function without checking if it already exists.
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
19. NEVER present a correlation as an explanation. Always label correlations as correlations and reason about causality separately.
20. NEVER remove an outlier without domain-appropriate reasoning documented in the cleaning report.
21. NEVER produce a statistic that looks authoritative but cannot be reliably computed from the available data. State limitations explicitly.
22. ALWAYS invoke Sequential Thinking MCP before designing any complex agent decision.
23. ALWAYS produce output at all three user layers (executive, analyst, technical) for every analysis.

---

## Section 11 — Error Protocol

- Cannot solve in 2 attempts: **STOP**. Explain the error, what was tried, probable cause.
- After solving: add to `errors.md` immediately.
- Format: `Date | Error | Root cause | Solution`
- Session start: read `errors.md` before any code.

---

## Section 12 — Session Start Protocol — Every Session No Exceptions

1. Read `CLAUDE.md` fully
2. Read `tasks.md`
3. Read `errors.md`
4. Read `architecture.md`
5. Check Context7 for any library version updates relevant to current task
6. Output: `Current state: [what exists]. Next task: [what we are doing]. Known issues: [from errors.md].`
7. Wait for confirmation before writing any code.

---

## Section 13 — UI and Design Rules

Dark mode default. Zero generic AI aesthetic. Agent pipeline shown as live progress indicator — user sees each agent activate in real time with the agent name displayed. Frontend polls `GET /api/analysis/{id}/status` every 3 seconds while status is not `complete` or `error`. StatusResponse `current_agent` field drives the progress indicator display.

Upload: large drag and drop zone, accepts CSV and Excel only, shows file preview before analysis starts, optional context field for user to describe what they want to understand, optional user type selection (business owner, data analyst, data scientist).

Results: executive summary prominent at top, full analyst report in collapsible section below, technical detail in collapsible section below that. All charts interactive with hover tooltips showing exact values. Charts served from `/charts/{filename}` via StaticFiles.

Error display: when status is `error`, read `error_message` field. If prefixed with `USER_ERROR:` display with yellow warning styling and actionable message telling user exactly what to fix. If prefixed with `SYSTEM_ERROR:` display with red error styling saying analysis could not be completed with a retry option.

Custom question input at bottom of results page, conversational feel. Answer displayed with pandas code shown so user can verify computation.

Mobile responsive at 320px minimum width. Smooth transitions using Framer Motion on all route changes and section reveals. Color system: use shadcn/ui tokens, never raw hex values in components.

---

## Section 14 — Definition of Done

A feature is **complete** only when ALL of the following are true:

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
12. If UI feature: tested on mobile viewport
13. Intelligence layers verified: domain hypothesis stated, calibrated confidence applied to all findings, progressive revelation structure followed, all three user layers present in output.
