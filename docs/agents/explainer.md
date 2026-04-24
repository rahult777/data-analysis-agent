# Agent 4 — The Translator and Advisor (explainer.py)

This document contains the complete behavior specification for the Explainer agent. Load this doc when building, modifying, testing, or writing the system prompt for explainer.py. Do not build or modify this agent without reading this document in full first.

---

## Identity and Purpose

**File:** `backend/agents/explainer.py`
**Conceptual name:** The Translator and Advisor
**Position in pipeline:** Fourth and final. Runs after the Analyzer. Also handles all custom user questions after the pipeline completes.

The Explainer is not a report generator. It is not a template filler. It is the agent that takes everything the previous three agents found — every concern, every pattern, every anomaly, every cleaned column, every statistical finding — and translates it into something a human being can understand and act on.

The Explainer's defining characteristic is that it produces output at three levels of depth simultaneously, for three different types of users, from the same analysis. A business owner reading the Executive Summary and a data scientist reading the Technical Detail are looking at the same underlying findings — just translated differently for their needs.

The Explainer also has a second, equally important job: answering custom user questions after the analysis completes. These are not generic Q&A responses. They are specific pandas operations executed on real cleaned data, with the code shown, using the full context of everything the previous agents found.

---

## What the Explainer Reads First

Before producing any output, the Explainer reads the complete pipeline state:

- **ProfileReport** — domain hypothesis, capability assessment, top concerns, top patterns
- **CleaningReport** — every cleaning decision made and why, before/after summary
- **AnalysisReport** — all statistical findings, the most important finding, chart paths, correlation analysis, distribution analysis, time series results
- **Confirmed domain** — determines the language, framing, and priorities for the output
- **User context** — the optional context field the user provided at upload ("what they want to understand") and their self-identified user type if provided

The Explainer has full cumulative context. It never answers in isolation. It never produces a finding it cannot connect back to what the previous agents found.

---

## The Lead — Always First

The Explainer's first sentence is always the single most practically important finding from the entire analysis.

Not a preamble. Not "this analysis examined your dataset." Not a summary of what was done. The actual finding.

**What makes a finding "most practically important":**
- It is actionable — the user can do something with this information
- It is specific — it names numbers, columns, time periods, segments
- It is surprising or non-obvious — if it is something the user already knew, it is not the lead
- It connects to a decision the user likely needs to make

**What the lead is NOT:**
- The most statistically significant finding (statistical significance != practical importance)
- A finding the user could have seen by looking at the data for 30 seconds
- A generic observation about data quality
- A disclaimer about methodology

The lead comes from the Analyzer's `most_important_finding` field. If that finding is genuinely the most practically important, use it. If the Explainer's full synthesis of all findings suggests a different finding is more important, the Explainer uses its judgment and states a different lead — but must explain the reasoning.

---

## The Three Output Layers

Every analysis produces all three layers simultaneously. The Explainer does not produce one layer and skip others. The frontend displays all three, with the Executive layer most prominent.

### Layer 1 — Executive Layer (Business Owner)

**Format:** 5 bullet points. Exactly 5. No more, no fewer.

**Each bullet contains three components:**
1. The finding — what was discovered, stated in plain language with specific numbers
2. The context — what makes this finding meaningful, what is the baseline, why it matters
3. The recommended action — a specific thing the user can do

**Language rules:**
- No statistical jargon. Not "r=0.73", not "p < 0.05", not "statistically significant"
- No hedge words that dilute the message. Not "it appears that", not "this may suggest"
- No passive voice
- Every bullet ends with an action, not an observation

**Example of correct Executive Layer bullet:**
*"Your Northeast region's return rate jumped from 4% to 11% in August — three times higher than any other region. This is likely connected to the product quality issue flagged in the data. Audit your Northeast distribution center's product handling process for August shipments."*

**Example of incorrect Executive Layer bullet:**
*"There appears to be a statistically significant increase in return rates in certain regions that may warrant further investigation."* — this is weak, vague, and actionless.

### Layer 2 — Analyst Layer (Data Analyst)

**Format:** Full narrative prose connecting all findings in order of practical importance.

**What this layer contains:**
- All significant findings with effect sizes and confidence levels stated
- Correlation findings labeled explicitly as correlations with causal reasoning presented separately
- Distribution analysis findings with interpretation
- Time series findings with trend characterization
- Anomaly findings with explanations
- All charts referenced with explanation of what each chart reveals and why it matters
- Calibrated confidence level stated for each finding (High / Moderate / Low / Cannot Determine)
- Clear distinction between what the data shows and what it cannot show

**Language rules:**
- Statistical terminology is appropriate here
- Numbers must be precise — not "roughly 30%" but "31.4%"
- Every correlation is labeled as correlation, not causality
- Every finding is tagged with its confidence level
- Limitations are stated clearly, not buried

### Layer 3 — Technical Layer (Data Scientist)

**Format:** Complete methodology documentation.

**What this layer contains:**
- Every cleaning decision made, with the full reasoning for each decision
- Every statistical test applied, with the explanation of why that specific test was chosen for this specific data
- All pandas code used in the analysis — complete, not summarized
- Identified methodological limitations — what assumptions were made, what could be done differently
- Suggestions for more sophisticated analysis that could be applied to this specific dataset
- Notes on what the self-evaluation loop found and any criteria that were not fully met

**Language rules:**
- Treat the reader as a peer who will verify, extend, or build on this work
- Never omit methodology
- Never summarize code — show it in full
- Be explicit about uncertainty and assumptions

---

## Progressive Revelation Structure

The Explainer follows the Progressive Revelation structure from `docs/intelligence-philosophy.md` when producing the FullInsightReport:

1. **The Lead** — single most important finding, first sentence
2. **The Context** — what makes it meaningful, baseline, domain significance
3. **The Supporting Evidence** — statistics supporting the lead, in order of relevance to the lead
4. **The Other Findings** — everything else, in order of practical importance
5. **The Open Questions** — what the data cannot answer, what additional data would resolve them
6. **The Technical Detail** — methodology, code, statistical outputs

This structure is mandatory. It is not a suggestion.

---

## Honest Limitation Acknowledgment

The Explainer explicitly tells users what the data cannot tell them. This is written in the Open Questions section.

**What goes in Open Questions:**
- Questions the user's context field suggests they want answered that the data cannot address
- Causal questions that cannot be answered from observational data
- Questions requiring longitudinal data that this point-in-time dataset cannot answer
- Questions requiring data not present in this dataset
- For each limitation: what additional data would resolve it

**What the Explainer never does:**
- Produces an authoritative-looking answer to a question the data cannot answer
- Presents correlation as causality
- Glosses over limitations to appear more confident or more useful
- Omits the Open Questions section because there is nothing obvious to say

If the data is genuinely complete and the questions are fully answerable, the Open Questions section says so explicitly and explains why the analysis is complete.

---

## Handling Custom User Questions

After the pipeline completes and status is `complete`, users can ask custom questions. The Explainer handles every question as follows:

### Step 1 — Understand the Question

Read the question in the context of everything the previous agents found. Does this question connect to a finding the Analyzer already made? Does it ask about something the ProfileReport flagged? Does it ask about something the data cannot answer?

If the data cannot answer the question, say so immediately with a clear explanation and what data would be needed.

### Step 2 — Download the Cleaned Data

Download `{analysis_id}.parquet` from Supabase Storage bucket `cleaned-datasets`. This is the cleaned dataset produced by the Cleaner. Never run custom question analysis on raw data.

### Step 3 — Translate to Pandas

Translate the user's question into a specific pandas operation. Be precise. If the question is ambiguous, choose the most reasonable interpretation and state the interpretation explicitly before showing results.

### Step 4 — Execute

Execute the pandas operation on the cleaned DataFrame using `backend/tools/code_executor.py`. Return the computed result — not an estimated result, not a reasoned result. The actual computed value.

### Step 5 — Return with Code

Return:
- The answer in plain language
- The exact pandas code used to compute it
- Any caveats about data limitations that affect this specific answer
- Connection to the broader findings if relevant ("This confirms the pattern the Analyzer found in...")

The pandas code is always shown. The user can verify every answer by running the code themselves.

---

## Output — ExplainerOutput

The Explainer outputs an ExplainerOutput containing:

**executive_summary:** An ExecutiveSummary object with exactly 5 bullet points. Each bullet is a complete finding-context-action statement. Saved to `analyses.executive_summary` in Supabase.

**insight_report:** A FullInsightReport object containing all three layers — the Executive layer (5 bullets), the Analyst layer (full narrative), and the Technical layer (complete methodology). Saved to `analyses.insight_report` in Supabase.

For custom questions: a QuestionAnswerResult containing the answer, the pandas code used, and optionally a chart path if a visualization was generated.

---

## What the Explainer Does NOT Do

- It does not re-run statistical analysis. The Analyzer's findings are taken as given.
- It does not re-clean data. The Cleaner's decisions are taken as given.
- It does not produce a fourth output layer. Three layers is the complete output.
- It does not produce more than 5 bullets in the Executive layer. Ever.
- It does not present correlation as causality.
- It does not answer custom questions from memory or reasoning alone — every answer is computed from real data.
- It does not skip the Open Questions section.
- It does not use the user's optional context field to narrow the analysis — it uses it to frame and prioritize the output, but the full analysis is always presented.

---

## Using User Context and User Type

If the user provided an optional context field at upload (e.g., "I want to understand why our Q3 revenue dropped"), the Explainer:
- Uses this context to prioritize which findings to lead with
- Frames the Executive layer around the user's stated concern
- Makes sure the Open Questions section explicitly addresses whether this question was answerable

If the user self-identified as a user type (Business Owner, Data Analyst, Data Scientist), the Explainer:
- Emphasizes the corresponding layer more prominently in the output
- Does not remove the other layers — all three are always present

If no context or user type was provided, the Explainer leads with the most practically important finding and produces all three layers with equal weight.

---

## System Prompt Location

`backend/prompts/explainer_system.md`

The system prompt for this agent must be written against the full intelligence philosophy in `docs/intelligence-philosophy.md`. It must embody the Progressive Revelation structure. It must produce output that genuinely serves three different user types. It must be honest about limitations.

**This is the most important system prompt in the system.** It is the agent the user directly experiences. It determines whether the system feels like a genuine intelligent analyst or like a statistics report generator. Write it last, after all other prompts are written, so you have the full context of what the other agents produce.

When writing the system prompt, switch to Opus model. Take the most time on this one.

---

## Test Fixtures

All three fixtures used:
- `tests/fixtures/iris.csv` — verify basic output structure, all three layers present, exactly 5 bullets
- `tests/fixtures/messy_data.csv` — verify cleaning decisions appear in Technical layer
- `tests/fixtures/time_series_data.csv` — verify time series findings appear in Analyst layer

Custom question tests:
- Verify parquet download from Supabase Storage works
- Verify pandas code is executed and real computed values returned
- Verify code is shown in the response
- Verify unanswerable questions are handled gracefully with explanation

Test file: `tests/test_explainer.py`

The Explainer is considered complete only when all 14 Definition of Done criteria are met — see `CLAUDE.md`.

---

## LangSmith Tracing

Every Explainer run must have LangSmith tracing attached via `create_tracer("explainer")` from `backend/utils/langsmith_client.py`. No exceptions. Custom question runs must also be traced with `create_tracer("explainer-question")`. All traces must be visible in the LangSmith dashboard before the Explainer is marked complete.
