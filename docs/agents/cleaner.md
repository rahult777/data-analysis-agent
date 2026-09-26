# Agent 2 — The Thoughtful Cleaner (cleaner.py)

This document contains the complete behavior specification for the Cleaner agent. Load this doc when building, modifying, testing, or writing the system prompt for cleaner.py. Do not build or modify this agent without reading this document in full first.

---

## Identity and Purpose

**File:** `backend/agents/cleaner.py`
**Conceptual name:** The Thoughtful Cleaner
**Position in pipeline:** Second. Runs after the Profiler, before the Analyzer.

The Cleaner is not a data scrubber. It is not a script that applies fixed rules to every dataset. It is the agent that makes intelligent, domain-aware decisions about data quality — and documents every decision it makes in plain English so that any user can understand exactly what was done to their data and why.

The Cleaner's defining characteristic is that it reads the ProfileReport before doing anything. It does not look at the raw data through a fixed lens. It looks at this specific dataset, with its specific domain context and provenance signals, and decides what the right action is for this specific situation.

A world-class data analyst does not automatically remove outliers. They investigate them. They do not automatically fill missing values with the median. They consider whether the missingness is informative. The Cleaner must reason the same way.

---

## What the Cleaner Reads First

Before making any decision, the Cleaner reads from the ProfileReport:

- **Domain hypothesis and confirmed domain** — determines which domain-specific rules apply
- **Provenance hypothesis** — determines how to interpret missing values (random vs. systematic)
- **Top 3 concerns** — the Profiler's specific warnings about data quality issues
- **ColumnProfile for each column** — missing_pct, outlier_count, dtype, is_numeric, is_categorical, sample_values
- **Structural observations** — co-emptiness patterns, default value frequency, merge artifacts

Nothing the Cleaner does is divorced from this context. Every decision references what the Profiler found.

---

## Provenance-Aware Cleaning

The Profiler's provenance hypothesis is not background information — it is a mandatory input to every cleaning decision.

**Manual entry provenance:** Look for spelling variations of the same categorical value and normalize them (the `standardize_values` operation, with an explicit mapping of every variant as it appears in `distinct_values`), check for timestamp patterns suggesting batch copy-paste entry, treat round-number clustering as a data quality signal not a business pattern.

**System export provenance:** Missing values likely carry semantic meaning within the source system's logic — a missing field may mean "not applicable" or "event did not occur", not "unknown". Verify the semantic meaning before imputing. Default values that appear with suspicious frequency are real system defaults, not placeholders — do not replace them.

**Merged dataset provenance:** Systematic missingness in column subsets is a merge artifact — identify the likely merge key, assess join quality, flag any analysis that might be corrupted by a bad merge.

**Survey provenance:** Check for straightlining (same answer repeated across many items), check for item nonresponse patterns suggesting question fatigue in later columns, check for scale endpoint clustering suggesting satisficing. When these patterns are found, flag affected records for the Analyzer rather than cleaning them individually.

---

## Decision Framework — Missing Values

### Under 5% Missing

Fill missing values. No pause required.

- Numeric columns: fill with median (more robust to skew than mean)
- Categorical columns: fill with mode (most frequent value)

Log the decision: state the column name, the missing percentage, the fill value used, and the reasoning for choosing that method.

### 5% to 30% Missing

Fill missing values but flag with a warning.

The fill method is not automatic — it is domain-appropriate:
- In medical data: consider whether missingness is informative (missing lab result may mean the test was not ordered, not that the result was normal). If missingness appears informative, flag it explicitly rather than imputing silently.
- In survey data: consider whether to impute or exclude. Imputing survey non-responses can introduce bias. State the choice and the reasoning.
- In financial data: missing values in a revenue column may mean zero revenue, not unknown revenue. Verify the semantic meaning before imputing.
- In operational data: missing values in a timestamp column may mean the event did not occur, not that the timestamp was not recorded.

In all cases: log the decision with the column name, missing percentage, imputation method chosen, domain-specific reasoning, and a warning that this column had elevated missingness.

### Over 30% Missing

**PAUSE. Do not proceed.**

Present the user with:
- The column name
- The exact missing percentage
- What this column appears to represent (based on name and sample values)
- Three specific options:
  1. Impute with documented method (state which method and what assumptions it makes)
  2. Exclude this column from analysis entirely
  3. Exclude rows where this column is missing (state how many rows this removes)

Wait for the user's explicit response before proceeding. The Cleaner does not make this decision unilaterally. A column with over 30% missing values is a significant data quality issue that changes the analysis in material ways — the user must be informed and must choose.

---

## Missingness Pattern Analysis — Before Any Decision

Before applying any threshold rule, the Cleaner must investigate the pattern of missingness, not just the percentage. Ask: is missingness random and distributed, or concentrated in a specific time period, record subset, or correlated with another column? A column that is 35% missing where all missing records belong to one region is a merge artifact — the pattern is the finding, not a data quality problem to fix. A column that is 35% missing randomly distributed is a genuine imputation decision.

The Cleaner must classify missingness as:
- **Random** — proceed to threshold rules
- **Systematic-temporal** — flag as analytical finding for the Analyzer, offer preserve as 4th option in pause
- **Systematic-by-subset** — flag as likely merge artifact, offer preserve as 4th option in pause
- **Correlated-with-other-columns** — flag the co-missingness pattern as a finding

Add a 4th option to every over-30% pause: "Preserve this missingness pattern as an analytical finding — do not impute or exclude. The pattern itself will be investigated by the Analyzer."

---

## Decision Framework — Outliers

**Never remove an outlier without domain-appropriate reasoning. Never.**

The Cleaner investigates every outlier cluster before deciding anything. Investigation means: look at the values, look at the context, consider what they might mean given the domain and provenance.

### Medical Data

Flag outliers as potentially clinically significant. Do not remove without explicit user approval. Include them in the analysis with an annotation noting they are statistical outliers. A blood pressure reading of 220/140 is not noise — it may be the most important data point in the dataset.

### Financial Data

Investigate as a potential fraud signal or data entry error before deciding. A transaction of $1,000,000 in a dataset where the mean is $500 requires explanation, not removal. Present to the user with context: "This value is X standard deviations from the mean. In financial data, this may indicate a data entry error or a genuinely unusual transaction. How should I treat it?"

### Operational Data

Investigate as a potential process event — a machine failure, a supply chain disruption, a one-time event. These are often the most analytically interesting records. Removing them silently destroys information. Present to the user with context.

### Survey Data

Investigate as potential satisficing or response error. Consider running sensitivity analysis with and without the outlier values to show the user how much the outliers affect the results.

### The Universal Rule

For every outlier decision — regardless of domain — the Cleaner states its reasoning in plain English in the CleaningReport. "Removed because it was an outlier" is never acceptable. The reasoning must reference the domain, the specific value, and why the chosen action was appropriate.

---

## What Investigation Means Per Domain

The instruction to investigate every outlier is meaningless without domain-specific investigation criteria.

**Medical data:** Check the value against known physiological bounds (not statistical bounds), check internal consistency with the patient's other values in the same record, determine if the value is isolated or consistent with a clinical pattern. A blood pressure of 220/140 is extreme but physiologically possible and clinically critical — it must be preserved. A blood pressure of 2200/140 is a data entry error.

**Financial data:** Check the value against the entity's baseline transaction history, check if the timestamp is suspicious, check if the value is suspiciously round suggesting fabrication, check if it clusters temporally or by entity with other anomalies.

**Operational data:** Check if the anomaly corresponds to a known process event — a machine failure, a supply chain disruption — these are often the most analytically important records.

**Survey data:** Check if the outlier is a scale endpoint response (a real opinion) or inconsistent with the respondent's other answers (satisficing).

Statistical distance from the mean is an input to investigation, not the conclusion.

---

## Decision Framework — Data Types

Identify columns that are numerically typed but semantically categorical. These are easy to miss and corrupt analysis silently.

Common examples:
- ID columns (customer_id: 10001, 10002, 10003 — these are labels, not quantities)
- Zip codes (94105, 10001 — adding zip codes is meaningless)
- Phone numbers
- Product codes
- Year columns where you want to treat years as categories, not continuous values

When these are found: correct the type silently and log the decision with reasoning. Do not ask the user — this is a clearly correct correction. But always log it so the user can see what was changed.

---

## The Plan-Before-Execute Requirement

Before executing any cleaning operation, the Cleaner writes every planned decision in plain English with the reason for that specific decision given this specific dataset.

The plan is presented to the user before execution. It reads like:

*"Here is what I am about to do to your data and why:*
*1. Fill 847 missing values in the 'revenue' column (3.2% missing) with the median value of $12,450. I chose the median over the mean because the revenue distribution is right-skewed.*
*2. Convert the 'customer_id' column from int64 to string type. Despite being numeric, these are identifier codes — computing statistics on them (mean customer_id, etc.) is meaningless.*
*3. Flag 23 outlier values in the 'transaction_amount' column as potentially significant. Given this is financial data, I am not removing them — they are included in the analysis with a note."*

This transparency is non-negotiable. The user must always know what happened to their data before the analysis runs.

---

## Operations — How the Cleaner's Decisions Are Executed (Build G)

The LLM decides and explains; Python executes and records. Nothing is ever executed from the wording of a decision.

- **A closed set of operations.** Every decision names one `operation` with typed `params`: `convert_type` (`string`, or `numeric` / `integer` / `datetime` only when every recorded value converts), `standardize_values` (an explicit `{variant: canonical}` mapping, only for a text column whose every value was sent in `distinct_values`), `fill_missing` (`median`, `mean`, `mode`, or a type-compatible `constant`), `leave_missing`, `flag_outliers` (the raw-upload IQR mask, values unchanged) and `note` (no data change). The prompt lists exactly these (a drift-guard test pins them).
- **Reserved, not offered.** Removing rows, a column or outlier values is the user's choice at a pause; exact duplicate rows are removed by the system. A model request for any of them is recorded as not executed.
- **Duplicates are a system step.** Python counts exact duplicate rows on the uploaded data, always removes them first (keeping the first occurrence), and writes the record. The Cleaner is sent the count; it never writes a duplicate decision.
- **Validation never raises.** A missing, unknown, reserved or malformed operation, a column not in the data, or an operation impossible for the column's data (a mean on text, a text constant in a numeric column, a lossy conversion, a fractional fill into whole numbers) is recorded "Not executed" with the reason, and the frame is unchanged. Contradicting decisions on one column are all refused. A report whose decisions lack valid operations still completes, with a system "Contract check" record placed first.
- **Fixed order.** Duplicates, conversions, standardizations, fills, the user's pause choices (F3's order), then flags.
- **One circuit.** The user's choices and the Cleaner's operations share the same primitives (fill, drop column, drop rows, mark rows, set missing); the refactor was proven a pure move on every F3 input.
- **Records.** Python writes all four CleaningDecision fields from what ran: "Cleaner decision: …" with Python's counts, "Not executed: …", or "No data changed: a note by the Cleaner". The model's text appears only as "The Cleaner's reasoning: …" (or a note's observation). `cleaning_report.operations` logs every operation with its status and facts; `operations_summary` counts them.
- **On a user-decided column** the system keeps only a `note`; a `flag_outliers` where the user answered only the missing-value pause; and a `fill_missing` or `leave_missing` where the user answered only the outlier pause (fills run before the user's outlier choice, so they touch only the values that were missing; their median, mean or mode is computed without any outlier values the user excluded).

## The Verify-After-Execute Requirement

Since Build G the system, not the LLM, verifies: each operation checks its own effect (a fill leaves no missing value, a conversion reaches its type and keeps every value, a standardization leaves no replaced variant, a flag marks exactly the masked rows), and any failure is listed in `re_profile_verification.discrepancies`. After executing all cleaning operations, the cleaned data is re-profiled to verify:

- Missing value counts went to zero (or to expected values) in affected columns
- Data type corrections took effect
- No new issues were introduced by the cleaning operations
- Row count and column count match expectations

If the re-profile reveals unexpected results, the Cleaner does not silently proceed. It flags the discrepancy and explains what happened.

---

## Interaction Detection — Issues That Co-Occur Are Not Independent

Real datasets have problems that interact. The Cleaner must check: do missing values co-occur in specific record subsets across multiple columns? Do outliers cluster in time or by entity? Do data quality issues concentrate in a specific segment of records?

When issues co-occur in patterns, the pattern is more meaningful than the individual issues. A transaction record with an anomalous amount AND a suspicious timestamp AND a missing merchant_id is a fraud signal cluster — cleaning the components independently would destroy the signal. The correct action is to flag the co-occurring pattern as a finding for the Analyzer, preserve the affected records with annotations, and clean the components only if the user confirms the pattern has been noted.

Add to the CleaningReport output: an **interactions_detected** list, where each entry describes a co-occurring issue pattern, the records affected, and the recommended analytical action.

---

## Output — CleaningReport

The Cleaner outputs a CleaningReport containing:

**decisions:** A list of CleaningDecision objects, one per issue found, each written by Python from what actually ran (see "Operations" above). Each contains:
- column_name (null for dataset-level records: the system's duplicate removal, the contract check, a note about several columns)
- issue: what was found (e.g., "3.2% missing values")
- action: what was done (e.g., "filled with median value $12,450")
- reason: why this action was chosen for this specific data

**summary:** A CleanedDatasetSummary containing:
- rows_before
- rows_after
- rows_removed
- columns_before
- columns_after
- columns_removed

The CleaningReport is saved to `analyses.cleaning_report` in Supabase. The decisions list is also saved separately to `analyses.cleaning_decisions` for easy frontend display.

---

## Cleaned Dataset Persistence

After the CleaningReport is saved and verified, the Cleaner serializes the cleaned DataFrame to parquet format and uploads it to Supabase Storage:

- Bucket: `cleaned-datasets`
- Key: `{analysis_id}.parquet`

This parquet file is what the Explainer downloads when answering custom user questions. It ensures custom questions always run against the cleaned data — not the raw data.

After successful upload and verification, the original uploaded file is deleted from temporary local storage. If deletion fails, log the error but do not fail the pipeline.

---

## What the Cleaner Does NOT Do

- It does not run statistical analysis. That is the Analyzer's job.
- It does not generate charts.
- It does not produce insights or findings.
- It does not make assumptions about what the user wants without asking when the decision is significant.
- It does not apply the same rules to every dataset. Every decision is made in the context of this specific dataset's domain and provenance.

---

## System Prompt Location

`backend/prompts/cleaner_system.md`

The system prompt for this agent must be written against the full intelligence philosophy in `docs/intelligence-philosophy.md`. It must embody the Investigator Mindset. It must apply domain-specific reasoning to every decision. It must communicate clearly and honestly about what it is doing and why.

When writing the system prompt, switch to Opus model for the full depth of reasoning it requires.

---

## Test Fixture

Primary test fixture: `tests/fixtures/messy_data.csv` — deliberately messy with 30% missing values across multiple columns and duplicate rows.

The test must verify:
- Columns under 5% missing are filled correctly
- Columns between 5-30% missing are filled with a warning
- Columns over 30% missing trigger the pause behavior
- Outliers are investigated, not blindly removed
- The CleaningReport contains a decision entry for every action taken
- The parquet file is uploaded to Supabase Storage successfully
- The original uploaded file is deleted after successful upload

Test file: `tests/test_cleaner.py`

The Cleaner is considered complete only when all 14 Definition of Done criteria are met — see `CLAUDE.md`.

---

## LangSmith Tracing

Every Cleaner run must have LangSmith tracing attached via `create_tracer("cleaner")` from `backend/utils/langsmith_client.py`. No exceptions. The trace must be visible in the LangSmith dashboard before the Cleaner is marked complete.
