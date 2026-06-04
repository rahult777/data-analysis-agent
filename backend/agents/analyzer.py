"""The Deep Investigator — Agent 3 in the data analysis pipeline.

Reads the cleaned dataset prepared by the Cleaner, computes the mandatory
descriptive analysis surface (descriptives, correlations, distributions,
value counts, time series), generates all required charts, runs the LLM
through a self-evaluation loop until the five investigator criteria pass
(or three iterations have elapsed), and persists a complete AnalysisReport
to Supabase for the Explainer to consume.
"""

import asyncio
import json
import logging
import math
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


def classify_columns(
    df: pd.DataFrame,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Classify columns into (numeric, categorical, datetime).

    Numeric: pandas number dtypes, excluding any column whose name contains
    "id" (case-insensitive) — IDs are stored as integers but are not numeric
    in the analytical sense.
    Categorical: object dtypes plus boolean columns.
    Datetime: the first column whose dtype name contains "datetime", or None.
    """
    raw_numeric = df.select_dtypes(include="number").columns.tolist()
    numeric_columns = [c for c in raw_numeric if "id" not in c.lower()]

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


def compute_correlation_matrix(
    df: pd.DataFrame,
    numeric_columns: List[str],
) -> Optional[dict]:
    """Compute the full Pearson correlation matrix with diagonal masking.

    Returns None if fewer than 2 numeric columns exist. Otherwise returns
    a dict with sanitized matrix, strong_pairs (|r| > 0.7, off-diagonal),
    highest_pair (list[col1, col2]), and highest_value (float or None).
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
    failed_criteria: Optional[List[str]],
) -> str:
    """Build the Anthropic user message for the analyzer LLM call."""
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
            "concerns": top_3_concerns,
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
                "SELF-EVALUATION FAILED — these criteria were not met in the "
                "previous iteration, address them explicitly this time."
            ),
            "failed_criteria": failed_criteria,
        }

    sanitized = sanitize_for_json(message_data)
    return json.dumps(sanitized, default=str)


def check_self_evaluation(
    analysis_response: dict,
    top_3_concerns: list,
    correlation_result: Optional[dict],
    chart_paths: List[str],
) -> Tuple[bool, List[str]]:
    """Run the five-criterion self-evaluation. Returns (all_passed, failed)."""
    failed: List[str] = []
    response_str = str(analysis_response).lower()

    # (a) Every concern addressed
    if top_3_concerns:
        unaddressed = []
        for concern in top_3_concerns:
            concern_str = str(concern).lower()
            if concern_str not in response_str:
                unaddressed.append(concern_str[:80])
        if unaddressed:
            failed.append(f"(a) profiler concerns not addressed: {unaddressed}")

    # (b) Every strong correlation pair investigated
    if correlation_result is not None:
        strong_pairs = correlation_result.get("strong_pairs") or []
        unaddressed_pairs: List[str] = []
        for pair in strong_pairs:
            col1 = str(pair.get("col1", "")).lower()
            col2 = str(pair.get("col2", "")).lower()
            if col1 not in response_str or col2 not in response_str:
                unaddressed_pairs.append(f"{col1}-{col2}")
        if unaddressed_pairs:
            failed.append(
                f"(b) strong correlations not investigated: {unaddressed_pairs}"
            )

    # (c) At least one anomaly explanation
    if "anomal" not in response_str:
        failed.append("(c) no anomaly explanations present in response")

    # (d) chart_paths non-empty
    if not chart_paths:
        failed.append("(d) chart_paths is empty — no charts generated")

    # (e) Both findings present, non-empty, distinct
    most_important = (analysis_response.get("most_important_finding") or "").strip()
    most_surprising = (analysis_response.get("most_surprising_finding") or "").strip()
    if not most_important or not most_surprising or most_important == most_surprising:
        failed.append(
            "(e) most_important_finding and most_surprising_finding must both "
            "be non-empty and distinct from each other"
        )

    return (len(failed) == 0, failed)


async def analyzer_node(state: PipelineState) -> dict:
    """LangGraph node — runs the full Deep Investigator pipeline."""
    analysis_id = state["analysis_id"]

    try:
        # LangSmith trace handle (callbacks attached at graph.invoke level).
        tracer = create_tracer("analyzer")  # noqa: F841

        # Memory MCP read — eight inheritance keys, sourced from pipeline state.
        domain_hypothesis = state.get("profiler_domain_hypothesis") or ""
        provenance_hypothesis = state.get("profiler_provenance_hypothesis") or ""
        top_3_concerns = state.get("profiler_top_3_concerns") or []
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

        loop_count = 0
        failed_criteria: List[str] = []
        analysis_response: dict = {}
        system_prompt = load_system_prompt("analyzer")

        while True:
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

            response = await asyncio.to_thread(_run_analyzer_stream)

            if response.stop_reason == "max_tokens":
                raise ValueError(
                    "Analyzer LLM response truncated: reached the max_tokens "
                    f"ceiling ({ANALYZER_MAX_TOKENS}) before the JSON was complete. "
                    "Raise ANALYZER_MAX_TOKENS or reduce the analyzer's output size."
                )

            analysis_response = parse_json_response(response.content[0].text)

            all_passed, failed_criteria = check_self_evaluation(
                analysis_response,
                top_3_concerns,
                correlation_result,
                chart_paths,
            )

            logger.info(
                "Analyzer self-evaluation iteration %d for analysis_id=%s: "
                "all_passed=%s, failed_criteria=%s",
                loop_count,
                analysis_id,
                all_passed,
                failed_criteria,
            )

            if all_passed or loop_count >= 2:
                break
            loop_count += 1

        if failed_criteria:
            analysis_response["self_evaluation_gaps"] = failed_criteria

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
