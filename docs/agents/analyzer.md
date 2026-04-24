# Agent 3 — The Deep Investigator (analyzer.py)

This document contains the complete behavior specification for the Analyzer agent. Load this doc when building, modifying, testing, or writing the system prompt for analyzer.py. Do not build or modify this agent without reading this document in full first.

---

## Identity and Purpose

**File:** `backend/agents/analyzer.py`
**Conceptual name:** The Deep Investigator
**Position in pipeline:** Third. Runs after the Cleaner, before the Explainer.

The Analyzer is not a statistics runner. It does not apply a fixed menu of statistical tests to every dataset uniformly. It is the agent that allocates analytical depth based on practical significance — spending more time and depth on findings that matter and less on findings that are obvious or routine.

The Analyzer's defining characteristic is its self-directed investigation agenda. It does not just compute what it was told to compute. It reads the ProfileReport, identifies what the Profiler flagged as important, and pursues those threads with genuine analytical curiosity. When it finds something surprising, it investigates fully before moving on.

A world-class analyst does not run the same report on every dataset. They read the data, notice what is interesting, and follow it. The Analyzer must reason the same way.

---

## What the Analyzer Reads First

Before running any analysis, the Analyzer reads from the pipeline state:

- **ProfileReport** — domain hypothesis, top 3 concerns, top 3 interesting patterns, column profiles, capability assessment
- **CleaningReport** — what was cleaned, what was flagged, what decisions were made
- **Confirmed domain** — determines which domain-specific analytical priorities apply

The Profiler's top 3 concerns are the Analyzer's mandatory investigation agenda. The Profiler's top 3 interesting patterns are the Analyzer's starting hypotheses. The Cleaner's decisions tell the Analyzer what the data looked like before cleaning and what caveats apply to the cleaned data.

---

## What Always Runs — Mandatory Analysis

Regardless of dataset type, domain, or size, the Analyzer always runs:

**Descriptive statistics for every column:**
- For numeric columns: count, mean, std, min, 25th percentile, median, 75th percentile, max, mode, skewness, kurtosis
- For categorical columns: count, unique count, top value, top value frequency, mode
- For datetime columns: earliest date, latest date, date range, most common time period

**Distribution analysis for every column:**
- Distribution type classification: normal, skewed left, skewed right, uniform, bimodal, categorical
- Histogram bin edges and counts for numeric columns

**Correlation matrix for all numeric column pairs:**
- Full NxN correlation matrix using Pearson correlation
- All pairs with correlation above 0.7 (positive or negative) flagged explicitly for investigation

**Value counts for all categorical columns:**
- Top 10 values with counts and percentages

**Time series detection:**
- If any datetime column is present: detect frequency (daily, monthly, irregular), detect trend (upward, downward, flat, seasonal), decompose if sufficient data exists

---

## What the Analyzer Investigates Specifically

In addition to the mandatory analysis, the Analyzer investigates:

**Every concern flagged by the Profiler** — these are not optional. If the Profiler flagged a concern, the Analyzer must address it explicitly. The self-evaluation checklist verifies this.

**Every column pair with correlation above 0.7** — strong correlations require investigation, not just reporting. For each strong correlation: state the correlation value, reason about possible causal mechanisms, identify potential confounders, state what additional data would be needed to establish causality. Never report a correlation without this reasoning.

**Every anomaly in the cleaned data** — values or patterns that are unexpected given the domain and the rest of the data. Each anomaly gets an explanation, even if the explanation is "I cannot determine the cause from this data alone."

**The single most surprising finding** — whatever the Analyzer finds most unexpected given the domain context gets a full deep-dive using all available analytical tools. This is the finding most likely to be the lead in the Explainer's Progressive Revelation structure.

---

## Superpowers Plugin Usage

The Analyzer uses the Superpowers plugin when:

**Multiple competing hypotheses exist for a significant finding** — rather than investigating one hypothesis at a time and stopping when one fits, spawn sub-agents to investigate multiple simultaneously. Each sub-agent investigates one hypothesis independently. The main Analyzer synthesizes findings and determines which hypothesis the evidence best supports.

**Distinct dataset subsets warrant simultaneous investigation** — if the data has a clear segmentation (by region, by product type, by time period) and the patterns appear to differ across segments, parallel investigation of segments reveals interactions that sequential investigation would miss.

When spawning sub-agents via Superpowers: define each sub-agent's specific hypothesis clearly, ensure each investigates independently without anchoring on the others' findings, synthesize all findings explicitly in the main AnalysisReport.

---

## Chart Generation Requirements

The Analyzer generates all charts using real computed data. Never estimated. Never approximated. Every chart is saved to `backend/outputs/charts/` with a descriptive filename including the analysis_id.

**Required charts — always generated:**

| Chart Type | Description | Library |
|-----------|-------------|---------|
| Histogram | One per numeric column showing value distribution | matplotlib/seaborn |
| Box plot | One per numeric column showing quartiles and outliers | matplotlib/seaborn |
| Correlation heatmap | Full NxN heatmap of all numeric column correlations | seaborn |
| Bar chart | One per categorical column showing top 10 value frequencies | matplotlib/seaborn |
| Line chart | Generated only if time series detected — shows trend over time | plotly |
| Scatter plot | One chart showing the highest-correlation column pair | plotly |

**Chart quality requirements:**
- All charts have descriptive titles
- All axes are labeled with units where applicable
- All charts have hover tooltips with exact values (plotly charts)
- All charts use the project's color scheme — no default matplotlib blue everywhere
- All charts are saved at sufficient resolution for web display

The list of all saved chart file paths is recorded in the AnalysisReport and saved to `analyses.chart_paths` in Supabase.

---

## The Self-Evaluation Loop

After completing all analysis, the Analyzer does not immediately proceed. It evaluates its own output against this exact checklist:

**(a) Did I analyze every concern flagged by the Comprehender in the ProfileReport?**
Each concern must have a corresponding finding or explicit statement in the AnalysisReport. "Concern X was investigated and found to have minimal impact on analysis because..." is acceptable. Silence is not.

**(b) Did I investigate all column pairs with correlation above 0.7?**
Every strong correlation must have: the correlation value stated, reasoning about possible causal mechanisms, identification of potential confounders, statement of what data would be needed for causal claims.

**(c) Did I provide an explanation for every anomaly identified?**
Every anomaly must have an explanation. If the cause cannot be determined from the data, the explanation must say so explicitly and state what additional data would clarify it.

**(d) Did I generate all required chart types?**
Verify: histograms for all numeric columns, box plots for all numeric columns, correlation heatmap, bar charts for all categorical columns, line chart if time series detected, scatter plot for highest correlation pair. Every chart must be saved and the path recorded.

**(e) Did I identify and clearly label the single most practically important finding?**
Not the most statistically significant finding. The most practically important one — the finding that, if the user knew nothing else from this analysis, they should know this. This finding must be labeled clearly at the top of the AnalysisReport.

**Loop behavior:**
- If any criterion is not met AND loop count is under 3: address the gap, increment loop count, re-evaluate
- If all criteria are met: proceed to the Explainer regardless of loop count
- If loop count reaches 3: proceed to the Explainer and note any unmet criteria explicitly in the AnalysisReport so the Explainer can account for them

The maximum is 3 loops. After 3 loops the Analyzer proceeds with whatever it has, documented honestly.

---

## Output — AnalysisReport

The Analyzer outputs a complete AnalysisReport containing:

**descriptive_stats:** One DescriptiveStats object per column with all computed statistics.

**correlation:** A CorrelationMatrix object with the full NxN correlation grid. Null if fewer than 2 numeric columns exist.

**distributions:** One DistributionInfo object per column with distribution type classification, histogram bins and counts for numeric columns.

**value_counts:** One ValueCounts object per categorical column with top values, counts, and percentages.

**time_series:** A TimeSeriesInfo object if a datetime column was detected — detected boolean, which column is the time axis, frequency, trend. Null otherwise.

**chart_paths:** List of all chart file paths saved during this run.

**most_important_finding:** The single most practically important finding, clearly labeled, written in plain language. This is what the Explainer leads with.

The AnalysisReport is saved to `analyses.analysis_report` in Supabase. Chart paths are saved separately to `analyses.chart_paths`. The data quality score is updated in `analyses.data_quality_score`.

---

## What the Analyzer Does NOT Do

- It does not clean data. Cleaning is already done.
- It does not generate the Executive Summary or insight report. That is the Explainer's job.
- It does not answer custom user questions. That is the Explainer's job.
- It does not present correlation as causality. Every correlation finding includes explicit causal reasoning and labeling.
- It does not skip the self-evaluation loop. Ever.
- It does not proceed after the first loop if the checklist is not met and loop count is under 3.

---

## Domain-Specific Analytical Priorities

The domain confirmed by the Profiler determines which analytical angles the Analyzer prioritizes:

**Financial data:** Period-over-period change analysis, fraud signal investigation for outliers, ratio analysis over absolute values, currency consistency verification.

**Medical data:** Clinically significant outlier annotation, missingness pattern analysis (is missingness informative?), sensitivity analysis showing results with and without flagged values.

**Retail data:** Seasonality decomposition before trend analysis, customer concentration analysis, return rate vs. sales rate comparison, promotional period identification.

**HR data:** Demographic distribution analysis with appropriate sensitivity, attrition pattern analysis if tenure data exists, manager-level aggregation analysis.

**Marketing data:** Attribution model assumption documentation, cohort analysis if acquisition date exists, vanity metric vs. actionable metric distinction.

**Logistics data:** Distribution analysis of on-time performance (never assume normal), variability analysis alongside average performance, route/geography effect identification.

**Manufacturing data:** Control chart analysis if sequential production data exists, defect clustering in time analysis, specification limit vs. statistical limit distinction.

---

## System Prompt Location

`backend/prompts/analyzer_system.md`

The system prompt for this agent must be written against the full intelligence philosophy in `docs/intelligence-philosophy.md`. It must embody the Investigator Mindset. It must apply domain-specific analytical priorities. It must never reduce to mechanical statistics running.

When writing the system prompt, switch to Opus model for the full depth of reasoning it requires.

---

## Test Fixtures

Basic functionality: `tests/fixtures/iris.csv` — verify all mandatory analysis runs, all charts generate, self-evaluation loop completes.

Cleaning integration: `tests/fixtures/messy_data.csv` — verify Analyzer correctly reads CleaningReport and accounts for cleaning decisions in its analysis.

Time series: `tests/fixtures/time_series_data.csv` — verify time series detection, line chart generation, trend identification.

Test file: `tests/test_analyzer.py`

The Analyzer is considered complete only when all 14 Definition of Done criteria are met — see `CLAUDE.md`.

---

## LangSmith Tracing

Every Analyzer run must have LangSmith tracing attached via `create_tracer("analyzer")` from `backend/utils/langsmith_client.py`. No exceptions. The trace must be visible in the LangSmith dashboard before the Analyzer is marked complete.
