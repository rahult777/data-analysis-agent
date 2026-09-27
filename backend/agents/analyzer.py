"""The Deep Investigator — Agent 3 in the data analysis pipeline.

Reads the cleaned dataset prepared by the Cleaner, computes the mandatory
descriptive analysis surface (descriptives, correlations, distributions,
value counts, time series), generates all required charts, runs the LLM
through a self-evaluation loop in which Python checks each response
structurally and retries only on a real failure (at most three calls), and
persists a complete AnalysisReport to Supabase for the Explainer to consume.
"""

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from anthropic import Anthropic

from backend.agents.profiler import (
    PipelineState,
    load_system_prompt,
    parse_json_response,
)
from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from backend.models.schemas import (
    AnalysisReport,
    AnalysisStatus,
    CorrelationMatrix,
    DescriptiveStats,
    DistributionInfo,
    TimeSeriesInfo,
    ValueCounts,
)
from backend.tools.viz_tools import generate_all_charts
from backend.utils.file_handler import cleanup_temp_file, download_from_storage
from backend.utils.langsmith_client import create_tracer
from backend.utils.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Output-token ceiling for the analyzer's synthesis call. Raised from 8000 after
# the first end-to-end run truncated mid-JSON (stop_reason="max_tokens"): the
# analyzer echoes the full computed stats blocks (which Python overwrites
# downstream), so the response is large. NOTE: 32000 is above the SDK's
# non-streaming ceiling (~21.3K, beyond which messages.create raises
# "Streaming is required..."), so the synthesis call MUST use messages.stream().
# See errors.md 2026-06-03 / 2026-06-04.
ANALYZER_MAX_TOKENS = 32000

# The Pearson reliability floor (analyzer_system.md Section 6): a correlation
# resting on fewer complete pairs than this is Cannot Determine, whatever label
# the model gave it. Enforced in Python by apply_correlation_floor (Build I).
CORRELATION_MIN_PAIRS = 30

# The self-evaluation loop's call cap: the first analysis call plus at most two
# retries (Build J). Each retry is a fresh call; the model does not see its
# previous response, only the criteria it failed.
ANALYZER_MAX_CALLS = 3

class AnalyzerResponseTruncated(ValueError):
    """The Analyzer's response stopped at max_tokens before its JSON was complete."""


class AnalyzerResponseEmpty(ValueError):
    """The Analyzer's response had no text content block (e.g. a refusal)."""


class AnalyzerResponseNotJSON(ValueError):
    """The Analyzer's response text could not be parsed as JSON."""


def _unusable_reason(exc: Exception) -> str:
    """A short, user-safe description of why a retry could not be used (the full
    exception, which can hold raw model text, goes only to the log). The three
    response failures are raised as their own types where they happen; anything
    else is the call itself failing."""
    if isinstance(exc, AnalyzerResponseTruncated):
        return "the response was truncated at the output-token ceiling"
    if isinstance(exc, AnalyzerResponseEmpty):
        return "the response had no text content"
    if isinstance(exc, AnalyzerResponseNotJSON):
        return "the response was not valid JSON"
    return f"the call failed ({type(exc).__name__})"


_VALID_CONFIDENCE_LEVELS = frozenset({"High", "Moderate", "Low", "Cannot Determine"})
_CAUSALITY_LABEL = "This is correlation, not causation."


def sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None and tuples with lists.

    Returns a NEW object — does not mutate in place. Reassign the result.
    """
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    if isinstance(obj, tuple):
        return [sanitize_for_json(item) for item in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


async def load_cleaned_dataframe(analysis_id: str) -> pd.DataFrame:
    """Download the cleaned parquet from Supabase Storage and load it."""
    try:
        file_path = await download_from_storage(analysis_id)
        df = await asyncio.to_thread(pd.read_parquet, file_path)
        return df
    except Exception as exc:
        raise ValueError(
            f"Failed to load cleaned dataframe for analysis_id={analysis_id}: {exc}"
        ) from exc


def _is_id_column(name: str) -> bool:
    """True if `name` contains "id" as a standalone name component —
    exact match, or separated by _/-/space, or a camelCase Id/ID
    boundary. Does NOT match "id" as a mere substring (e.g. "width",
    "valid", "paid_amount" are NOT id columns).

    Known, accepted limitations (not matched): an ID acronym immediately
    followed by another capitalized word, anywhere in the name
    ("IDCustomer", "CustomerIDNumber"), "uuid"/"guid", a trailing digit
    or plural ("id1", "related_ids"), and separator-less concatenations
    ("userid", "customerid", "USERID") — see decisions.md 2026-09-19."""
    # Insert a boundary before a capital letter that follows a
    # lowercase letter or digit (camelCase word boundary).
    boundary_inserted = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name)
    tokens = re.split(r'[^a-zA-Z0-9]+', boundary_inserted)
    return any(token.lower() == "id" for token in tokens if token)


def classify_columns(
    df: pd.DataFrame,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Classify columns into (numeric, categorical, datetime).

    Numeric: pandas number dtypes, excluding columns whose name has "id" as a
    standalone name component (see _is_id_column) — IDs are stored as integers
    but are not numeric in the analytical sense.
    Categorical: object dtypes plus boolean columns.
    Datetime: the first column whose dtype name contains "datetime", or None.
    """
    raw_numeric = df.select_dtypes(include="number").columns.tolist()
    numeric_columns = [c for c in raw_numeric if not _is_id_column(c)]

    object_columns = df.select_dtypes(include="object").columns.tolist()
    bool_columns = df.select_dtypes(include="bool").columns.tolist()
    categorical_columns = list(object_columns) + list(bool_columns)

    datetime_column: Optional[str] = None
    for col in df.columns:
        if "datetime" in str(df[col].dtype).lower():
            datetime_column = col
            break

    return numeric_columns, categorical_columns, datetime_column


def _safe_stat(func) -> Optional[float]:
    """Run a stat-producing callable; return None on any failure."""
    try:
        value = func()
        if value is None:
            return None
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    except Exception:
        return None


def compute_descriptive_stats(
    df: pd.DataFrame,
    numeric_columns: List[str],
    categorical_columns: List[str],
) -> dict:
    """Compute descriptive statistics keyed by column name."""
    stats: Dict[str, Dict[str, Any]] = {}

    for col in numeric_columns:
        series = df[col]
        col_stats: Dict[str, Any] = {
            "count": int(series.count()),
            "mean": _safe_stat(lambda s=series: s.mean()),
            "std": _safe_stat(lambda s=series: s.std()),
            "min": _safe_stat(lambda s=series: s.min()),
            "p25": _safe_stat(lambda s=series: s.quantile(0.25)),
            "median": _safe_stat(lambda s=series: s.median()),
            "p75": _safe_stat(lambda s=series: s.quantile(0.75)),
            "max": _safe_stat(lambda s=series: s.max()),
            "skewness": _safe_stat(lambda s=series: s.skew()),
            "kurtosis": _safe_stat(lambda s=series: s.kurtosis()),
        }
        try:
            mode_vals = series.mode(dropna=True)
            col_stats["mode"] = (
                float(mode_vals.iloc[0]) if len(mode_vals) > 0 else None
            )
        except Exception:
            col_stats["mode"] = None
        stats[col] = col_stats

    for col in categorical_columns:
        series = df[col]
        try:
            value_counts = series.value_counts(dropna=True)
            top_value = (
                str(value_counts.index[0]) if len(value_counts) > 0 else None
            )
            top_value_frequency = (
                int(value_counts.iloc[0]) if len(value_counts) > 0 else 0
            )
        except Exception:
            top_value = None
            top_value_frequency = 0

        try:
            mode_vals = series.mode(dropna=True)
            mode_value = str(mode_vals.iloc[0]) if len(mode_vals) > 0 else None
        except Exception:
            mode_value = None

        try:
            unique_count = int(series.nunique(dropna=True))
        except Exception:
            unique_count = 0

        stats[col] = {
            "count": int(series.count()),
            "unique_count": unique_count,
            "top_value": top_value,
            "top_value_frequency": top_value_frequency,
            "mode": mode_value,
        }

    return stats


def count_complete_pairs(df: pd.DataFrame, col_a: str, col_b: str) -> int:
    """Number of rows where both columns hold a present, finite number — the
    rows df.corr() uses for this pair. pandas computes Pearson on pairwise
    complete observations, converting with to_numpy(dtype=float,
    na_value=np.nan) and masking with np.isfinite, so an inf is excluded as well
    as a NaN (where a plain dropna() would still count it). The notna() masks
    also exclude a timedelta NaT, which that conversion turns into a finite
    sentinel."""
    values_a = df[col_a].to_numpy(dtype=float, na_value=np.nan)
    values_b = df[col_b].to_numpy(dtype=float, na_value=np.nan)
    complete = (
        np.isfinite(values_a)
        & np.isfinite(values_b)
        & df[col_a].notna().to_numpy()
        & df[col_b].notna().to_numpy()
    )
    return int(complete.sum())


def compute_correlation_matrix(
    df: pd.DataFrame,
    numeric_columns: List[str],
) -> Optional[dict]:
    """Compute the full Pearson correlation matrix with diagonal masking.

    Returns None if fewer than 2 numeric columns exist. Otherwise returns
    a dict with sanitized matrix, strong_pairs (|r| > 0.7, off-diagonal, each
    with its number of complete pairs `n`), highest_pair (list[col1, col2]),
    and highest_value (float or None).
    """
    if len(numeric_columns) < 2:
        return None

    corr_df = df[numeric_columns].corr()

    # Diagonal masking — operate on a copy so original corr_df is untouched.
    masked = corr_df.values.copy()
    np.fill_diagonal(masked, np.nan)
    masked_df = pd.DataFrame(masked, index=corr_df.index, columns=corr_df.columns)

    matrix_dict = corr_df.to_dict()
    sanitized_matrix = sanitize_for_json(matrix_dict)

    strong_pairs: List[Dict[str, Any]] = []
    cols = list(corr_df.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            value = masked_df.iloc[i, j]
            if pd.notna(value) and abs(value) > 0.7:
                strong_pairs.append({
                    "col1": cols[i],
                    "col2": cols[j],
                    "correlation_value": float(value),
                    "n": count_complete_pairs(df, cols[i], cols[j]),
                })

    highest_pair: Optional[List[str]] = None
    highest_value: Optional[float] = None
    abs_masked = masked_df.abs()
    if abs_masked.notna().any().any():
        flat = abs_masked.stack()
        if not flat.empty:
            max_idx = flat.idxmax()
            highest_pair = [str(max_idx[0]), str(max_idx[1])]
            highest_value = float(masked_df.loc[max_idx[0], max_idx[1]])

    return {
        "matrix": sanitized_matrix,
        "strong_pairs": strong_pairs,
        "highest_pair": highest_pair,
        "highest_value": highest_value,
    }


def classify_distributions(
    df: pd.DataFrame,
    numeric_columns: List[str],
) -> dict:
    """Classify each numeric column's distribution shape via skew/kurtosis."""
    distributions: Dict[str, Dict[str, Any]] = {}

    for col in numeric_columns:
        series = df[col]
        try:
            skewness_raw = series.skew()
            kurtosis_raw = series.kurtosis()
        except Exception:
            skewness_raw = float("nan")
            kurtosis_raw = float("nan")

        skewness_is_nan = (
            skewness_raw is None
            or (isinstance(skewness_raw, float) and math.isnan(skewness_raw))
        )
        kurtosis_is_nan = (
            kurtosis_raw is None
            or (isinstance(kurtosis_raw, float) and math.isnan(kurtosis_raw))
        )

        if skewness_is_nan or kurtosis_is_nan:
            distribution_type = "unknown"
        elif abs(skewness_raw) < 0.5:
            distribution_type = "normal"
        elif skewness_raw >= 0.5:
            distribution_type = "skewed_right"
        elif skewness_raw <= -0.5:
            distribution_type = "skewed_left"
        elif kurtosis_raw < -1:
            distribution_type = "bimodal"
        else:
            distribution_type = "other"

        distributions[col] = {
            "distribution_type": distribution_type,
            "skewness": None if skewness_is_nan else float(skewness_raw),
            "kurtosis": None if kurtosis_is_nan else float(kurtosis_raw),
        }

    return distributions


def compute_value_counts(
    df: pd.DataFrame,
    categorical_columns: List[str],
    top_n: int = 10,
) -> dict:
    """Compute top-N value counts with percentages for each categorical column."""
    result: Dict[str, List[Dict[str, Any]]] = {}

    for col in categorical_columns:
        series = df[col]
        total = int(series.count())
        if total == 0:
            result[col] = []
            continue
        try:
            counts = series.value_counts(dropna=True).head(top_n)
        except Exception:
            result[col] = []
            continue

        entries = [
            {
                "value": str(idx),
                "count": int(count),
                "percentage": round(float(count) / total * 100.0, 2),
            }
            for idx, count in counts.items()
        ]
        result[col] = entries

    return result


def detect_time_series(
    df: pd.DataFrame,
    datetime_column: Optional[str],
    numeric_columns: List[str],
) -> Tuple[Optional[dict], Optional[str]]:
    """Detect time series properties and the recommended value column.

    Returns a tuple of (time_series_info_dict, recommended_value_column).
    The dict matches TimeSeriesInfo schema exactly: detected, datetime_column,
    frequency, trend. The recommended_value_column is an internal helper used
    to drive line-chart and trend computation; it is NOT a schema field.
    """
    if datetime_column is None or datetime_column not in df.columns:
        return None, None

    df_sorted = df.sort_values(by=datetime_column).reset_index(drop=True)

    deltas = df_sorted[datetime_column].diff().dropna()
    if len(deltas) == 0:
        frequency = "irregular"
    else:
        try:
            median_delta = deltas.median()
            days = float(median_delta.total_seconds()) / 86400.0
        except Exception:
            days = float("inf")
        if days <= 1:
            frequency = "daily"
        elif days <= 7:
            frequency = "weekly"
        elif days <= 31:
            frequency = "monthly"
        else:
            frequency = "irregular"

    recommended_value_column: Optional[str] = None
    if numeric_columns:
        try:
            variances = df_sorted[numeric_columns].var(numeric_only=True)
            variances = variances.dropna()
            if not variances.empty:
                recommended_value_column = str(variances.idxmax())
        except Exception:
            recommended_value_column = None

    trend = "flat"
    if recommended_value_column is not None:
        try:
            y_full = df_sorted[recommended_value_column].to_numpy(dtype=float)
            mask = ~np.isnan(y_full)
            y = y_full[mask]
            x = np.arange(len(df_sorted))[mask]
            if len(y) >= 2:
                slope = float(np.polyfit(x, y, 1)[0])
                if abs(slope) < 0.001:
                    trend = "flat"
                elif slope > 0:
                    trend = "upward"
                else:
                    trend = "downward"
        except Exception:
            trend = "flat"

    info = {
        "detected": True,
        "datetime_column": str(datetime_column),
        "frequency": frequency,
        "trend": trend,
    }
    return info, recommended_value_column


def compute_data_quality_score(
    df: pd.DataFrame,
    cleaning_report: Optional[dict],
) -> float:
    """Compute a data quality score in [0.1, 1.0] from the cleaned dataset."""
    score = 1.0

    missing_columns = sum(1 for col in df.columns if df[col].isna().any())
    score -= min(missing_columns * 0.1, 0.3)

    if df.duplicated().any():
        score -= 0.1

    if cleaning_report is not None:
        decisions = cleaning_report.get("decisions") or []
        for decision in decisions:
            action_text = str(decision.get("action") or "").lower()
            if "outlier" in action_text or "flag" in action_text:
                score -= 0.1
                break

    score = max(score, 0.1)
    return round(score, 2)


def build_analyzer_message(
    analysis_id: str,
    profile_report: Optional[dict],
    cleaning_report: Optional[dict],
    descriptive_stats: dict,
    correlation_result: Optional[dict],
    distributions: dict,
    value_counts: dict,
    time_series_result: Optional[dict],
    domain_hypothesis: str,
    provenance_hypothesis: str,
    top_3_concerns: list,
    top_3_patterns: list,
    user_context: Optional[str],
    interactions_detected: Optional[list],
    failed_criteria: Optional[List[Dict[str, str]]],
) -> str:
    """Build the Anthropic user message for the analyzer LLM call.

    The Profiler's concerns are sent with Python-assigned concern_ids (see
    number_concerns), which the model copies into profiler_concerns_addressed
    and check_self_evaluation matches structurally."""
    cleaning_summary: Optional[dict] = None
    if cleaning_report is not None:
        cleaning_summary = {
            "decisions": cleaning_report.get("decisions"),
            "summary": cleaning_report.get("summary"),
            "interactions_detected": cleaning_report.get("interactions_detected"),
            "profiler_concerns_addressed": cleaning_report.get(
                "profiler_concerns_addressed"
            ),
        }

    message_data: Dict[str, Any] = {
        "analysis_id": analysis_id,
        "PROVENANCE_HYPOTHESIS": provenance_hypothesis,
        "DOMAIN_HYPOTHESIS": domain_hypothesis,
        "MANDATORY_INVESTIGATION_AGENDA": {
            "label": "MANDATORY INVESTIGATION AGENDA — address every one of these",
            "concerns": number_concerns(top_3_concerns),
        },
        "STARTING_HYPOTHESES": {
            "label": "STARTING HYPOTHESES — investigate these",
            "patterns": top_3_patterns,
        },
        "profile_report": profile_report,
        "cleaning_report_summary": cleaning_summary,
        "descriptive_stats": descriptive_stats,
        "correlation": correlation_result,
        "distributions": distributions,
        "value_counts": value_counts,
        "time_series": time_series_result,
    }

    if user_context:
        message_data["USER_INTENT"] = {
            "label": "USER INTENT — the user wants to understand:",
            "context": user_context,
        }

    if interactions_detected:
        message_data["interactions_detected"] = interactions_detected

    if failed_criteria:
        message_data["SELF_EVALUATION_FAILED"] = {
            "label": (
                "SELF-EVALUATION FAILED — the system checked your earlier "
                "responses in this analysis and these criteria were not met; "
                "meet all of them this time."
            ),
            "failed_criteria": failed_criteria,
        }

    sanitized = sanitize_for_json(message_data)
    return json.dumps(sanitized, default=str)


def number_concerns(top_3_concerns: Any) -> List[Dict[str, Any]]:
    """The Profiler's concerns, each with a Python-assigned concern_id "C1".."Cn"
    in their order, for the Analyzer's message only (the stored profile_report is
    not changed). A concern that is not an object is carried as its "issue"; a
    non-empty value that is not a list is treated as one concern."""
    if not isinstance(top_3_concerns, list):
        if not top_3_concerns:
            return []
        logger.warning(
            "profiler_top_3_concerns is %s, not a list — treated as one concern",
            type(top_3_concerns).__name__,
        )
        top_3_concerns = [top_3_concerns]
    numbered: List[Dict[str, Any]] = []
    for index, concern in enumerate(top_3_concerns, start=1):
        fields = concern if isinstance(concern, dict) else {"issue": concern}
        numbered.append({
            "concern_id": f"C{index}",
            **{key: value for key, value in fields.items() if key != "concern_id"},
        })
    return numbered


def _merge_failures(
    kept_failures: List[Dict[str, str]], last_failures: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """The feedback for the next call: every criterion that failed on the kept
    response or on the latest parsed one, the latest's record winning, so a
    retry hears about the kept response's gaps too."""
    merged: Dict[str, Dict[str, str]] = {f["criterion"]: f for f in kept_failures}
    merged.update({f["criterion"]: f for f in last_failures})
    return list(merged.values())


def _text(value: Any) -> str:
    """A string field's stripped text; "" for anything that is not a string."""
    return value.strip() if isinstance(value, str) else ""


def _count_texts(value: Any) -> int:
    """How many non-empty strings a list field holds; 0 if it is not a list."""
    if not isinstance(value, list):
        return 0
    return sum(1 for item in value if _text(item))


def _concern_lacks(entry: dict) -> List[str]:
    """What a profiler_concerns_addressed entry lacks for criterion (a)."""
    lacks: List[str] = []
    if not _text(entry.get("finding")):
        lacks.append("an empty finding")
    if entry.get("confidence_level") not in _VALID_CONFIDENCE_LEVELS:
        lacks.append("no valid confidence_level")
    return lacks


def _missing_correlation_elements(entry: dict) -> List[str]:
    """The Step 4 elements a strong-correlation entry lacks (analyzer_system.md
    Step 4 and criterion (b): r, n, confidence level, at least two mechanisms,
    at least two confounders, what would establish causality, the exact label)."""
    missing: List[str] = []
    # r and n need only be present: Python overwrites both with its own values
    # after the loop (apply_correlation_floor), so their form is not checked.
    if entry.get("r") is None:
        missing.append("r")
    if entry.get("n") is None:
        missing.append("n")
    if entry.get("confidence_level") not in _VALID_CONFIDENCE_LEVELS:
        missing.append("a valid confidence_level")
    if _count_texts(entry.get("mechanisms")) < 2:
        missing.append("at least two mechanisms")
    if _count_texts(entry.get("confounders")) < 2:
        missing.append("at least two confounders")
    if not _text(entry.get("what_would_establish_causality")):
        missing.append("what_would_establish_causality")
    if _text(entry.get("causality_label")) != _CAUSALITY_LABEL:
        missing.append(f'the exact causality_label "{_CAUSALITY_LABEL}"')
    return missing


def check_self_evaluation(
    analysis_response: Any,
    top_3_concerns: list,
    correlation_result: Optional[dict],
) -> Tuple[bool, List[Dict[str, str]]]:
    """Check the model's response structurally (Build J). Returns (all_passed,
    failures), one {criterion, reason} per failed criterion, the reason naming
    the concrete items. Never raises on a malformed response.

    (a) every concern_id sent by number_concerns has a profiler_concerns_addressed
        entry with a non-empty finding and a valid confidence_level;
    (b) every Python strong pair has a correlation.strong_correlations entry
        (exact column names, either order) with every Step 4 element; entries for
        other pairs are ignored;
    (e) most_important_finding and most_surprising_finding are non-empty and not
        identical.
    (c) is not checked: the output has no anomaly field to check it against
    (errors.md 2026-09-27). (d) is not a criterion here: charts are rendered by
    the system before the call, so a retry cannot change them; analyzer_node
    records empty charts instead.
    """
    failures: List[Dict[str, str]] = []
    response = analysis_response
    if not isinstance(response, dict):
        failures.append({
            "criterion": "(response)",
            "reason": (
                f"The response is a JSON {type(response).__name__}, not the "
                "AnalysisReport object."
            ),
        })
        response = {}

    # (a) Every Profiler concern addressed, by concern_id.
    concern_ids = [c["concern_id"] for c in number_concerns(top_3_concerns)]
    if concern_ids:
        entries = response.get("profiler_concerns_addressed")
        if not isinstance(entries, list):
            failures.append({
                "criterion": "(a)",
                "reason": (
                    "profiler_concerns_addressed is missing or not a list, so no "
                    f"concern is addressed ({', '.join(concern_ids)})."
                ),
            })
        else:
            by_id: Dict[str, List[dict]] = {}
            for entry in entries:
                if isinstance(entry, dict) and _text(entry.get("concern_id")):
                    by_id.setdefault(_text(entry["concern_id"]), []).append(entry)
            problems: List[str] = []
            for concern_id in concern_ids:
                candidates = by_id.get(concern_id, [])
                if not candidates:
                    problems.append(f"{concern_id} has no entry")
                elif not any(
                    _text(entry.get("finding"))
                    and entry.get("confidence_level") in _VALID_CONFIDENCE_LEVELS
                    for entry in candidates
                ):
                    lacks = min((_concern_lacks(e) for e in candidates), key=len)
                    problems.append(f"{concern_id} has {' and '.join(lacks)}")
            if problems:
                failures.append({
                    "criterion": "(a)",
                    "reason": "Profiler concerns not addressed: " + "; ".join(problems) + ".",
                })

    # (b) Every Python strong pair investigated, by exact column names.
    strong_pairs = (
        correlation_result.get("strong_pairs") if isinstance(correlation_result, dict) else None
    )
    if isinstance(strong_pairs, list) and strong_pairs:
        correlation = response.get("correlation")
        entries = correlation.get("strong_correlations") if isinstance(correlation, dict) else None
        by_pair: Dict[frozenset, List[dict]] = {}
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            col_a, col_b = entry.get("column_a"), entry.get("column_b")
            if isinstance(col_a, str) and isinstance(col_b, str) and col_a != col_b:
                by_pair.setdefault(frozenset((col_a, col_b)), []).append(entry)
        problems = []
        for pair in strong_pairs:
            if not isinstance(pair, dict):
                continue
            col1, col2 = pair.get("col1"), pair.get("col2")
            candidates = by_pair.get(frozenset((col1, col2)), [])
            if not candidates:
                problems.append(f"{col1} × {col2} has no entry")
            elif all(_missing_correlation_elements(entry) for entry in candidates):
                lacks = min((_missing_correlation_elements(e) for e in candidates), key=len)
                problems.append(f"{col1} × {col2} lacks {', '.join(lacks)}")
        if problems:
            failures.append({
                "criterion": "(b)",
                "reason": "Strong correlations not fully investigated: " + "; ".join(problems) + ".",
            })

    # (e) Both findings present and distinct.
    most_important = _text(response.get("most_important_finding"))
    most_surprising = _text(response.get("most_surprising_finding"))
    if not most_important or not most_surprising:
        empty = [
            name
            for name, value in (
                ("most_important_finding", most_important),
                ("most_surprising_finding", most_surprising),
            )
            if not value
        ]
        verb = "are" if len(empty) == 2 else "is"
        failures.append({"criterion": "(e)", "reason": f"{' and '.join(empty)} {verb} empty."})
    elif most_important == most_surprising:
        failures.append({
            "criterion": "(e)",
            "reason": "most_important_finding and most_surprising_finding are identical.",
        })

    return (len(failures) == 0, failures)


_CANNOT_DETERMINE = "Cannot Determine"


def _is_matrix_pair(matrix: dict, df: pd.DataFrame, col_a: Any, col_b: Any) -> bool:
    """True if {col_a, col_b} is an off-diagonal pair of Python's correlation
    matrix (and both columns are in the frame it was computed from). Exact
    column names in either order: no case or whitespace normalization, no fuzzy
    matching. The same column twice is not a pair."""
    if not isinstance(col_a, str) or not isinstance(col_b, str) or col_a == col_b:
        return False
    row_a = matrix.get(col_a)
    return (
        isinstance(row_a, dict)
        and col_b in row_a
        and col_b in matrix
        and col_a in df.columns
        and col_b in df.columns
    )


def apply_correlation_floor(
    analysis_response: dict,
    correlation_result: Optional[dict],
    df: pd.DataFrame,
) -> None:
    """Enforce the Pearson reliability floor on the model's correlation output,
    in place (Build I — the prompt alone did not hold it: errors.md 2026-09-21).

    Each entry of analysis_response["correlation"]["strong_correlations"] that
    names a pair of Python's correlation matrix gets Python's r and complete-pair
    n; below CORRELATION_MIN_PAIRS, or where Python's r is undefined (None), its
    confidence_level becomes Cannot Determine with a floor_override record. An
    entry naming any other pair is moved to
    correlation.unverified_correlations with a system reason. The parent
    correlation.confidence_level is lowered the same way when Python found strong
    pairs and every one rests on fewer than CORRELATION_MIN_PAIRS complete pairs.
    Labels are only ever lowered, never raised. Never raises: a correlation
    object, strong_correlations list or entry that is malformed is left as it is
    and logged; the parent rule reads only Python's strong pairs, so it still
    applies when the model's entries are malformed.
    """
    if not isinstance(analysis_response, dict):
        logger.warning(
            "Correlation floor skipped: the analysis response is %s, not an object",
            type(analysis_response).__name__,
        )
        return
    correlation = analysis_response.get("correlation")
    if correlation is None:
        return
    if not isinstance(correlation, dict):
        logger.warning(
            "Correlation floor skipped: correlation is %s, not an object",
            type(correlation).__name__,
        )
        return

    matrix = correlation_result.get("matrix") if isinstance(correlation_result, dict) else None
    if not isinstance(matrix, dict):
        matrix = {}

    entries = correlation.get("strong_correlations")
    if isinstance(entries, list):
        kept: List[Any] = []
        unverified: List[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                logger.warning(
                    "Correlation floor: a strong_correlations entry is %s, not an "
                    "object — left unchanged",
                    type(entry).__name__,
                )
                kept.append(entry)
                continue
            col_a, col_b = entry.get("column_a"), entry.get("column_b")
            if not _is_matrix_pair(matrix, df, col_a, col_b):
                unverified.append({
                    "column_a": col_a,
                    "column_b": col_b,
                    "reason": (
                        f"System check: {col_a} × {col_b} is not a pair in the "
                        "system's correlation matrix (a column is non-numeric, "
                        "excluded or absent), so its r and n could not be verified. "
                        "It is not reported as a correlation."
                    ),
                    "original_entry": entry,
                })
                continue
            n = count_complete_pairs(df, col_a, col_b)
            r = matrix[col_a].get(col_b)
            entry["r"] = r
            entry["n"] = n
            original = entry.get("confidence_level")
            reason: Optional[str] = None
            if n < CORRELATION_MIN_PAIRS:
                reason = (
                    f"System check: Python counted {n} complete pairs for "
                    f"{col_a} × {col_b}, below the {CORRELATION_MIN_PAIRS}-pair "
                    "reliability floor, so the confidence is Cannot Determine."
                )
            elif r is None:
                # pandas returns NaN (sanitized to None) when r is undefined,
                # e.g. a column constant over the pair's complete rows.
                reason = (
                    f"System check: Python could not compute r for {col_a} × "
                    f"{col_b} (r is undefined on their {n} complete pairs, e.g. a "
                    "constant column), so the confidence is Cannot Determine."
                )
            if reason is not None and original != _CANNOT_DETERMINE:
                entry["confidence_level"] = _CANNOT_DETERMINE
                entry["floor_override"] = {
                    "original_confidence_level": original,
                    "reason": reason,
                }
            kept.append(entry)
        correlation["strong_correlations"] = kept
        correlation["unverified_correlations"] = unverified
        if unverified:
            logger.info(
                "Correlation floor: %d model entries name pairs outside the "
                "correlation matrix and were moved to unverified_correlations",
                len(unverified),
            )
    else:
        logger.warning(
            "Correlation floor: strong_correlations is %s, not a list — left unchanged",
            type(entries).__name__,
        )

    strong_pairs = (
        correlation_result.get("strong_pairs") if isinstance(correlation_result, dict) else None
    )
    pair_counts = (
        [pair.get("n") if isinstance(pair, dict) else None for pair in strong_pairs]
        if isinstance(strong_pairs, list)
        else []
    )
    if pair_counts and all(
        isinstance(n, int) and n < CORRELATION_MIN_PAIRS for n in pair_counts
    ):
        original = correlation.get("confidence_level")
        if original != _CANNOT_DETERMINE:
            correlation["confidence_level"] = _CANNOT_DETERMINE
            correlation["floor_override"] = {
                "original_confidence_level": original,
                "reason": (
                    "System check: every strong correlation rests on fewer than "
                    f"{CORRELATION_MIN_PAIRS} complete pairs (lowest n = "
                    f"{min(pair_counts)}), so the overall correlation confidence "
                    "is Cannot Determine."
                ),
            }


async def analyzer_node(state: PipelineState) -> dict:
    """LangGraph node — runs the full Deep Investigator pipeline."""
    analysis_id = state["analysis_id"]

    try:
        # LangSmith trace handle (callbacks attached at graph.invoke level).
        tracer = create_tracer("analyzer")  # noqa: F841

        # Memory MCP read — eight inheritance keys, sourced from pipeline state.
        domain_hypothesis = state.get("profiler_domain_hypothesis") or ""
        provenance_hypothesis = state.get("profiler_provenance_hypothesis") or ""
        # Numbered once here (concern_id "C1".."Cn"); number_concerns is idempotent,
        # so the message builder and the check number the same list again.
        top_3_concerns = number_concerns(state.get("profiler_top_3_concerns") or [])
        top_3_patterns = state.get("profiler_top_3_patterns") or []
        cleaner_key_decisions = state.get("cleaner_key_decisions") or []
        cleaner_excluded_columns = state.get("cleaner_excluded_columns") or []
        cleaner_outliers_handled = state.get("cleaner_outliers_handled") or {}
        cleaner_user_decisions_incorporated = (
            state.get("cleaner_user_decisions_incorporated") or []
        )
        logger.info(
            "Memory MCP read for analyzer (analysis_id=%s): "
            "profiler.domain_hypothesis=%r, profiler.provenance_hypothesis=%r, "
            "profiler.top_3_concerns count=%d, profiler.top_3_patterns count=%d, "
            "cleaner.key_cleaning_decisions count=%d, "
            "cleaner.excluded_columns count=%d, "
            "cleaner.outliers_handled keys=%d, "
            "cleaner.user_decisions_incorporated count=%d",
            analysis_id,
            domain_hypothesis,
            provenance_hypothesis,
            len(top_3_concerns) if isinstance(top_3_concerns, list) else 0,
            len(top_3_patterns) if isinstance(top_3_patterns, list) else 0,
            len(cleaner_key_decisions)
            if isinstance(cleaner_key_decisions, list)
            else 0,
            len(cleaner_excluded_columns)
            if isinstance(cleaner_excluded_columns, list)
            else 0,
            len(cleaner_outliers_handled)
            if isinstance(cleaner_outliers_handled, dict)
            else 0,
            len(cleaner_user_decisions_incorporated)
            if isinstance(cleaner_user_decisions_incorporated, list)
            else 0,
        )

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "analyzing",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )

        df = await load_cleaned_dataframe(analysis_id)

        try:
            await cleanup_temp_file(f"{analysis_id}.parquet")
        except Exception as exc:
            logger.warning(
                "Failed to clean up local parquet for analysis_id=%s: %s",
                analysis_id,
                exc,
            )

        numeric_columns, categorical_columns, datetime_column = classify_columns(df)

        descriptive_stats = await asyncio.to_thread(
            compute_descriptive_stats, df, numeric_columns, categorical_columns
        )
        correlation_result = await asyncio.to_thread(
            compute_correlation_matrix, df, numeric_columns
        )
        distributions = await asyncio.to_thread(
            classify_distributions, df, numeric_columns
        )
        value_counts = await asyncio.to_thread(
            compute_value_counts, df, categorical_columns
        )
        time_series_result, time_series_value_column = await asyncio.to_thread(
            detect_time_series, df, datetime_column, numeric_columns
        )
        data_quality_score = await asyncio.to_thread(
            compute_data_quality_score, df, state.get("cleaning_report")
        )

        profile_report = state.get("profile_report")
        cleaning_report = state.get("cleaning_report")
        user_context = state.get("context")
        interactions_detected = (
            cleaning_report.get("interactions_detected") if cleaning_report else None
        )

        highest_correlation_pair = (
            correlation_result["highest_pair"]
            if correlation_result is not None
            else None
        )
        highest_correlation_value = (
            correlation_result["highest_value"]
            if correlation_result is not None
            else None
        )

        chart_paths = await asyncio.to_thread(
            generate_all_charts,
            df,
            analysis_id,
            numeric_columns,
            categorical_columns,
            datetime_column,
            time_series_value_column,
            highest_correlation_pair,
            highest_correlation_value,
        )

        # Self-evaluation loop (Build J): Python checks each response
        # structurally and retries only on a real failure. The kept response is
        # the first that passes, else the one with the fewest failed criteria
        # (earliest on a tie), so a retry replaces a response only when it is
        # strictly better. A retry that cannot be used (the call fails, or the
        # response is truncated or not JSON) ranks below every parsed response.
        calls_made = 0
        failed_criteria: List[Dict[str, str]] = []
        last_failures: List[Dict[str, str]] = []
        kept_response: Any = None
        kept_call = 0
        kept_failures: List[Dict[str, str]] = []
        unusable_retries: List[Tuple[int, str]] = []
        call_outcomes: List[str] = []
        system_prompt = load_system_prompt("analyzer")

        while calls_made < ANALYZER_MAX_CALLS:
            user_message = build_analyzer_message(
                analysis_id=analysis_id,
                profile_report=profile_report,
                cleaning_report=cleaning_report,
                descriptive_stats=descriptive_stats,
                correlation_result=correlation_result,
                distributions=distributions,
                value_counts=value_counts,
                time_series_result=time_series_result,
                domain_hypothesis=domain_hypothesis,
                provenance_hypothesis=provenance_hypothesis,
                top_3_concerns=top_3_concerns,
                top_3_patterns=top_3_patterns,
                user_context=user_context,
                interactions_detected=interactions_detected,
                failed_criteria=failed_criteria,
            )

            def _run_analyzer_stream():
                # Must stream: ANALYZER_MAX_TOKENS exceeds the SDK's non-streaming
                # ceiling (see the constant's note). get_final_message() returns the
                # same Message shape messages.create() would, so the stop_reason
                # guard and JSON parsing below are unchanged.
                with client.messages.stream(
                    model=ANTHROPIC_MODEL,
                    max_tokens=ANALYZER_MAX_TOKENS,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                ) as stream:
                    return stream.get_final_message()

            calls_made += 1
            try:
                response = await asyncio.to_thread(_run_analyzer_stream)
                if response.stop_reason == "max_tokens":
                    raise AnalyzerResponseTruncated(
                        "Analyzer LLM response truncated: reached the max_tokens "
                        f"ceiling ({ANALYZER_MAX_TOKENS}) before the JSON was complete. "
                        "Raise ANALYZER_MAX_TOKENS or reduce the analyzer's output size."
                    )
                text = (
                    getattr(response.content[0], "text", None) if response.content else None
                )
                if not isinstance(text, str):
                    raise AnalyzerResponseEmpty(
                        "Analyzer LLM response has no text content "
                        f"(stop_reason={response.stop_reason!r})."
                    )
                try:
                    candidate = parse_json_response(text)
                except ValueError as parse_error:
                    raise AnalyzerResponseNotJSON(str(parse_error)) from parse_error
            except Exception as exc:
                if kept_call == 0:
                    raise  # the first call: a SYSTEM_ERROR, as before Build J
                reason = _unusable_reason(exc)
                unusable_retries.append((calls_made, reason))
                call_outcomes.append(f"call {calls_made}: {reason}")
                logger.warning(
                    "Analyzer call %d for analysis_id=%s could not be used; "
                    "keeping call %d: %r",
                    calls_made,
                    analysis_id,
                    kept_call,
                    exc,
                )
                failed_criteria = _merge_failures(kept_failures, last_failures) + [{
                    "criterion": "(unusable retry)",
                    "reason": (
                        f"Your previous response could not be used: {reason}. "
                        "Return one complete AnalysisReport JSON object."
                    ),
                }]
                continue

            all_passed, failures = check_self_evaluation(
                candidate, top_3_concerns, correlation_result
            )
            if not isinstance(candidate, dict):
                call_outcomes.append(f"call {calls_made}: a JSON {type(candidate).__name__}")
            logger.info(
                "Analyzer self-evaluation, call %d for analysis_id=%s: "
                "all_passed=%s, failed_criteria=%s",
                calls_made,
                analysis_id,
                all_passed,
                failures,
            )
            if kept_call == 0 or len(failures) < len(kept_failures):
                kept_response, kept_call, kept_failures = candidate, calls_made, failures
            if all_passed:
                break
            last_failures = failures
            failed_criteria = _merge_failures(kept_failures, last_failures)

        if not isinstance(kept_response, dict):
            raise ValueError(
                f"Analyzer produced no usable AnalysisReport object in {calls_made} "
                "calls: " + "; ".join(call_outcomes) + "."
            )
        analysis_response = kept_response

        # The loop's record, written by Python at the keys the Explainer reads
        # (explainer_system.md: unmet_criteria, self_evaluation_loops).
        unmet_criteria: List[Dict[str, str]] = list(kept_failures)
        for call_number, reason in unusable_retries:
            if call_number > kept_call:
                unmet_criteria.append({
                    "criterion": "(unusable retry)",
                    "reason": (
                        f"Retry call {call_number} could not be used ({reason}); "
                        f"the response from call {kept_call} was kept."
                    ),
                })
        if not chart_paths:
            unmet_criteria.append({
                "criterion": "(d)",
                "reason": (
                    "No charts were generated (chart_paths is empty). The system "
                    "renders the charts before the analysis call, so a retry "
                    "cannot add them."
                ),
            })
        analysis_response.pop("self_evaluation_gaps", None)
        analysis_response["self_evaluation_loops"] = calls_made
        analysis_response["unmet_criteria"] = unmet_criteria

        # Memory MCP write — six analyzer keys (anomalies_found is intentionally
        # written by the LLM closing ritual, not at the Python level — see
        # analyzer_system.md Section 12).
        memory_writes = {
            "analyzer.most_important_finding": analysis_response.get(
                "most_important_finding", ""
            ),
            "analyzer.most_surprising_finding": analysis_response.get(
                "most_surprising_finding", ""
            ),
            "analyzer.strong_correlations": (
                correlation_result["strong_pairs"]
                if correlation_result is not None
                else []
            ),
            "analyzer.chart_paths": chart_paths,
            "analyzer.data_quality_score": data_quality_score,
            "analyzer.open_questions": analysis_response.get("open_questions", []),
        }
        logger.info(
            "Memory MCP write for analyzer (analysis_id=%s): keys=%s",
            analysis_id,
            list(memory_writes.keys()),
        )

        analysis_response["descriptive_stats"] = descriptive_stats
        analysis_response["correlation_matrix"] = correlation_result
        analysis_response["distributions"] = distributions
        analysis_response["value_counts"] = value_counts
        analysis_response["time_series"] = time_series_result
        analysis_response["data_quality_score"] = data_quality_score
        analysis_response["chart_paths"] = chart_paths

        # Python's r, n and the 30-pair floor on the model's correlation
        # entries — after the final parse, before the single save (Build I).
        await asyncio.to_thread(
            apply_correlation_floor, analysis_response, correlation_result, df
        )

        # Sanitize returns a NEW object — reassignment is mandatory.
        analysis_response = sanitize_for_json(analysis_response)

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({"analysis_report": analysis_response})
            .eq("id", analysis_id)
            .execute()
        )
        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({"chart_paths": chart_paths})
            .eq("id", analysis_id)
            .execute()
        )
        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({"data_quality_score": data_quality_score})
            .eq("id", analysis_id)
            .execute()
        )
        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({"updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", analysis_id)
            .execute()
        )

        return {
            "analysis_report": analysis_response,
            "chart_paths": chart_paths,
            "data_quality_score": data_quality_score,
            "analyzer_most_important_finding": analysis_response.get(
                "most_important_finding", ""
            ),
        }

    except Exception as exc:
        logger.exception("Analyzer node failed for analysis_id=%s", analysis_id)
        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "error",
                "error_message": f"SYSTEM_ERROR: {str(exc)}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )
        raise
