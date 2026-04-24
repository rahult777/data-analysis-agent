# Agent 1 — The Comprehender (profiler.py)

This document contains the complete behavior specification for the Profiler agent. Load this doc when building, modifying, testing, or writing the system prompt for profiler.py. Do not build or modify this agent without reading this document in full first.

---

## Identity and Purpose

**File:** `backend/agents/profiler.py`
**Conceptual name:** The Comprehender
**Position in pipeline:** First. Runs before every other agent. Never skipped under any circumstances.

The Profiler is not a statistics calculator. It is not a column-counter. It is the agent that forms a genuine understanding of what a dataset is — where it came from, what human process created it, what it was designed to capture, and critically, what it can and cannot reliably tell us.

The Profiler's output is not just numbers. It is understanding. Every downstream agent depends on the Profiler's domain hypothesis, provenance assessment, and flagged concerns. If the Profiler misunderstands the data, every subsequent agent amplifies that misunderstanding. The quality of the entire analysis depends on the quality of the Profiler's comprehension.

---

## The Seven Steps — Mandatory Execution Order

### Step 1 — Read Data Provenance Signals

Before examining any column statistics, the Profiler examines the dataset as a whole to determine how this data was created. It looks for these signals:

**Manual data entry signals:**
- Inconsistent formatting within the same column (e.g., "New York", "new york", "NY", "N.Y." in the same column)
- Spelling variations of the same value
- Values that cluster suspiciously around round numbers (100, 500, 1000 appearing far more often than nearby values)
- Timestamp patterns that suggest batch entry (many records entered at the same time of day)
- High frequency of default or placeholder values ("N/A", "TBD", "0", "-")

**System export signals:**
- Perfectly consistent formatting throughout
- Timestamps at regular programmatic intervals
- Foreign key columns that are always populated
- Default values appearing with suspicious mathematical frequency
- No partial records — all-or-nothing row completeness

**Merged dataset signals:**
- Columns that are systematically empty for certain record subsets but fully populated for others
- Duplicate columns with slightly different names (e.g., "customer_id" and "cust_id")
- Inconsistent units or scales in what appears to be the same measurement
- ID columns that do not appear to join cleanly to the rest of the data

**Survey and self-report signals:**
- Value distributions that cluster heavily at scale endpoints (1s and 5s on a 1-5 scale)
- Item nonresponse patterns suggesting question fatigue (later columns systematically emptier)
- Response patterns suggesting straightlining (same answer repeated across many columns)
- Numeric scales used inconsistently across rows

The Profiler assigns a **provenance hypothesis**: manual entry, system export, merged dataset, survey data, or mixed. This hypothesis changes how the Cleaner interprets missing values and outliers downstream.

---

### Step 2 — Form Domain Hypothesis

The Profiler examines column names, value patterns, and structural signals together to determine what industry and business process this data represents.

This is not just column name matching. The Profiler reasons holistically:
- What do these columns, together, represent?
- What kind of organization would collect this data?
- What business process would produce records shaped like this?
- What does the combination of columns reveal about the purpose of this dataset?

The domain hypothesis must be stated explicitly with supporting evidence:
- Which column names support the hypothesis
- Which value patterns support the hypothesis
- Which structural signals support the hypothesis

The Profiler assigns a **domain confidence score from 0 to 100**. This score determines downstream behavior:
- 80 or above: proceed directly to Cleaner
- Below 80: enter PAUSE state — present the hypothesis and supporting signals to the user, offer two options (confirm or correct), wait for user response, update the ProfileReport with the confirmed domain before any further processing continues, then proceed to the Cleaner.

Domain knowledge that applies to each domain type is documented in `docs/intelligence-philosophy.md` under Domain Intelligence. The Profiler must apply that domain knowledge when forming its hypothesis.

---

### Step 3 — Examine Every Column Completely

For every column in the dataset, the Profiler computes and records:

| Field | Description |
|-------|-------------|
| column_name | The column name as it appears in the data |
| dtype | The pandas dtype string (e.g., "int64", "object", "float64", "datetime64") |
| missing_count | Absolute count of missing values |
| missing_pct | Percentage of values missing (0.0 to 100.0) |
| unique_count | Count of distinct non-null values |
| sample_values | Up to 5 representative values, stringified for safe JSON serialization |
| is_numeric | Boolean — true if column contains numeric data |
| is_categorical | Boolean — true if column contains categorical/string data |
| is_datetime | Boolean — true if column contains or could be parsed as datetime |
| outlier_count | Count of statistical outliers using IQR method (null for non-numeric) |
| outlier_pct | Percentage of values that are outliers (null for non-numeric) |
| min_value | Minimum value (null for non-numeric) |
| max_value | Maximum value (null for non-numeric) |
| mean | Mean value (null for non-numeric) |
| std | Standard deviation (null for non-numeric) |

The Profiler also makes an intelligent type assessment: if a column is numerically typed but semantically categorical (ID columns, zip codes, phone numbers, product codes), this is flagged explicitly for the Cleaner.

---

### Step 4 — Examine Dataset Structure

Beyond individual columns, the Profiler examines the dataset's structure as a whole:

- **Duplicate row count:** Exact duplicate rows in the dataset
- **Co-emptiness patterns:** Columns that are always empty together (suggests a related data entry workflow)
- **Co-completeness patterns:** Columns that are always filled together (suggests a linked process)
- **Default value frequency:** Columns where a single value appears with suspicious frequency (may indicate a default that was never updated)
- **Potential merge artifacts:** Columns that are systematically empty for certain record subsets but full for others (the clearest signal of a bad merge)

These structural observations often reveal more about the data's history and reliability than any individual column statistic.

---

### Step 5 — Capability Assessment

The Profiler explicitly identifies what this dataset can and cannot tell us. Three categories:

**Can reliably answer:** Questions where the data is complete, the methodology is sound, and the result would be trustworthy.

**Can partially answer with caveats:** Questions where the data is sufficient for a directional answer but limitations must be stated — missing data that affects completeness, time period too short for trend analysis, sample too small for confident inference.

**Cannot answer regardless of sophistication:** Questions that the data structurally cannot answer — asking about causality from observational data, asking about populations not represented in the sample, asking for longitudinal analysis from a point-in-time snapshot.

This capability assessment is critical. It prevents the downstream agents from producing authoritative-looking answers to questions the data cannot reliably answer. It also helps the Explainer set appropriate expectations with the user.

---

### Step 6 — Flag Concerns and Patterns

The Profiler flags the most important items for downstream agents. Two categories, three items each:

**Top 3 Concerns** — data quality issues that could corrupt analysis if not addressed:
- These are not just "has missing values" — they are specific, reasoned concerns
- Example: "The revenue column has 34% missing values concentrated in records from Q3 2023, which will bias any trend analysis unless addressed explicitly"
- Each concern states the issue, the affected columns, and why it matters for analysis

**Top 3 Interesting Patterns** — findings worth deep investigation:
- These are signals the Profiler noticed that deserve the Analyzer's attention
- Example: "The discount column and the return column are correlated at r=0.71 — this may indicate that discounted products have higher return rates, which is worth investigating"
- Each pattern states what was noticed and why it is interesting

These flags serve as the Analyzer's initial investigation agenda. The Analyzer's self-evaluation checklist explicitly requires investigating every concern the Profiler flagged.

---

### Step 7 — Output ProfileReport

The Profiler outputs a complete ProfileReport containing:

- All column statistics (one ColumnProfile per column)
- Duplicate row count
- Data quality score (float 0.0 to 1.0, computed from missingness, duplicate rate, and outlier prevalence)
- Domain hypothesis with supporting signals
- Domain confidence score (0 to 100)
- Provenance hypothesis and supporting signals
- Capability assessment (three categories)
- Top 3 concerns with reasoning
- Top 3 interesting patterns with reasoning

This ProfileReport is saved to `analyses.profile_report` in Supabase and passed to every subsequent agent via the LangGraph state. No agent builds on top of raw data — every agent builds on the Profiler's understanding.

---

## What the Profiler Does NOT Do

- It does not clean data. Cleaning is the Cleaner's job.
- It does not run statistical analysis. That is the Analyzer's job.
- It does not generate charts.
- It does not make cleaning decisions — it only provides the information the Cleaner needs to make those decisions wisely.
- It does not remove outliers or fill missing values, even temporarily.

The Profiler's only job is to understand. Everything else comes after.

---

## System Prompt Location

`backend/prompts/profiler_system.md`

The system prompt for this agent must be written against the full intelligence philosophy in `docs/intelligence-philosophy.md`. It must embody the Investigator Mindset. It must apply domain knowledge. It must ask the seven questions. It must never reduce to mechanical statistics.

When writing the system prompt, switch to Opus model for the full depth of reasoning it requires.

---

## Test Fixture

Basic functionality: `tests/fixtures/iris.csv` (150 rows, 5 columns, clean data)
Cleaning tests: `tests/fixtures/messy_data.csv` (30% missing values, duplicate rows)
Time series tests: `tests/fixtures/time_series_data.csv` (date column, numeric values over time)

Test file: `tests/test_profiler.py`

The Profiler is considered complete only when all 14 Definition of Done criteria are met — see `CLAUDE.md`.

---

## LangSmith Tracing

Every Profiler run must have LangSmith tracing attached via `create_tracer("profiler")` from `backend/utils/langsmith_client.py`. No exceptions. The trace must be visible in the LangSmith dashboard before the Profiler is marked complete.
