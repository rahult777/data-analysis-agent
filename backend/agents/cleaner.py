"""The Thoughtful Cleaner — Agent 2 in the data analysis pipeline.

Reads the ProfileReport, makes domain-aware decisions about data quality,
executes cleaning operations, and produces a fully documented CleaningReport.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from anthropic import Anthropic

from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from backend.models.schemas import (
    AnalysisStatus,
    CleanedDatasetSummary,
    CleaningDecision,
    CleaningReport,
)
from backend.utils.file_handler import cleanup_temp_file, upload_to_storage
from backend.utils.langsmith_client import create_tracer
from backend.utils.supabase_client import get_supabase_client
from backend.agents.profiler import PipelineState, load_system_prompt, parse_json_response

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# The model's pause "type" → the analyses.status the pause-wait node writes,
# which is also the pause_type /resume requires in the user's answer.
_MISSING_VALUE_PAUSE = "missing_value_pause"
_OUTLIER_PAUSE = "outlier_pause"
_PAUSE_STATUS_BY_TYPE: dict[str, str] = {
    "missing_value_decision_required": _MISSING_VALUE_PAUSE,
    "outlier_decision_required": _OUTLIER_PAUSE,
}
_MISSING_PAUSE_THRESHOLD_PCT = 30.0
_MISSING_OPTION_IDS = ["impute", "exclude_column", "exclude_rows"]
_PRESERVE_OPTION_ID = "preserve_missingness"
_IMPUTE_METHODS = ("median", "mean", "mode")
_MISSING_PAUSE_TEXT_FIELDS = (
    "what_this_column_represents", "provenance_interpretation", "domain_context",
)
_OUTLIER_OPTION_IDS: dict[str, list[str]] = {
    "medical": ["include_with_annotation", "exclude_pending_clinical_review"],
    "financial": ["treat_as_valid", "flag_as_suspected_error"],
}
_OUTLIER_NOTE_FIELD: dict[str, str] = {
    "medical": "clinical_significance_note",
    "financial": "financial_context_note",
}
_OUTLIER_KEEP_IDS = {"include_with_annotation", "treat_as_valid"}
# cleaner_system.md §8.2/§8.3 option labels, re-rendered with Python's count so
# the label the user clicks cannot contradict the count stored beside it.
_OUTLIER_LABELS: dict[str, str] = {
    "include_with_annotation": "Include the {n} outlier value(s) in the analysis as potentially clinically significant; annotate as statistical outliers",
    "exclude_pending_clinical_review": "Exclude the {n} outlier value(s) pending clinical review",
    "treat_as_valid": "Treat the {n} outlier value(s) as valid data (legitimate large transaction or expected business event)",
    "flag_as_suspected_error": "Flag the {n} outlier value(s) as suspected data entry error or fraud; exclude from aggregate statistics pending investigation",
}
# The model is shown the first 50 columns only (build_cleaner_message), so only
# those can be routed in outlier_review.
_MESSAGE_COLUMN_LIMIT = 50
_OUTLIER_ROUTINGS = ("medical", "financial", "none")
# §8.2/§8.3's fixed first sentence of each domain note, for a pause Python writes.
_OUTLIER_DOMAIN_SENTENCE: dict[str, str] = {
    "medical": (
        "In medical data, extreme values are often the most clinically significant data "
        "points in the dataset rather than measurement errors."
    ),
    "financial": (
        "In financial data, extreme values are often legitimate large transactions (corporate "
        "treasury movements, end-of-quarter true-ups, wholesale orders), fraud signals, or data "
        "integration errors at merge points."
    ),
}


async def load_dataframe_from_uploads(stored_filename: str) -> pd.DataFrame:
    file_path = Path("backend") / "uploads" / stored_filename
    if not await asyncio.to_thread(file_path.exists):
        raise FileNotFoundError(
            f"Uploaded file not found at expected path: {file_path.resolve()}"
        )
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = await asyncio.to_thread(pd.read_csv, file_path)
    elif suffix in (".xls", ".xlsx"):
        df = await asyncio.to_thread(pd.read_excel, file_path)
    else:
        raise ValueError(
            f"Unsupported file extension '{suffix}' for '{file_path.name}'. "
            "Only .csv, .xls, and .xlsx files are supported."
        )
    # Excel keeps date and number header cells as their native type, so a
    # column label can be a datetime or an int. json.dumps coerces int,
    # float and bool keys to JSON strings, so the LLM names a decision
    # "2021" while the label is still int 2021 — execute_cleaning_operations
    # then matches nothing and silently skips every decision for that
    # column. A datetime key raises TypeError outright. map(str), not
    # astype(str): it matches parquet's own stringification, so these
    # names stay identical to the ones the Analyzer later reads back.
    df.columns = df.columns.map(str)
    return df


def analyze_missingness_patterns(df: pd.DataFrame) -> dict:
    patterns: dict = {}

    for col in df.columns:
        missing_mask = df[col].isna()
        missing_pct = missing_mask.mean() * 100

        if missing_pct == 0:
            continue

        # Check correlated missingness with other columns first
        other_missing_cols = [c for c in df.columns if c != col and df[c].isna().any()]
        corr_found = False
        for other_col in other_missing_cols:
            other_missing_mask = df[other_col].isna()
            overlap = int((missing_mask & other_missing_mask).sum())
            if missing_mask.sum() > 0 and overlap / missing_mask.sum() > 0.7:
                patterns[col] = {
                    "classification": "correlated-with-other-columns",
                    "missing_pct": round(float(missing_pct), 2),
                    "details": (
                        f"Missing values co-occur with '{other_col}' "
                        f"in {overlap} records"
                    ),
                }
                corr_found = True
                break

        if corr_found:
            continue

        # Check temporal pattern — missing values cluster in a time period
        datetime_cols = [
            c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])
        ]
        if not datetime_cols:
            datetime_cols = [
                c for c in df.columns
                if any(kw in c.lower() for kw in ("date", "time", "year", "month"))
            ]

        temporal_found = False
        if datetime_cols:
            try:
                time_col = datetime_cols[0]
                time_series = pd.to_datetime(df[time_col], errors="coerce")
                if time_series.notna().any():
                    df_temp = pd.DataFrame({"missing": missing_mask, "time": time_series})
                    df_temp = df_temp.dropna(subset=["time"])
                    if len(df_temp) > 10:
                        time_int = df_temp["time"].astype("int64")
                        df_temp["bin"] = pd.qcut(
                            time_int, q=4, labels=False, duplicates="drop"
                        )
                        bin_missing = df_temp.groupby("bin")["missing"].mean()
                        if bin_missing.max() - bin_missing.min() > 0.3:
                            peak_bin = int(bin_missing.idxmax())
                            patterns[col] = {
                                "classification": "systematic-temporal",
                                "missing_pct": round(float(missing_pct), 2),
                                "details": (
                                    f"Missing values concentrate in time bin {peak_bin} "
                                    f"({bin_missing.max():.0%} vs "
                                    f"{bin_missing.min():.0%} overall)"
                                ),
                            }
                            temporal_found = True
            except Exception:
                pass

        if temporal_found:
            continue

        # Check subset-based systematic pattern
        categorical_cols = [
            c for c in df.columns
            if c != col and df[c].dtype == "object" and df[c].nunique() < 20
        ]
        subset_found = False
        for cat_col in categorical_cols:
            try:
                group_missing = df.groupby(cat_col)[col].apply(
                    lambda x: x.isna().mean()
                )
                if group_missing.max() - group_missing.min() > 0.5:
                    dominant_group = group_missing.idxmax()
                    patterns[col] = {
                        "classification": "systematic-by-subset",
                        "missing_pct": round(float(missing_pct), 2),
                        "details": (
                            f"Missing values concentrate in "
                            f"'{cat_col}'='{dominant_group}' "
                            f"({group_missing.max():.0%} missing vs "
                            f"{group_missing.min():.0%} in other groups)"
                        ),
                    }
                    subset_found = True
                    break
            except Exception:
                pass

        if subset_found:
            continue

        patterns[col] = {
            "classification": "random",
            "missing_pct": round(float(missing_pct), 2),
            "details": "Missing values appear randomly distributed",
        }

    return patterns


def build_cleaner_message(
    df: pd.DataFrame,
    profile_report: dict,
    domain_hypothesis: Optional[str],
    provenance_hypothesis: Optional[str],
    top_3_concerns: Optional[list],
    resolved_pauses: Optional[list],
    missingness_patterns: dict,
    domain_resolution: Optional[dict] = None,
    outlier_review_columns: Optional[list] = None,
) -> str:
    columns = df.columns[:_MESSAGE_COLUMN_LIMIT].tolist()
    df_subset = df[columns]

    col_info: dict = {}
    for col in columns:
        series = df_subset[col]
        non_null_vals = series.dropna()
        if (pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)) or pd.api.types.is_datetime64_any_dtype(series):
            sampled = non_null_vals.sample(min(5, len(non_null_vals)), random_state=42)
        else:
            sampled = non_null_vals.drop_duplicates().head(5)
        sample = [str(v) for v in sampled.tolist()]
        col_info[col] = {
            "dtype": str(series.dtype),
            "missing_pct": round(float(series.isna().mean() * 100), 2),
            "missing_count": int(series.isna().sum()),
            "sample_values": sample,
        }

    for col in columns:
        # The same bounds and mask the outlier pause, outlier_review and the
        # apply step use, so the model and Python count the same values.
        bounds = _iqr_bounds(df_subset[col])
        if bounds is not None:
            col_info[col]["outlier_count"] = int(_iqr_outlier_mask(df_subset[col]).sum())
            col_info[col]["outlier_bounds"] = {"lower": bounds[0], "upper": bounds[1]}

    message_data: dict = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns_included": len(columns),
        "column_info": col_info,
        "domain_hypothesis": domain_hypothesis,
        "provenance_hypothesis": provenance_hypothesis,
        "top_3_concerns": top_3_concerns or [],
        "missingness_patterns": missingness_patterns,
    }

    if profile_report:
        message_data["profile_summary"] = {
            "structural_observations": profile_report.get("structural_observations"),
            "top_3_patterns": profile_report.get("top_3_patterns"),
        }

    if len(df.columns) > 50:
        message_data["columns_note"] = (
            f"Dataset has {len(df.columns)} columns total. "
            "First 50 included to prevent token bloat."
        )

    # The user's settlement of the domain, when there was a domain pause
    # (profiler.apply_domain_resolution). The score is deliberately not sent:
    # it is either the original sub-80 pause score or the resume call's own.
    if domain_resolution:
        message_data["domain_resolution"] = domain_resolution

    if resolved_pauses:
        message_data["resolved_pauses"] = resolved_pauses

    # The columns the report's outlier_review must route (cleaner_system.md §8.3).
    if outlier_review_columns is not None:
        message_data["outlier_review_columns"] = outlier_review_columns

    return json.dumps(message_data, default=str)


def detect_interactions(df: pd.DataFrame, profile_report: dict) -> list:
    if len(df) == 0:
        return []

    interactions: list = []
    missing_cols = [col for col in df.columns if df[col].isna().any()]

    # Co-missing patterns across column pairs
    for i, col_a in enumerate(missing_cols):
        for col_b in missing_cols[i + 1:]:
            mask_a = df[col_a].isna()
            mask_b = df[col_b].isna()
            co_missing = int((mask_a & mask_b).sum())
            if co_missing > 5 and co_missing / len(df) > 0.02:
                interactions.append({
                    "pattern": "co-missing",
                    "columns": [col_a, col_b],
                    "affected_records": co_missing,
                    "recommendation": (
                        f"{co_missing} records are missing both '{col_a}' and "
                        f"'{col_b}'. This may indicate a merge artifact or a "
                        "systematic data collection gap. Investigate before "
                        "imputing either column independently."
                    ),
                })

    # Outlier + missing combination patterns
    numeric_cols = [
        col for col in df.columns
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col])
    ]
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 4:
            continue
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_mask = (df[col] < lower) | (df[col] > upper)

        for miss_col in missing_cols:
            if miss_col == col:
                continue
            co_pattern = int((outlier_mask & df[miss_col].isna()).sum())
            if (
                co_pattern > 3
                and outlier_mask.sum() > 0
                and co_pattern / outlier_mask.sum() > 0.5
            ):
                interactions.append({
                    "pattern": "outlier-with-missing",
                    "columns": [col, miss_col],
                    "affected_records": co_pattern,
                    "recommendation": (
                        f"{co_pattern} records with outlier values in '{col}' "
                        f"also have missing '{miss_col}'. This cluster may be a "
                        "fraud signal, data entry error, or merge artifact. "
                        "Preserve these records with annotation rather than "
                        "cleaning independently."
                    ),
                })

    return interactions


def classify_cleaning_decision(decision: dict) -> str:
    """Name the operation execute_cleaning_operations will run for a decision.

    The routing reads keywords in the decision's action and issue text, in a
    fixed order; the first match wins. It is a heuristic over model-written
    prose, so the returned name says what the text will trigger, not what the
    model meant (errors.md 2026-09-25).
    """
    if decision.get("column_name") is None:
        return "dedupe"
    action_lower = (decision.get("action", "") or "").lower()
    issue_lower = (decision.get("issue", "") or "").lower()
    combined = action_lower + " " + issue_lower
    if "median" in combined:
        return "median"
    if "mean" in combined and "median" not in combined:
        return "mean"
    if "mode" in combined:
        return "mode"
    if any(
        kw in combined
        for kw in ("fill with", "impute with", "replace with", "set to", "replace missing")
    ):
        return "fill"
    if any(
        kw in combined
        for kw in (
            "drop column", "exclude column", "remove column",
            "exclude from analysis", "drop from dataset",
        )
    ):
        return "drop_column"
    if any(
        kw in combined
        for kw in (
            "drop rows", "remove rows", "drop records",
            "remove records", "exclude rows",
        )
    ):
        return "drop_rows"
    if any(kw in combined for kw in ("convert", "cast", "change type", "dtype", "type to")):
        return "dtype"
    if "outlier" in combined or "flag" in combined:
        if not any(kw in combined for kw in ("remove", "delete", "drop")):
            return "outlier_flag"
        return "outlier_noop"
    return "unmatched"


def execute_cleaning_operations(
    df: pd.DataFrame,
    decisions: list,
) -> tuple[pd.DataFrame, list, dict]:
    df = df.copy()
    excluded_columns: list = []
    outlier_flagged: dict = {}

    for decision in decisions:
        col = decision.get("column_name")
        action = decision.get("action", "") or ""
        issue = decision.get("issue", "") or ""
        action_lower = action.lower()
        issue_lower = issue.lower()
        combined = action_lower + " " + issue_lower
        op = classify_cleaning_decision(decision)

        # 1. DUPLICATE REMOVAL — column_name is null for dataset-level decisions
        if op == "dedupe":
            before = len(df)
            df = df.drop_duplicates()
            after = len(df)
            if before != after:
                logger.info("Removed %d duplicate rows", before - after)
            continue

        if col not in df.columns:
            logger.warning(
                "Skipped decision — column '%s' not found in dataframe", col
            )
            continue

        # 2. MEDIAN FILL
        if op == "median":
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].median())
            continue

        # 3. MEAN FILL (not median)
        if op == "mean":
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].mean())
            continue

        # 4. MODE FILL
        if op == "mode":
            mode_vals = df[col].mode()
            if len(mode_vals) > 0:
                df[col] = df[col].fillna(mode_vals.iloc[0])
            continue

        # 5. SPECIFIC VALUE FILL
        if op == "fill":
            match = re.search(
                r"(?:fill|impute|replace|set)\s+(?:missing\s+)?(?:with|to)"
                r"\s+['\"]?([^'\"]+)['\"]?",
                action_lower,
            )
            if match:
                raw_val = match.group(1).strip()
                try:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        fill_val = float(raw_val) if "." in raw_val else int(raw_val)
                    else:
                        fill_val = raw_val
                    df[col] = df[col].fillna(fill_val)
                except (ValueError, TypeError):
                    df[col] = df[col].fillna(raw_val)
            continue

        # 6. DROP COLUMN
        if op == "drop_column":
            df = df.drop(columns=[col])
            excluded_columns.append(col)
            continue

        # 7. DROP ROWS
        if op == "drop_rows":
            df = df.dropna(subset=[col])
            continue

        # 8. DTYPE CONVERT
        if op == "dtype":
            try:
                if any(kw in combined for kw in ("string", "str", "object", "text")):
                    df[col] = df[col].where(df[col].isna(), df[col].astype(str))
                elif "category" in combined:
                    df[col] = df[col].astype("category")
                elif any(kw in combined for kw in ("float", "decimal", "numeric")):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif any(kw in combined for kw in ("int", "integer")):
                    df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
                elif any(kw in combined for kw in ("datetime", "date", "timestamp")):
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            except Exception as e:
                logger.warning("DTYPE CONVERT failed for column '%s': %s", col, e)
            continue

        # 9. OUTLIER FLAG — annotate without removing
        if op in ("outlier_flag", "outlier_noop"):
            if op == "outlier_flag":
                if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
                    series = df[col].dropna()
                    if len(series) > 4:
                        q1 = series.quantile(0.25)
                        q3 = series.quantile(0.75)
                        iqr = q3 - q1
                        lower = q1 - 1.5 * iqr
                        upper = q3 + 1.5 * iqr
                        flag_col = f"{col}_outlier_flag"
                        df[flag_col] = (
                            (df[col] < lower) | (df[col] > upper)
                        ).astype(int)
                        outlier_flagged[col] = int(df[flag_col].sum())
            continue

        logger.warning(
            "Skipped decision — no matching operation rule: column=%s, action=%s",
            col,
            action,
        )

    return df, excluded_columns, outlier_flagged


def re_profile_dataframe(df: pd.DataFrame) -> dict:
    missing_counts = {
        col: int(df[col].isna().sum())
        for col in df.columns
        if df[col].isna().any()
    }
    columns_with_missing = list(missing_counts.keys())
    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "missing_counts": missing_counts,
        "columns_with_missing": columns_with_missing,
        "passed": len(columns_with_missing) == 0,
    }


def _is_numeric_column(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _iqr_bounds(series: pd.Series) -> Optional[tuple[float, float]]:
    """The 1.5×IQR (lower, upper) bounds, or None when the column gets no outlier check.

    None for a non-numeric column (bool counts as non-numeric: it has no
    quantile, the same exclusion as profiler.compute_column_stats) and for one
    with 4 or fewer recorded values.
    """
    values = series.dropna()
    if not _is_numeric_column(series) or len(values) <= 4:
        return None
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def _iqr_outlier_mask(series: pd.Series) -> pd.Series:
    """True where a value lies outside the 1.5×IQR bounds build_cleaner_message reports.

    The one outlier definition behind the message's counts, outlier_review, the
    outlier pause, the outlier records and apply_user_decisions, so the values a
    user answers about are exactly the ones the model was shown. (The keyword
    router's OUTLIER FLAG branch for the model's own decisions still computes
    its own bounds on the partly cleaned frame — errors.md 2026-09-25, IQR.)
    """
    bounds = _iqr_bounds(series)
    if bounds is None:
        return pd.Series(False, index=series.index)
    lower, upper = bounds
    return (series < lower) | (series > upper)


def _outlier_facts(series: pd.Series, mask: pd.Series, representative: object = None) -> dict:
    """What an outlier pause or record states about a column, computed from the mask.

    Mean and standard deviation are over the finite recorded values (pandas'
    default sample std, as the Profiler reports them), so an infinite value is
    counted as an outlier but never turns a statistic into inf or NaN, which
    the saved JSON cannot hold. The representative value is `representative`
    when it is one of the flagged finite values (the model's own choice, which
    its note text describes), otherwise the flagged finite value furthest from
    the mean; its signed distance in SDs is Python's. Any of value,
    sd_distance, mean and std is None when it cannot be computed.
    """
    recorded = series.dropna().astype(float)
    finite = recorded[np.isfinite(recorded)]
    mean = float(finite.mean()) if len(finite) else None
    std = float(finite.std()) if len(finite) > 1 else None
    flagged = series[mask].astype(float)
    finite_flagged = flagged[np.isfinite(flagged)]
    if (
        isinstance(representative, (int, float, np.integer, np.floating))
        and not isinstance(representative, bool)
        and float(representative) in set(finite_flagged.tolist())
    ):
        value = float(representative)
    elif len(finite_flagged) and mean is not None:
        value = float(finite_flagged.loc[(finite_flagged - mean).abs().idxmax()])
    else:
        value = None
    lower, upper = _iqr_bounds(series)
    return {
        "count": int(mask.sum()),
        "lower": lower,
        "upper": upper,
        "min": float(flagged.min()),
        "max": float(flagged.max()),
        "value": value,
        "sd_distance": round((value - mean) / std, 2) if value is not None and mean is not None and std else None,
        "mean": mean,
        "std": std,
    }


def _outlier_extreme_clause(facts: dict) -> str:
    """"; the most extreme, v, is d SD from the column mean of m" — or "" when not computable."""
    if facts["sd_distance"] is None:
        return ""
    return (
        f"; the most extreme, {_format_value(facts['value'])}, is {facts['sd_distance']} SD from "
        f"the column mean of {_format_value(facts['mean'])}"
    )


def _outlier_facts_sentence(facts: dict) -> str:
    return (
        f"{facts['count']} value(s) lie outside the IQR bounds ({_format_value(facts['lower'])} to "
        f"{_format_value(facts['upper'])}), from {_format_value(facts['min'])} to "
        f"{_format_value(facts['max'])}{_outlier_extreme_clause(facts)}."
    )


def _missing_counts(df: pd.DataFrame, column: str) -> tuple[int, float, int]:
    """(missing_count, missing_pct, total_rows), computed as build_cleaner_message does."""
    series = df[column]
    return int(series.isna().sum()), round(float(series.isna().mean() * 100), 2), len(df)


def _format_value(value: object) -> str:
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.6g}"
    return str(value)


def _is_blank(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


def _preserve_option(column: str, missing_count: int, recorded_count: int) -> dict:
    """The fourth missing-value option. Written by Python, never the model, so its
    wording promises only what the pipeline does: nothing downstream
    investigates the pattern (errors.md 2026-09-22, option drift)."""
    return {
        "id": _PRESERVE_OPTION_ID,
        "label": f"Keep `{column}` as it is: its {missing_count} missing values stay missing",
        "consequence": (
            f"nothing is imputed and no rows are removed. Statistics on `{column}` will use "
            f"only its {recorded_count} recorded values, and the missingness is recorded in "
            "the cleaning report, where the Analyzer and Explainer will see it"
        ),
    }


def _excluded_by_answer(answered: list) -> set:
    return {
        entry.get("column_name")
        for entry in answered
        if entry.get("pause_type") == _MISSING_VALUE_PAUSE
        and (entry.get("response") or {}).get("option_id") == "exclude_column"
    }


def validate_cleaner_pause(parsed: dict, df: pd.DataFrame, answered: list) -> dict:
    """Check a Cleaner pause before it is stored and shown; return the question to store.

    Raises ValueError for anything the user must never be asked: a repeat of an
    answered question (the multi-column loop), a column that does not exist or
    that the user already excluded, or options Python could not execute exactly
    as chosen. Fails before the user answers, never after. Python overwrites the
    displayed counts with its own and appends the fourth missing-value option.
    """
    pause_type = _PAUSE_STATUS_BY_TYPE[parsed["type"]]
    column = parsed.get("column_name")
    if not isinstance(column, str) or column not in df.columns:
        raise ValueError(f"The Cleaner paused on column {column!r}, which is not in the dataset.")
    if any(
        entry.get("pause_type") == pause_type and entry.get("column_name") == column
        for entry in answered
    ):
        raise ValueError(
            f"The Cleaner asked again for a {pause_type} decision on '{column}' after the "
            "user answered it; refusing to ask the same question twice."
        )
    if column in _excluded_by_answer(answered):
        raise ValueError(
            f"The Cleaner paused on '{column}', which the user already excluded from the dataset."
        )

    options = parsed.get("options")
    option_ids = (
        [option.get("id") if isinstance(option, dict) else None for option in options]
        if isinstance(options, list)
        else None
    )

    if pause_type == _MISSING_VALUE_PAUSE:
        if option_ids != _MISSING_OPTION_IDS:
            raise ValueError(
                f"Missing-value pause on '{column}' must offer options {_MISSING_OPTION_IDS} "
                f"in that order; got {option_ids}."
            )
        for field in _MISSING_PAUSE_TEXT_FIELDS:
            if _is_blank(parsed.get(field)):
                raise ValueError(f"Missing-value pause on '{column}' has no {field}.")
        method_id = options[0].get("method_id")
        if method_id not in _IMPUTE_METHODS:
            raise ValueError(
                f"Missing-value pause on '{column}' offers imputation by {method_id!r}; "
                f"the method_id must be one of {list(_IMPUTE_METHODS)}."
            )
        if method_id in ("median", "mean") and not _is_numeric_column(df[column]):
            raise ValueError(
                f"Missing-value pause on '{column}' offers {method_id} imputation, but the "
                f"column is {df[column].dtype}, not numeric."
            )
        missing_count, missing_pct, total_rows = _missing_counts(df, column)
        recorded_count = total_rows - missing_count
        if missing_pct <= _MISSING_PAUSE_THRESHOLD_PCT:
            logger.warning(
                "Cleaner paused on '%s' at %.2f%% missing, at or under the %.0f%% threshold.",
                column, missing_pct, _MISSING_PAUSE_THRESHOLD_PCT,
            )
        stored_options = [dict(option) for option in options]
        # Labels re-rendered from §8.1's templates with Python's count.
        stored_options[0]["label"] = (
            f"Impute the {missing_count} missing values with "
            f"{stored_options[0].get('method') or method_id}"
        )
        stored_options[2]["label"] = f"Exclude the {missing_count} rows where `{column}` is missing"
        if recorded_count == 0:
            # Nothing to impute from, and excluding the missing rows would
            # remove every row: neither could be executed as the user expects.
            stored_options = [
                option for option in stored_options if option["id"] not in ("impute", "exclude_rows")
            ]
        stored_options.append(_preserve_option(column, missing_count, recorded_count))
        return {
            **parsed,
            "missing_count": missing_count,
            "missing_pct": missing_pct,
            "total_rows": total_rows,
            "options": stored_options,
        }

    domain_context = parsed.get("domain_context")
    if domain_context not in _OUTLIER_OPTION_IDS:
        raise ValueError(
            f"Outlier pause on '{column}' has domain_context {domain_context!r}; "
            f"it must be one of {list(_OUTLIER_OPTION_IDS)}."
        )
    if option_ids != _OUTLIER_OPTION_IDS[domain_context]:
        raise ValueError(
            f"{domain_context.capitalize()} outlier pause on '{column}' must offer options "
            f"{_OUTLIER_OPTION_IDS[domain_context]} in that order; got {option_ids}."
        )
    note_field = _OUTLIER_NOTE_FIELD[domain_context]
    if _is_blank(parsed.get(note_field)):
        raise ValueError(f"Outlier pause on '{column}' has no {note_field}.")
    mask = _iqr_outlier_mask(df[column])
    outlier_count = int(mask.sum())
    if outlier_count == 0:
        raise ValueError(
            f"Outlier pause on '{column}', but the column has no values outside the IQR bounds."
        )
    stored_options = [
        {**option, "label": _OUTLIER_LABELS[option["id"]].format(n=outlier_count)}
        for option in options
    ]
    # Every number the user reads beside the options is Python's, from the same
    # mask the apply step will act on (the model's note text keeps its own).
    facts = _outlier_facts(df[column], mask, parsed.get("outlier_value"))
    return {
        **parsed,
        "outlier_count": outlier_count,
        "outlier_value": facts["value"],
        "sd_distance": facts["sd_distance"],
        "column_mean": facts["mean"],
        "column_std": facts["std"],
        "options": stored_options,
    }


def apply_missingness_backstop(
    parsed: dict,
    df: pd.DataFrame,
    answered: list,
    domain_hypothesis: Optional[str],
    provenance_hypothesis: Optional[str],
) -> dict:
    """Turn a report that skipped a mandatory missing-value pause into that pause.

    The >30% pause is mandatory in cleaner_system.md but the model decides it,
    and F2 showed a mandatory prompt rule can be skipped. A model pause passes
    through untouched. Otherwise the first column over the threshold that the
    user has not answered becomes a pause with factual, Python-written fields
    that say plainly the Cleaner did not assess the column. The report is
    discarded, so nothing is executed or saved before the user answers.
    """
    if parsed.get("type") in _PAUSE_STATUS_BY_TYPE:
        return parsed
    answered_columns = {
        entry.get("column_name")
        for entry in answered
        if entry.get("pause_type") == _MISSING_VALUE_PAUSE
    }
    for column in df.columns:
        if column in answered_columns:
            continue
        missing_count, missing_pct, total_rows = _missing_counts(df, column)
        if missing_pct <= _MISSING_PAUSE_THRESHOLD_PCT:
            continue
        series = df[column]
        method_id = "median" if _is_numeric_column(series) else "mode"
        recorded = series.dropna()
        if len(recorded) == 0:
            method_value = "no recorded values"
        elif method_id == "median":
            method_value = _format_value(recorded.median())
        else:
            method_value = _format_value(recorded.mode().iloc[0])
        samples = ", ".join(str(v) for v in recorded.drop_duplicates().head(5).tolist())
        logger.warning(
            "Cleaner returned a full report while '%s' is %.2f%% missing with no user answer; "
            "converted to a missing-value pause.",
            column, missing_pct,
        )
        return {
            "type": "missing_value_decision_required",
            "column_name": column,
            "missing_pct": missing_pct,
            "missing_count": missing_count,
            "total_rows": total_rows,
            "what_this_column_represents": (
                f"`{column}` ({series.dtype}); recorded values include: {samples or 'none'}."
            ),
            "provenance_interpretation": (
                "Not assessed. The Cleaner did not ask about this column, so the system "
                "generated this question and made no provenance-specific interpretation of "
                "the missing values. The Profiler's provenance hypothesis for the dataset is "
                f"'{provenance_hypothesis}'."
            ),
            "domain_context": (
                f"The Profiler's domain hypothesis is '{domain_hypothesis}'. More than 30% of "
                "this column is missing, which is the point at which the decision must come "
                "from you rather than the pipeline."
            ),
            "options": [
                {
                    "id": "impute",
                    "label": f"Impute the {missing_count} missing values with the {method_id}",
                    "method": f"{method_id} ({method_value})",
                    "method_id": method_id,
                    "assumption": (
                        "the missing values would have resembled the recorded ones; "
                        "this has not been checked"
                    ),
                },
                {
                    "id": "exclude_column",
                    "label": f"Exclude `{column}` from analysis entirely",
                    "consequence": f"removes the column but keeps all {total_rows} rows",
                },
                {
                    "id": "exclude_rows",
                    "label": f"Exclude the {missing_count} rows where `{column}` is missing",
                    "consequence": (
                        f"keeps the column but removes {missing_count} of {total_rows} rows "
                        f"({missing_pct}%)"
                    ),
                },
            ],
        }
    return parsed


def _same_value(after: object, before: object) -> bool:
    """Value equality that never raises (a categorical, a string or pd.NA after cleaning)."""
    try:
        return bool(after == before)
    except (TypeError, ValueError):
        return False


def _answered_outlier_columns(answered: list) -> set:
    return {
        entry.get("column_name")
        for entry in answered
        if entry.get("pause_type") == _OUTLIER_PAUSE
    }


def _outlier_review_columns(df: pd.DataFrame, answered: list) -> dict:
    """The columns the report's outlier_review must route, each with its outlier mask.

    The one source for the message's `outlier_review_columns`, the routing
    check, the outlier backstop and the outlier records: the columns the model
    is shown (the first 50) that have values outside the IQR bounds on the raw
    upload, less those the user excluded or already answered an outlier pause
    on. Insertion order is column order.
    """
    skip = _excluded_by_answer(answered) | _answered_outlier_columns(answered)
    required: dict = {}
    for column in df.columns[:_MESSAGE_COLUMN_LIMIT]:
        if column in skip:
            continue
        mask = _iqr_outlier_mask(df[column])
        if mask.any():
            required[column] = mask
    return required


def normalize_outlier_review(parsed: dict, required: dict) -> tuple[dict, dict]:
    """Read a report's outlier_review against the required columns. Never raises.

    Returns (routing, unrouted): routing maps each required column that has one
    valid routing to "medical", "financial" or "none"; unrouted maps every other
    required column to why it has none — no field, no entry, a value outside
    the three, or conflicting entries. Python never guesses a routing. Entries
    for columns that need none (not in the data, no outliers under the mask,
    beyond the first 50, excluded or already answered) are ignored.
    """
    review = parsed.get("outlier_review")
    if not isinstance(review, list):
        return {}, {column: "The report had no outlier_review." for column in required}
    contexts: dict = {}
    for entry in review:
        column = entry.get("column_name") if isinstance(entry, dict) else None
        if not isinstance(column, str) or column not in required:
            logger.warning("Ignored an outlier_review entry that routes no required column: %r", entry)
            continue
        contexts.setdefault(column, []).append(entry.get("domain_context"))
    routing: dict = {}
    unrouted: dict = {}
    for column in required:
        given = contexts.get(column)
        if not given:
            unrouted[column] = "The report's outlier_review had no entry for this column."
        elif any(context not in _OUTLIER_ROUTINGS for context in given):
            invalid = next(context for context in given if context not in _OUTLIER_ROUTINGS)
            unrouted[column] = (
                f"The report's outlier_review gave domain_context {invalid!r}, which is not "
                "medical, financial or none."
            )
        elif len(set(given)) > 1:
            unrouted[column] = (
                f"The report's outlier_review had conflicting entries for this column ({sorted(set(given))})."
            )
        else:
            routing[column] = given[0]
    return routing, unrouted


def _outlier_consequence(option_id: str, column: str) -> str:
    """What each outlier option runs (apply_user_decisions), and nothing more."""
    flag_column = f"{column}_outlier_flag"
    if option_id in _OUTLIER_KEEP_IDS:
        return (
            f"the values stay in `{column}` and in every statistic; their rows are marked "
            f"in `{flag_column}`"
        )
    return (
        f"the values are set to missing in `{column}`, so they drop out of every statistic; "
        f"their rows are kept and marked in `{flag_column}`"
    )


def apply_outlier_backstop(parsed: dict, df: pd.DataFrame, required: dict, routing: dict) -> dict:
    """Turn a report that routed a column to an outlier pause it never emitted into that pause.

    Unlike the missing-value backstop, this enforces the Cleaner's own routing
    judgment rather than replacing it: whether a column's outliers need the
    medical or financial pause is the Cleaner's call (cleaner_system.md §8.2,
    §8.3, Step 8), and Python only holds the report to it. A column routed
    "none" is never paused. A model pause passes through untouched. Otherwise
    the first required column routed medical or financial becomes that pause,
    with the fixed option ids and Python's numbers from the raw-upload mask,
    and the report is discarded.
    """
    if parsed.get("type") in _PAUSE_STATUS_BY_TYPE:
        return parsed
    for column, mask in required.items():
        context = routing.get(column)
        if context not in _OUTLIER_OPTION_IDS:
            continue
        facts = _outlier_facts(df[column], mask)
        logger.warning(
            "Cleaner routed '%s' as %s in its outlier review but returned a full report; "
            "converted to an outlier pause.",
            column, context,
        )
        return {
            "type": "outlier_decision_required",
            "domain_context": context,
            "column_name": column,
            "outlier_value": facts["value"],
            "outlier_count": facts["count"],
            "sd_distance": facts["sd_distance"],
            "column_mean": facts["mean"],
            "column_std": facts["std"],
            _OUTLIER_NOTE_FIELD[context]: (
                f"Not assessed. The Cleaner routed `{column}` as {context} in its outlier review "
                "but did not ask about it, so the system generated this question and made no "
                f"column-specific interpretation of these values. {_OUTLIER_DOMAIN_SENTENCE[context]} "
                f"{_outlier_facts_sentence(facts)}"
            ),
            "options": [
                {
                    "id": option_id,
                    "label": _OUTLIER_LABELS[option_id].format(n=facts["count"]),
                    "consequence": _outlier_consequence(option_id, column),
                }
                for option_id in _OUTLIER_OPTION_IDS[context]
            ],
        }
    return parsed


def build_outlier_records(
    df_raw: pd.DataFrame,
    df_cleaned: pd.DataFrame,
    required: dict,
    routing: dict,
    unrouted: dict,
) -> list:
    """One system-written decision per required column: its routing and its true final state.

    Written after every cleaning operation has run, and never executed or
    filtered. It replaces what filter_user_decided dropped on a user-decided
    column, and it is the one statement the report makes about a column the
    Cleaner routed "none" or did not route. Its state is computed from the
    cleaned data, so where a Cleaner decision (still routed by keyword)
    describes the same values differently, this record is the accurate one.
    """
    records: list = []
    for column, mask in required.items():
        if column not in df_cleaned.columns:
            continue  # removed by the Cleaner's own decision, which records it
        facts = _outlier_facts(df_raw[column], mask)
        present = mask[mask].index.intersection(df_cleaned.index)
        unchanged = sum(
            _same_value(after, before)
            for after, before in zip(df_cleaned.loc[present, column], df_raw.loc[present, column])
        )
        state = f"{unchanged} of the {facts['count']} value(s) are unchanged"
        if unchanged < facts["count"]:
            state += (
                f"; {facts['count'] - unchanged} were removed with their rows or changed by other "
                "cleaning decisions"
            )
        flag_column = f"{column}_outlier_flag"
        if flag_column in df_cleaned.columns:
            marked = int((df_cleaned.loc[present, flag_column] == 1).sum())
            state += f"; {marked} of them are marked in `{flag_column}`"
            total = int((df_cleaned[flag_column] == 1).sum())
            if total != marked:
                state += f", which marks {total} row(s) in all"
        else:
            state += "; they are not flagged"
        computed = (
            f"Computed from the cleaned data: {state}. Recorded by the system, not written by the "
            "Cleaner; where a Cleaner decision describes these values differently, this record is "
            "the accurate one."
        )
        if routing.get(column) == "none":
            action = (
                "Outlier review: the Cleaner routed these values 'none' (no user decision "
                "needed), so no question was asked."
            )
            reason = (
                f"{computed} The routing is the Cleaner's judgment, not a check: the system asks "
                "the user about outliers only when the Cleaner routes a column medical or financial."
            )
        else:
            why = unrouted.get(column) or (
                f"The Cleaner routed this column {routing.get(column)!r}, but no pause was asked."
            )
            action = (
                f"Not reviewed: the Cleaner's report gave no valid outlier routing for `{column}`, "
                "so no question was asked about these values."
            )
            reason = (
                f"{computed} {why} Treat these values as unreviewed: they may be data errors or "
                "genuine extremes."
            )
        issue = (
            f"{facts['count']} value(s) in `{column}` lie outside the IQR bounds "
            f"({_format_value(facts['lower'])} to {_format_value(facts['upper'])})"
            f"{_outlier_extreme_clause(facts)}"
        )
        records.append({"column_name": column, "issue": issue, "action": action, "reason": reason})
    return records


def summarize_outlier_review(
    df_raw: pd.DataFrame,
    df_cleaned: pd.DataFrame,
    answered: list,
    routing: dict,
) -> list:
    """The saved cleaning_report.outlier_review_summary: every column with outliers the
    model was shown, how it was routed, and how it was resolved. A different key
    and shape from the model's outlier_review ({column_name, domain_context})."""
    excluded = _excluded_by_answer(answered)
    answered_contexts = {
        entry.get("column_name"): (entry.get("question") or {}).get("domain_context")
        for entry in answered
        if entry.get("pause_type") == _OUTLIER_PAUSE
    }
    summary: list = []
    for column in df_raw.columns[:_MESSAGE_COLUMN_LIMIT]:
        if not _iqr_outlier_mask(df_raw[column]).any():
            continue
        if column in excluded:  # supersedes an earlier outlier answer (apply_user_decisions)
            context, resolution = None, "excluded_by_user"
        elif column in answered_contexts:
            context, resolution = answered_contexts[column], "user_decision"
        elif column not in df_cleaned.columns:
            context, resolution = routing.get(column), "column_removed"
        elif routing.get(column) == "none":
            context, resolution = "none", "routed_none"
        else:
            context, resolution = routing.get(column), "unreviewed"
        summary.append({"column_name": column, "routing": context, "resolution": resolution})
    return summary


def build_cleaner_resolutions(answered: list) -> list:
    """One resolution per answered Cleaner pause: the chosen option, taken from the question.

    Raises ValueError when the chosen id is not an option of the stored question
    (reachable only through /resume's escape hatch) — never a guess, never a
    silent skip.
    """
    resolutions: list = []
    for entry in answered:
        question = entry.get("question") if isinstance(entry.get("question"), dict) else {}
        option_id = (entry.get("response") or {}).get("option_id")
        offered = {
            option["id"]: option
            for option in question.get("options") or []
            if isinstance(option, dict) and isinstance(option.get("id"), str)
        }
        if option_id not in offered:
            raise ValueError(
                f"The answer to the {entry.get('pause_type')} on '{entry.get('column_name')}' "
                f"chose option {option_id!r}, which the question did not offer "
                f"({sorted(offered)}); refusing to guess."
            )
        resolutions.append({
            "pause_type": entry.get("pause_type"),
            "column_name": entry.get("column_name"),
            "option_id": option_id,
            "option": offered[option_id],
            "question": question,
        })
    return resolutions


def filter_user_decided(decisions: list, resolutions: list) -> list:
    """Drop every model decision on a column the user decided; Python executes and records those.

    The model's text would otherwise be routed by keyword and could run a
    different operation than the user chose, or none, while the report claimed
    the choice (errors.md 2026-09-25). Scoped by column, not by the guessed
    operation: an outlier issue must state its SD distance "from the mean",
    which the router reads as a mean fill. A legitimate model decision on the
    column (a type conversion, a fill of a different gap) is lost with it, but
    it is also absent from the report, so the report still matches what ran.
    That includes the model's outlier decision on a column whose missing values
    the user decided: build_outlier_records states those outliers' routing and
    true final state instead.
    """
    decided_columns = {r["column_name"] for r in resolutions}
    kept: list = []
    for decision in decisions:
        column = decision.get("column_name")
        if column in decided_columns:
            logger.warning(
                "Dropped the Cleaner's own decision on user-decided column '%s' (%s): %r",
                column, classify_cleaning_decision(decision), decision.get("action"),
            )
            continue
        kept.append(decision)
    return kept


def apply_user_decisions(
    df: pd.DataFrame,
    resolutions: list,
    outlier_masks: dict,
) -> tuple[pd.DataFrame, list, list, dict, list]:
    """Execute each user choice by option id and write its decision record.

    Missing-value choices run first, then outlier choices: the order the user
    was asked in, and the impute value was shown with the outliers present.
    outlier_masks are computed on the frame the question was asked about;
    they are aligned here by index label (reindex), because the model's own
    decisions may already have removed rows (duplicates). Nothing between the
    two resets the index.

    Returns (df, decisions, excluded_columns, outliers_flagged, user_decisions_incorporated).
    """
    df = df.copy()
    decisions: list = []
    excluded_columns: list = []
    outliers_flagged: dict = {}
    record: list = []
    ordered = [r for r in resolutions if r["pause_type"] == _MISSING_VALUE_PAUSE] + [
        r for r in resolutions if r["pause_type"] == _OUTLIER_PAUSE
    ]
    user_excluded = {
        r["column_name"]
        for r in resolutions
        if r["pause_type"] == _MISSING_VALUE_PAUSE and r["option_id"] == "exclude_column"
    }
    for resolution in ordered:
        column = resolution["column_name"]
        option_id = resolution["option_id"]
        option = resolution["option"]
        question = resolution["question"]
        if resolution["pause_type"] == _OUTLIER_PAUSE and column in user_excluded:
            # Answered before a later missing-value answer excluded the column
            # (only reachable out of the prompt's order, e.g. via the backstop):
            # the exclusion supersedes it. Recorded, not executed, not claimed.
            record.append({
                "pause_type": resolution["pause_type"],
                "column_name": column,
                "option_chosen": option_id,
                "resolution_summary": (
                    f"Not applied: the user excluded `{column}` at its missing-value pause, "
                    "which supersedes this outlier choice"
                ),
            })
            continue
        if column not in df.columns:
            raise ValueError(
                f"Cannot apply the user's '{option_id}' choice: column '{column}' is no longer "
                "in the dataset."
            )

        if resolution["pause_type"] == _MISSING_VALUE_PAUSE:
            missing_count = int(df[column].isna().sum())
            issue = (
                f"{missing_count} missing values in `{column}` "
                f"({missing_count / len(df) * 100 if len(df) else 0:.1f}% of {len(df)} rows), over "
                "the 30% threshold at which the user decides"
            )
            reason = (
                "Chosen by the user at the missing-value pause, not decided by the Cleaner. "
                f"The question the user answered said: {question.get('provenance_interpretation')} "
                f"{question.get('domain_context')}"
            )
            if option_id == "impute":
                method_id = option.get("method_id")
                recorded = df[column].dropna()
                if method_id in ("median", "mean") and not _is_numeric_column(df[column]):
                    raise ValueError(f"Cannot impute '{column}' with the {method_id}: not numeric.")
                if method_id not in _IMPUTE_METHODS or len(recorded) == 0:
                    raise ValueError(f"Cannot impute '{column}' with {method_id!r}.")
                value = {
                    "median": lambda: recorded.median(),
                    "mean": lambda: recorded.mean(),
                    "mode": lambda: recorded.mode().iloc[0],
                }[method_id]()
                df[column] = df[column].fillna(value)
                action = (
                    f"imputed the {missing_count} missing values in `{column}` with the "
                    f"{method_id} ({_format_value(value)})"
                )
                reason += f" The user accepted this method's assumption: {option.get('assumption')}"
            elif option_id == "exclude_column":
                df = df.drop(columns=[column])
                excluded_columns.append(column)
                action = f"excluded `{column}` from the dataset and from analysis"
            elif option_id == "exclude_rows":
                rows_before = len(df)
                df = df.dropna(subset=[column])
                action = f"removed the {rows_before - len(df)} rows where `{column}` was missing"
            elif option_id == _PRESERVE_OPTION_ID:
                action = (
                    f"kept `{column}` unchanged; its {missing_count} missing values stay missing "
                    "(nothing imputed, no rows removed)"
                )
            else:
                raise ValueError(f"Unknown missing-value option {option_id!r} for '{column}'.")
            action = f"User decision (missing-value pause): {action}"
        else:
            domain_context = question.get("domain_context")
            mask = outlier_masks.get(column)
            if mask is None:
                raise ValueError(f"No outlier mask was computed for '{column}'.")
            mask = mask.reindex(df.index, fill_value=False).astype(bool)
            outlier_count = int(mask.sum())
            flagged_values = df.loc[mask, column]
            value_range = (
                f"{_format_value(flagged_values.min())} to {_format_value(flagged_values.max())}"
                if outlier_count
                else "none remaining"
            )
            flag_column = f"{column}_outlier_flag"
            df[flag_column] = mask.astype(int)
            if option_id in _OUTLIER_KEEP_IDS:
                action = (
                    f"kept the {outlier_count} outlier value(s) in `{column}` as valid data; "
                    f"marked in `{flag_column}`"
                )
            elif option_id in ("flag_as_suspected_error", "exclude_pending_clinical_review"):
                df.loc[mask, column] = np.nan
                pending = (
                    "pending clinical review"
                    if option_id == "exclude_pending_clinical_review"
                    else "as suspected error"
                )
                action = (
                    f"removed the {outlier_count} outlier value(s) in `{column}` from aggregate "
                    f"statistics {pending} (set to missing); rows kept and marked in `{flag_column}`"
                )
            else:
                raise ValueError(f"Unknown outlier option {option_id!r} for '{column}'.")
            outliers_flagged[column] = outlier_count
            issue = f"{outlier_count} outlier value(s) in `{column}` outside the IQR bounds ({value_range})"
            reason = (
                f"Chosen by the user at the {domain_context} outlier pause, not decided by the "
                "Cleaner. Domain reasoning shown to the user: "
                f"{question.get(_OUTLIER_NOTE_FIELD.get(domain_context, ''), '')}"
            )
            action = f"User decision ({domain_context} outlier pause): {action}"

        decisions.append({"column_name": column, "issue": issue, "action": action, "reason": reason})
        record.append({
            "pause_type": resolution["pause_type"],
            "column_name": column,
            "option_chosen": option_id,
            "resolution_summary": action,
        })
    return df, decisions, excluded_columns, outliers_flagged, record


async def cleaner_node(state: PipelineState) -> dict:
    analysis_id = state["analysis_id"]

    try:
        tracer = create_tracer("cleaner")

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "cleaning",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )

        df = await load_dataframe_from_uploads(state["stored_filename"])
        rows_before = len(df)
        cols_before = len(df.columns)

        profile_report = state.get("profile_report") or {}
        missingness_patterns = await asyncio.to_thread(analyze_missingness_patterns, df)
        interactions = await asyncio.to_thread(detect_interactions, df, profile_report)

        domain_hypothesis = state.get("profiler_domain_hypothesis")
        provenance_hypothesis = state.get("profiler_provenance_hypothesis")
        top_3_concerns = state.get("profiler_top_3_concerns")
        # Every Cleaner pause answered so far, in order (the pause-wait node
        # appends one per answer). Resolved before the LLM call so an unusable
        # answer fails before any spend.
        answered = state.get("answered_cleaner_pauses") or []
        resolutions = build_cleaner_resolutions(answered)
        # Masks on the frame the questions were asked about, before any row
        # is removed; apply_user_decisions aligns them by index label.
        outlier_masks = {
            r["column_name"]: _iqr_outlier_mask(df[r["column_name"]])
            for r in resolutions
            if r["pause_type"] == _OUTLIER_PAUSE and r["column_name"] in df.columns
        }
        # The columns whose outliers the report must route, from the same mask.
        review_columns = await asyncio.to_thread(_outlier_review_columns, df, answered)

        user_message = build_cleaner_message(
            df=df,
            profile_report=profile_report,
            domain_hypothesis=domain_hypothesis,
            provenance_hypothesis=provenance_hypothesis,
            top_3_concerns=top_3_concerns,
            resolved_pauses=[
                {
                    "pause_type": r["pause_type"],
                    "column_name": r["column_name"],
                    "option_id": r["option_id"],
                    "chosen_option": r["option"],
                }
                for r in resolutions
            ],
            missingness_patterns=missingness_patterns,
            domain_resolution=profile_report.get("domain_resolution"),
            outlier_review_columns=list(review_columns),
        )
        system_prompt = load_system_prompt("cleaner")

        response = await asyncio.to_thread(
            lambda: client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=8000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        )

        parsed = parse_json_response(response.content[0].text)
        parsed = apply_missingness_backstop(
            parsed, df, answered, domain_hypothesis, provenance_hypothesis
        )
        routing, unrouted = normalize_outlier_review(parsed, review_columns)
        parsed = apply_outlier_backstop(parsed, df, review_columns, routing)

        pause_type = _PAUSE_STATUS_BY_TYPE.get(parsed.get("type"))
        if pause_type is not None:
            pause_key = (
                "missing_value_pause_data"
                if pause_type == _MISSING_VALUE_PAUSE
                else "outlier_pause_data"
            )
            return {
                pause_key: validate_cleaner_pause(parsed, df, answered),
                "user_pause_response": None,
            }

        decisions_data = filter_user_decided(parsed.get("decisions", []), resolutions)

        df_cleaned, excluded_columns, outlier_flagged = await asyncio.to_thread(
            execute_cleaning_operations, df, decisions_data
        )
        (
            df_cleaned,
            user_decisions,
            user_excluded_columns,
            user_outliers_flagged,
            user_decisions_incorporated,
        ) = await asyncio.to_thread(apply_user_decisions, df_cleaned, resolutions, outlier_masks)
        # Appended last: never executed, never filtered (build_outlier_records).
        outlier_records = await asyncio.to_thread(
            build_outlier_records, df, df_cleaned, review_columns, routing, unrouted
        )
        decisions_data = decisions_data + user_decisions + outlier_records
        excluded_columns = excluded_columns + user_excluded_columns
        outlier_flagged = {**outlier_flagged, **user_outliers_flagged}

        # Its own key: the model's outlier_review has a different shape.
        outlier_review_summary = await asyncio.to_thread(
            summarize_outlier_review, df, df_cleaned, answered, routing
        )

        rows_after = len(df_cleaned)
        cols_after = len(df_cleaned.columns)
        summary = {
            "rows_before": rows_before,
            "rows_after": rows_after,
            "rows_removed": rows_before - rows_after,
            "columns_before": cols_before,
            "columns_after": cols_after,
            "columns_removed": cols_before - cols_after,
        }

        re_profile = await asyncio.to_thread(re_profile_dataframe, df_cleaned)

        local_parquet_path = str(
            Path("backend") / "uploads" / f"{analysis_id}.parquet"
        )
        await asyncio.to_thread(
            lambda: df_cleaned.to_parquet(local_parquet_path, index=False)
        )

        await upload_to_storage(analysis_id, local_parquet_path)

        try:
            await cleanup_temp_file(state["stored_filename"])
        except Exception as e:
            logger.warning(
                "Failed to delete original uploaded file for analysis_id=%s: %s",
                analysis_id,
                e,
            )

        try:
            await cleanup_temp_file(f"{analysis_id}.parquet")
        except Exception as e:
            logger.warning(
                "Failed to delete local parquet file for analysis_id=%s: %s",
                analysis_id,
                e,
            )

        profiler_concerns_addressed = []
        if top_3_concerns:
            for concern in top_3_concerns:
                concern_str = str(concern).lower()
                matched = any(
                    concern_str in str(d.get("reason", "")).lower()
                    or concern_str in str(d.get("issue", "")).lower()
                    for d in decisions_data
                )
                profiler_concerns_addressed.append({
                    "concern": concern,
                    "addressed": matched,
                })

        full_cleaning_report = {
            "decisions": decisions_data,
            "profiler_concerns_addressed": profiler_concerns_addressed,
            "summary": summary,
            "re_profile_verification": re_profile,
            "interactions_detected": interactions,
            "user_decisions_incorporated": user_decisions_incorporated,
            "outlier_review_summary": outlier_review_summary,
        }

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "cleaned",
                "cleaning_report": full_cleaning_report,
                "cleaning_decisions": decisions_data,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )

        return {
            "cleaning_report": full_cleaning_report,
            "cleaner_key_decisions": decisions_data,
            "cleaner_excluded_columns": excluded_columns,
            "cleaner_outliers_handled": outlier_flagged,
            "cleaner_user_decisions_incorporated": user_decisions_incorporated,
            "missing_value_pause_data": None,
            "outlier_pause_data": None,
            "user_pause_response": None,
        }

    except Exception as exc:
        logger.exception("Cleaner node failed for analysis_id=%s", analysis_id)
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
