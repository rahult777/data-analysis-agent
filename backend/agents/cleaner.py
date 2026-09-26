"""The Thoughtful Cleaner — Agent 2 in the data analysis pipeline.

Reads the ProfileReport, makes domain-aware decisions about data quality,
executes cleaning operations, and produces a fully documented CleaningReport.
"""

import asyncio
import json
import logging
import math
import warnings
from collections import Counter
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
# The Cleaner's own decisions (cleaner_system.md, "The Operations"): a closed set,
# each checked and run by Python. Nothing is executed from a decision's wording.
_MODEL_OPERATIONS = (
    "convert_type", "standardize_values", "fill_missing", "leave_missing", "flag_outliers", "note",
)
# Changes the prompt reserves for the system (duplicates, Step 4) or the user
# (rows, columns and outlier values, Step 9), named so a request gets a precise refusal.
_RESERVED_OPERATIONS: dict[str, str] = {
    **dict.fromkeys(
        ("drop_rows", "remove_rows", "exclude_rows", "delete_rows"),
        "removing rows is decided only by the user, at a missing-value pause",
    ),
    **dict.fromkeys(
        ("drop_column", "remove_column", "exclude_column", "delete_column"),
        "removing a column is decided only by the user, at a missing-value pause",
    ),
    **dict.fromkeys(
        ("remove_outliers", "drop_outliers", "exclude_outliers", "delete_outliers"),
        "removing or excluding outlier values is decided only by the user, at an outlier pause",
    ),
    **dict.fromkeys(
        ("remove_duplicates", "drop_duplicates", "dedupe", "deduplicate"),
        "the system removes exact duplicate rows itself",
    ),
}
_CONVERT_TARGETS = ("string", "numeric", "integer", "datetime")
_FILL_METHODS = ("median", "mean", "mode", "constant")
# A text column with at most this many distinct values is sent in full
# (distinct_values), so standardize_values only ever maps values the model saw.
_DISTINCT_VALUES_LIMIT = 30
# When each operation runs. The user's pause choices run between "fill" and "flag".
_PHASE_OF: dict[str, str] = {
    "convert_type": "convert",
    "standardize_values": "standardize",
    "fill_missing": "fill",
    "leave_missing": "fill",
    "flag_outliers": "flag",
    "note": "note",
}
_MODEL_PHASES_BEFORE_USER = ("convert", "standardize", "fill")
_MODEL_PHASES_AFTER_USER = ("flag",)
# Under the SDK's non-streaming ceiling (3600 s × 16000 / 128000 = 450 s < 600 s).
_CLEANER_MAX_TOKENS = 16000


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
    # "2021" while the label is still int 2021 — the decision's column then
    # matches nothing and no decision for that column can run. A datetime
    # key raises TypeError outright. map(str), not
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
    interactions: Optional[list] = None,
    distinct_values: Optional[dict] = None,
    duplicate_row_count: Optional[int] = None,
) -> str:
    """The Cleaner's user message. `distinct_values` and `duplicate_row_count` are
    computed here when not given (cleaner_node passes the ones it already has)."""
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

    semantically_categorical = (profile_report or {}).get("semantically_categorical_columns")
    message_data: dict = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns_included": len(columns),
        "column_info": col_info,
        "distinct_values": distinct_values if distinct_values is not None else _distinct_value_columns(df),
        "domain_hypothesis": domain_hypothesis,
        "provenance_hypothesis": provenance_hypothesis,
        "top_3_concerns": top_3_concerns or [],
        # The Profiler's judgment (Step 5); its other structural fields are
        # whole-table claims from a sample and are not sent (decisions.md, Build G).
        "semantically_categorical_columns": (
            semantically_categorical if isinstance(semantically_categorical, list) else []
        ),
        # Computed by the system over every row, never the Profiler's copy (0 on
        # messy_data.csv against 15 real duplicates).
        "duplicate_row_count": (
            duplicate_row_count if duplicate_row_count is not None else int(df.duplicated().sum())
        ),
        "missingness_patterns": missingness_patterns,
        "interactions_detected": interactions or [],
    }

    if profile_report:
        message_data["profile_summary"] = {
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


def re_profile_dataframe(df: pd.DataFrame, discrepancies: Optional[list] = None) -> dict:
    """Counts on the cleaned frame, plus every operation whose own check failed.

    `passed` still means "no missing value remains" (a pessimistic, pre-existing
    meaning, logged in errors.md); `discrepancies` lists each executed operation
    that did not have the effect it should have (run_model_operations).
    """
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
        "discrepancies": list(discrepancies or []),
    }


def _is_numeric_column(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _is_text_column(series: pd.Series) -> bool:
    """Object or string dtype whose recorded values are all str (an all-missing one counts)."""
    if not (series.dtype == object or isinstance(series.dtype, pd.StringDtype)):
        return False
    return pd.api.types.infer_dtype(series, skipna=True) in ("string", "empty")


def _distinct_value_columns(df: pd.DataFrame) -> dict:
    """{column: {value: count}}, most frequent first, for every text column the model
    is shown (the first 50) with 1 to 30 distinct recorded values. The one source for
    the message's distinct_values and the check that standardize_values only maps a
    column whose every value the model saw."""
    shown: dict = {}
    for column in df.columns[:_MESSAGE_COLUMN_LIMIT]:
        series = df[column]
        if not _is_text_column(series):
            continue
        counts = series.value_counts(dropna=True)
        if 0 < len(counts) <= _DISTINCT_VALUES_LIMIT:
            shown[column] = {str(value): int(count) for value, count in counts.items()}
    return shown


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
    outlier pause, the outlier records, apply_user_decisions and the Cleaner's
    flag_outliers, so the values a user answers about and the rows the Cleaner
    marks are exactly the ones the model was shown. (detect_interactions still
    computes its own bounds — errors.md 2026-09-25, IQR.)
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


def _excluded_by_resolution(resolutions: list) -> set:
    """The columns the user excluded, read from build_cleaner_resolutions' output (the
    same rule as _excluded_by_answer, which reads the raw answered pauses)."""
    return {
        r["column_name"]
        for r in resolutions
        if r["pause_type"] == _MISSING_VALUE_PAUSE and r["option_id"] == "exclude_column"
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
    cleaned data, so where the Cleaner's own text (its reasoning, or a note)
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


def filter_user_decided(decisions: list, resolutions: list) -> tuple[list, list]:
    """Keep the Cleaner's decisions that may run beside the user's choices; return (kept, dropped).

    Python executes and records the user's choices itself (apply_user_decisions).
    On a column the user decided, the Cleaner keeps a `note`; a `flag_outliers`
    when the user answered only the missing-value pause there (the flag adds its
    own column and changes no value); and a `fill_missing` or `leave_missing` when
    the user answered only the outlier pause there — its smaller gaps are then
    handled and recorded, not silently dropped. Fills run before the user's
    outlier choices (_MODEL_PHASES_BEFORE_USER), so a fill touches only the
    originally missing values and the values the user excludes as outliers stay
    missing. Everything else would restate the user's choice (cleaner_system.md
    §8.4) or change the column the user was asked about — a conversion to text
    before the user's median would raise after the user had answered. Every
    decision on a column the user excluded is dropped. The operation is read from
    the decision's `operation` field only, never from its wording.
    """
    decided = {r["column_name"] for r in resolutions}
    excluded = _excluded_by_resolution(resolutions)
    outlier_answered = {r["column_name"] for r in resolutions if r["pause_type"] == _OUTLIER_PAUSE}
    missing_answered = {r["column_name"] for r in resolutions if r["pause_type"] == _MISSING_VALUE_PAUSE}
    kept: list = []
    dropped: list = []
    for decision in decisions:
        column = decision.get("column_name") if isinstance(decision, dict) else None
        column = column if isinstance(column, str) else None  # anything else is rejected later
        operation = decision.get("operation") if isinstance(decision, dict) else None
        allowed = (
            column not in decided
            or (
                column not in excluded
                and (
                    operation == "note"
                    or (operation == "flag_outliers" and column not in outlier_answered)
                    or (operation in ("fill_missing", "leave_missing") and column not in missing_answered)
                )
            )
        )
        if allowed:
            kept.append(decision)
            continue
        logger.warning(
            "Dropped the Cleaner's own decision on user-decided column '%s' (operation %r): %r",
            column, operation, decision.get("action"),
        )
        dropped.append(decision)
    return kept, dropped


# Shared primitives: the one implementation of each change to the data, used by
# the user's pause choices (apply_user_decisions) and the Cleaner's own
# operations (run_model_operations). Each returns a new frame; the caller checks
# preconditions and writes the record.


def _impute_value(series: pd.Series, method: str) -> object:
    """The median, mean or mode of a column's recorded values."""
    recorded = series.dropna()
    return {
        "median": lambda: recorded.median(),
        "mean": lambda: recorded.mean(),
        "mode": lambda: recorded.mode().iloc[0],
    }[method]()


def _fill_missing(df: pd.DataFrame, column: str, value: object) -> pd.DataFrame:
    df = df.copy()
    df[column] = df[column].fillna(value)
    return df


def _drop_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    return df.drop(columns=[column])


def _drop_rows_missing(df: pd.DataFrame, column: str) -> pd.DataFrame:
    return df.dropna(subset=[column])


def _mark_rows(df: pd.DataFrame, flag_column: str, mask: pd.Series) -> pd.DataFrame:
    """Write a 0/1 flag column from a mask already aligned to df's index."""
    df = df.copy()
    df[flag_column] = mask.astype(int)
    return df


def _set_missing(df: pd.DataFrame, column: str, mask: pd.Series) -> pd.DataFrame:
    """Set the masked values of a column to missing; rows are kept."""
    df = df.copy()
    df.loc[mask, column] = np.nan
    return df


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
    user_excluded = _excluded_by_resolution(resolutions)
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
                value = _impute_value(df[column], method_id)
                df = _fill_missing(df, column, value)
                action = (
                    f"imputed the {missing_count} missing values in `{column}` with the "
                    f"{method_id} ({_format_value(value)})"
                )
                reason += f" The user accepted this method's assumption: {option.get('assumption')}"
            elif option_id == "exclude_column":
                df = _drop_column(df, column)
                excluded_columns.append(column)
                action = f"excluded `{column}` from the dataset and from analysis"
            elif option_id == "exclude_rows":
                rows_before = len(df)
                df = _drop_rows_missing(df, column)
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
            df = _mark_rows(df, flag_column, mask)
            if option_id in _OUTLIER_KEEP_IDS:
                action = (
                    f"kept the {outlier_count} outlier value(s) in `{column}` as valid data; "
                    f"marked in `{flag_column}`"
                )
            elif option_id in ("flag_as_suspected_error", "exclude_pending_clinical_review"):
                df = _set_missing(df, column, mask)
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


def remove_duplicate_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    """The system's Step 4: remove exact duplicate rows before any other cleaning.

    Always runs, with Python's own count; the Cleaner neither decides nor
    reports it, so a false "no duplicates" claim cannot reach the report.
    Returns (frame, decision record, operations entry). The first occurrence of
    each row is kept with its index label, which the outlier masks rely on.
    """
    rows_before = len(df)
    duplicated = df.duplicated()
    count = int(duplicated.sum())
    cleaned = df[~duplicated]  # what drop_duplicates() does, with the mask computed once
    if count:
        issue = f"{count} exact duplicate row(s) (identical in every column) in the uploaded data"
        action = f"System step: removed the {count} exact duplicate rows, keeping the first occurrence of each"
    else:
        issue = "No exact duplicate rows in the uploaded data"
        action = "System step: checked for exact duplicate rows and found none; nothing removed"
    record = {
        "column_name": None,
        "issue": issue,
        "action": action,
        "reason": (
            "Recorded by the system, not written by the Cleaner. Exact duplicates are removed "
            "before any other cleaning, so that every count, fill value and statistic describes "
            f"each record once; {rows_before} rows became {len(cleaned)}."
        ),
    }
    entry = {
        "source": "system",
        "operation": "remove_duplicates",
        "column_name": None,
        "params": {},
        "status": "executed",
        "detail": action,
        "facts": {"duplicate_rows": count, "rows_before": rows_before, "rows_after": len(cleaned)},
    }
    return cleaned, record, entry


def _is_scalar_constant(value: object) -> bool:
    if isinstance(value, str):
        return True
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _param_problem(operation: str, params: dict, df: pd.DataFrame) -> Optional[str]:
    """Why a decision's params do not fit its operation, or None. Shape only: whether
    the operation is possible for the column's data is checked when it runs."""
    if operation == "convert_type":
        if params.get("to") not in _CONVERT_TARGETS:
            return f"params.to must be one of {list(_CONVERT_TARGETS)}, got {params.get('to')!r}"
    elif operation == "standardize_values":
        mapping = params.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            return "params.mapping must be a non-empty object of {existing value: replacement}"
        if not all(isinstance(k, str) for k in mapping) or not all(
            isinstance(v, str) and v.strip() for v in mapping.values()
        ):
            return "every params.mapping key and replacement must be non-empty text"
    elif operation == "fill_missing":
        method = params.get("method")
        if method not in _FILL_METHODS:
            return f"params.method must be one of {list(_FILL_METHODS)}, got {method!r}"
        if method == "constant" and not _is_scalar_constant(params.get("value")):
            return f"a constant fill needs params.value as text or a finite number, got {params.get('value')!r}"
    elif operation == "note" and "columns" in params:
        columns = params["columns"]
        if not isinstance(columns, list) or not all(isinstance(c, str) and c in df.columns for c in columns):
            return "params.columns must list columns that are in the data"
    return None


def _reject(item: dict, detail: str, contract: bool = False) -> None:
    item["status"] = "not_executed"
    item["detail"] = detail
    item["contract"] = contract


def plan_model_decisions(decisions: object, df: pd.DataFrame, numbers: Optional[list] = None) -> list:
    """Check every Cleaner decision's operation before anything runs. Never raises.

    One item per decision, in the Cleaner's order: "planned", or "not_executed"
    with the reason. `numbers` gives each decision's position in the Cleaner's
    full report (before filter_user_decided), so "decision 3" in a record means
    the report's third decision. `contract` marks a decision with no valid operation
    (missing, unknown, reserved, malformed params, or no usable column); a
    decision without a column is shown only as a note naming two or more
    columns (`printed`), so dataset-level prose like "no duplicate rows
    present" never reaches the report. Contradicting decisions on one column
    (two fills, a fill and leave_missing, two conversions, two mappings) are
    all refused; an exact repeat is refused as a repeat. Nothing is guessed.
    """
    items: list = []
    for position, decision in enumerate(decisions if isinstance(decisions, list) else []):
        item = {
            "index": numbers[position] if numbers is not None else position,
            "decision": decision if isinstance(decision, dict) else {},
            "column_name": None,
            "operation": None,
            "params": {},
            "status": "planned",
            "detail": "",
            "contract": False,
            "printed": False,
            "facts": {},
            "verification": None,
        }
        items.append(item)
        if not isinstance(decision, dict):
            _reject(item, "the decision is not an object", contract=True)
            continue
        column = decision.get("column_name")
        operation = decision.get("operation")
        params = decision.get("params", {})
        params = {} if params is None else params
        item["column_name"] = column if isinstance(column, str) else None
        item["operation"] = operation if isinstance(operation, str) else None
        item["params"] = params if isinstance(params, dict) else {}
        item["printed"] = isinstance(column, str) and bool(column.strip())
        if not isinstance(operation, str) or not operation.strip():
            _reject(item, "the decision names no operation", contract=True)
        elif operation in _RESERVED_OPERATIONS:
            _reject(item, f"'{operation}' is not an operation the Cleaner can run: {_RESERVED_OPERATIONS[operation]}", contract=True)
        elif operation not in _MODEL_OPERATIONS:
            _reject(item, f"'{operation}' is not one of the Cleaner's operations ({', '.join(_MODEL_OPERATIONS)})", contract=True)
        elif not isinstance(params, dict):
            _reject(item, "its params are not an object", contract=True)
        elif column is None:
            columns = params.get("columns")
            if operation == "note" and isinstance(columns, list) and len(columns) >= 2 and not _param_problem(operation, params, df):
                item["printed"] = True
            else:
                _reject(item, "a decision with no column can only be a note naming two or more columns", contract=True)
        elif not isinstance(column, str) or column not in df.columns:
            _reject(item, f"there is no column {column!r} in the data", contract=True)
        else:
            problem = _param_problem(operation, params, df)
            if problem:
                _reject(item, problem, contract=True)

    by_column: dict = {}
    for item in items:
        if item["status"] == "planned" and item["operation"] != "note":
            by_column.setdefault(item["column_name"], []).append(item)
    for column, group in by_column.items():
        seen: dict = {}
        unique: list = []
        for item in group:
            key = (item["operation"], json.dumps(item["params"], sort_keys=True, default=str))
            if key in seen:
                _reject(item, f"it repeats decision {seen[key] + 1} on `{column}`")
                continue
            seen[key] = item["index"]
            unique.append(item)
        conflicting: list = []
        for kinds in (("fill_missing", "leave_missing"), ("convert_type",), ("standardize_values",)):
            members = [item for item in unique if item["operation"] in kinds]
            if len(members) > 1:
                conflicting.append(members)
        for members in conflicting:
            numbers = ", ".join(str(item["index"] + 1) for item in members)
            for item in members:
                _reject(
                    item,
                    f"decisions {numbers} on `{column}` contradict each other "
                    f"({', '.join(_describe_request(m) for m in members)}), so none of them was run",
                )
    return items


def _describe_request(item: dict) -> str:
    """The requested operation, rendered from its structured fields only."""
    operation, params = item["operation"], item["params"]
    if operation is None:
        return "a decision with no operation"
    if operation == "convert_type":
        return f"convert_type to {params.get('to')}"
    if operation == "fill_missing":
        if params.get("method") == "constant":
            return f"fill_missing with the value {params.get('value')!r}"
        return f"fill_missing with the {params.get('method')}"
    if operation == "standardize_values" and isinstance(params.get("mapping"), dict):
        return f"standardize_values ({len(params['mapping'])} value(s) to replace)"
    if operation in _MODEL_OPERATIONS:
        return operation
    return f"the operation {operation!r}"


def _examples(values: pd.Series) -> str:
    return ", ".join(repr(v) for v in values.drop_duplicates().head(5).tolist())


def _run_convert(
    df: pd.DataFrame, item: dict, df_raw: pd.DataFrame, shown: dict, excluded: dict
) -> pd.DataFrame:
    column, target = item["column_name"], item["params"]["to"]
    series = df[column]
    before = str(series.dtype)
    recorded = int(series.notna().sum())
    if pd.api.types.is_bool_dtype(series):
        _reject(item, f"`{column}` holds True/False values, which are not converted")
        return df
    if target == "string":
        if _is_text_column(series):
            _reject(item, f"`{column}` is already stored as text")
            return df
        # Built explicitly as object: `where` would keep a datetime64 or Int64 dtype.
        converted = pd.Series(
            np.where(series.isna(), np.nan, series.astype(str)), index=series.index, dtype=object
        )
    elif target in ("numeric", "integer"):
        if pd.api.types.is_datetime64_any_dtype(series):
            _reject(item, f"`{column}` holds dates, which are not converted to numbers")
            return df
        if target == "numeric" and _is_numeric_column(series):
            _reject(item, f"`{column}` is already numeric ({before})")
            return df
        if target == "integer" and pd.api.types.is_integer_dtype(series):
            _reject(item, f"`{column}` already holds whole numbers ({before})")
            return df
        numbers = series if _is_numeric_column(series) else pd.to_numeric(series, errors="coerce")
        lost = series.notna() & numbers.isna()
        if lost.any():
            _reject(
                item,
                f"{int(lost.sum())} recorded value(s) in `{column}` are not numbers "
                f"(e.g. {_examples(series[lost])}), and converting would erase them",
            )
            return df
        if target == "integer":
            recorded_numbers = numbers.dropna().astype(float)
            fractional = recorded_numbers[~np.isfinite(recorded_numbers) | (recorded_numbers % 1 != 0)]
            if len(fractional):
                _reject(
                    item,
                    f"{len(fractional)} value(s) in `{column}` are not whole numbers "
                    f"(e.g. {_examples(fractional)})",
                )
                return df
            converted = numbers.astype("Int64")
        else:
            converted = numbers
    else:  # datetime
        if pd.api.types.is_datetime64_any_dtype(series):
            _reject(item, f"`{column}` is already stored as dates ({before})")
            return df
        if not _is_text_column(series):
            _reject(item, f"only text is converted to dates; `{column}` is {before}")
            return df
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            converted = pd.to_datetime(series, errors="coerce")
        lost = series.notna() & converted.isna()
        if lost.any():
            _reject(
                item,
                f"{int(lost.sum())} recorded value(s) in `{column}` are not dates "
                f"(e.g. {_examples(series[lost])}), and converting would erase them",
            )
            return df
    df = df.copy()
    df[column] = converted
    matches = {
        "string": _is_text_column,
        "numeric": _is_numeric_column,
        "integer": pd.api.types.is_integer_dtype,
        "datetime": pd.api.types.is_datetime64_any_dtype,
    }[target](df[column])
    kept = int(df[column].notna().sum())
    if not matches or kept != recorded:
        item["verification"] = (
            f"`{column}` is {df[column].dtype} with {kept} of {recorded} recorded values after the conversion"
        )
    item["status"] = "executed"
    item["facts"] = {"dtype_before": before, "dtype_after": str(df[column].dtype), "recorded": recorded}
    return df


def _run_standardize(
    df: pd.DataFrame, item: dict, df_raw: pd.DataFrame, shown: dict, excluded: dict
) -> pd.DataFrame:
    column, mapping = item["column_name"], item["params"]["mapping"]
    series = df[column]
    if column not in shown:
        _reject(
            item,
            f"the Cleaner was not shown every value of `{column}` (only text columns with at most "
            f"{_DISTINCT_VALUES_LIMIT} distinct values are sent in full)",
        )
        return df
    if not _is_text_column(series):
        _reject(item, f"`{column}` is no longer a text column (it is {series.dtype})")
        return df
    # Checked against the values the model was shown (the uploaded data), so a
    # variant that only occurred in a removed duplicate row is not an error.
    unknown = [key for key in mapping if key not in shown[column]]
    if unknown:
        _reject(
            item,
            f"{len(unknown)} of the values to replace are not in `{column}` "
            f"({', '.join(repr(k) for k in unknown[:5])}), so nothing was replaced",
        )
        return df
    changes = {key: value for key, value in mapping.items() if key != value}
    counts = {key: int((series == key).sum()) for key in changes}
    if not changes or not sum(counts.values()):
        _reject(item, f"none of the mapped values of `{column}` would change")
        return df
    distinct_before = int(series.nunique())
    df = df.copy()
    df[column] = series.map(lambda value: changes.get(value, value) if isinstance(value, str) else value)
    remaining = [key for key in changes if key not in changes.values() and (df[column] == key).any()]
    if remaining or int(df[column].notna().sum()) != int(series.notna().sum()):
        item["verification"] = f"values still present in `{column}` after the replacement: {remaining}"
    item["status"] = "executed"
    item["facts"] = {
        "replaced": {key: {"to": changes[key], "cells": counts[key]} for key in changes},
        "cells_changed": sum(counts.values()),
        "distinct_before": distinct_before,
        "distinct_after": int(df[column].nunique()),
    }
    return df


def _constant_problem(series: pd.Series, column: str, value: object) -> Optional[str]:
    if pd.api.types.is_bool_dtype(series):
        return f"`{column}` holds True/False values, which are not filled with a constant"
    if pd.api.types.is_datetime64_any_dtype(series):
        return f"`{column}` holds dates, which are not filled with a constant"
    if _is_numeric_column(series):
        if isinstance(value, str):
            return f"`{column}` is numeric ({series.dtype}), so the fill value must be a number; {value!r} is text"
        if pd.api.types.is_integer_dtype(series) and float(value) % 1 != 0:
            return f"`{column}` holds whole numbers ({series.dtype}), so the fill value must be one; {value!r} is not"
        return None
    if _is_text_column(series):
        if not isinstance(value, str):
            return f"`{column}` is text, so the fill value must be text; {value!r} is a number"
        return None
    return f"`{column}` is {series.dtype}, which is not filled with a constant"


def _run_fill(
    df: pd.DataFrame, item: dict, df_raw: pd.DataFrame, shown: dict, excluded: dict
) -> pd.DataFrame:
    column = item["column_name"]
    series = df[column]
    missing = int(series.isna().sum())
    if item["operation"] == "leave_missing":
        if missing == 0:
            _reject(item, f"`{column}` has no missing values, so there were none to leave")
            return df
        item["status"] = "executed"
        item["facts"] = {"missing": missing, "rows": len(df)}
        # The rows left missing, re-checked on the final frame (build_model_records):
        # a user's exclude_rows may later remove some of them, which is not a failure.
        item["missing_rows"] = series.index[series.isna()]
        return df
    method = item["params"]["method"]
    if missing == 0:
        _reject(item, f"`{column}` has no missing values")
        return df
    # Where the user excluded this column's outliers as errors, the fill value is
    # computed without them: the fill runs before the user's choice is applied, and
    # a value built from rejected errors was never shown to the user.
    excluded_mask = excluded.get(column)
    basis = series
    excluded_count = 0
    if excluded_mask is not None:
        aligned = excluded_mask.reindex(series.index, fill_value=False).astype(bool)
        excluded_count = int(aligned.sum())
        basis = series[~aligned]
    recorded = basis.dropna()
    if method in ("median", "mean", "mode") and len(recorded) == 0:
        _reject(item, f"`{column}` has no recorded values to compute a {method} from")
        return df
    if method in ("median", "mean"):
        if not _is_numeric_column(series):
            _reject(item, f"{method} imputation needs a numeric column; `{column}` is {series.dtype}")
            return df
        value = _impute_value(basis, method)
        if pd.api.types.is_integer_dtype(series):
            if float(value) % 1 != 0:
                _reject(
                    item,
                    f"the {method} of `{column}` is {_format_value(value)}, not a whole number, "
                    f"and the column holds whole numbers ({series.dtype})",
                )
                return df
            value = int(value)
    elif method == "mode":
        value = _impute_value(basis, "mode")
    else:
        value = item["params"]["value"]
        problem = _constant_problem(series, column, value)
        if problem:
            _reject(item, problem)
            return df
    dtype_before = str(series.dtype)
    df = _fill_missing(df, column, value)
    remaining = int(df[column].isna().sum())
    # A numeric column must stay numeric; pandas may legitimately narrow an object
    # column (True/False values with gaps become bool once filled).
    if remaining or (_is_numeric_column(series) and not _is_numeric_column(df[column])):
        item["verification"] = (
            f"`{column}` has {remaining} missing value(s) and dtype {df[column].dtype} "
            f"(was {dtype_before}) after the fill"
        )
    item["status"] = "executed"
    item["facts"] = {
        "missing": missing,
        "rows": len(df),
        "value": value if isinstance(value, str) else _format_value(value),
        "excluded_outliers": excluded_count if method != "constant" else 0,
    }
    return df


def _run_flag(
    df: pd.DataFrame, item: dict, df_raw: pd.DataFrame, shown: dict, excluded: dict
) -> pd.DataFrame:
    column = item["column_name"]
    flag_column = f"{column}_outlier_flag"
    if flag_column in df.columns:
        _reject(item, f"a column named `{flag_column}` already exists")
        return df
    if not _is_numeric_column(df_raw[column]):
        _reject(item, f"`{column}` is not numeric, so it has no IQR outliers")
        return df
    if not _is_numeric_column(df[column]):
        _reject(item, f"`{column}` is no longer numeric (it is now {df[column].dtype}), so its outliers are not marked")
        return df
    # The raw-upload mask the model was shown, aligned by index label (F3's rule).
    raw_mask = _iqr_outlier_mask(df_raw[column])
    if not raw_mask.any():
        _reject(item, f"`{column}` has no values outside the IQR bounds")
        return df
    mask = raw_mask.reindex(df.index, fill_value=False).astype(bool)
    present = int(mask.sum())
    if present == 0:
        _reject(item, f"none of the {int(raw_mask.sum())} rows holding `{column}`'s outliers remain in the data")
        return df
    df = _mark_rows(df, flag_column, mask)
    if int(df[flag_column].sum()) != present:
        item["verification"] = f"`{flag_column}` marks {int(df[flag_column].sum())} rows, not {present}"
    lower, upper = _iqr_bounds(df_raw[column])
    item["status"] = "executed"
    item["facts"] = {
        "outliers": int(raw_mask.sum()),
        "marked": present,
        "lower": _format_value(lower),
        "upper": _format_value(upper),
        "flag_column": flag_column,
    }
    return df


_RUNNERS = {
    "convert_type": _run_convert,
    "standardize_values": _run_standardize,
    "fill_missing": _run_fill,
    "leave_missing": _run_fill,
    "flag_outliers": _run_flag,
}


def run_model_operations(
    df: pd.DataFrame,
    items: list,
    phases: tuple,
    df_raw: pd.DataFrame,
    shown: dict,
    excluded: Optional[dict] = None,
) -> pd.DataFrame:
    """Run the planned Cleaner operations of the given phases, in phase order. Never raises.

    Each operation is checked against the frame as it is when it runs; one
    that is impossible for the column, or fails unexpectedly, leaves the frame
    unchanged and is recorded "not_executed" with the reason. `shown` is
    _distinct_value_columns of the uploaded data. `excluded` maps a column to the
    raw-upload mask of outlier values the user chose to exclude (set to missing)
    at its outlier pause: a fill's median, mean or mode is computed without them.
    """
    for phase in phases:
        for item in items:
            if item["status"] != "planned" or _PHASE_OF.get(item["operation"]) != phase:
                continue
            if item["column_name"] not in df.columns:
                _reject(item, f"`{item['column_name']}` is no longer in the data")
                continue
            try:
                df = _RUNNERS[item["operation"]](df, item, df_raw, shown, excluded or {})
            except Exception as exc:
                logger.exception("Cleaner operation %s on '%s' failed", item["operation"], item["column_name"])
                _reject(item, f"it failed unexpectedly ({type(exc).__name__}: {exc})")
    return df


def _cleaner_reason(item: dict, acted: bool) -> str:
    reason = item["decision"].get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return "The Cleaner gave no reasoning."
    prefix = "The Cleaner's reasoning: " if acted else "The Cleaner's reasoning (not acted on): "
    return prefix + reason.strip()


def _executed_record(item: dict) -> tuple[str, str]:
    """(issue, action) for an executed operation, from the facts Python computed."""
    column, facts, operation = item["column_name"], item["facts"], item["operation"]
    if operation == "convert_type":
        return (
            f"`{column}` was stored as {facts['dtype_before']} ({facts['recorded']} recorded value(s))",
            f"converted `{column}` from {facts['dtype_before']} to {facts['dtype_after']} "
            f"({item['params']['to']}); all {facts['recorded']} recorded value(s) kept",
        )
    if operation == "standardize_values":
        pairs = "; ".join(
            f"'{key}' → '{change['to']}' ({change['cells']})" for key, change in facts["replaced"].items()
        )
        return (
            f"`{column}` had {facts['distinct_before']} distinct values, including variants of the same value",
            f"replaced {facts['cells_changed']} value(s) in `{column}`: {pairs}; "
            f"{facts['distinct_before']} distinct values became {facts['distinct_after']}",
        )
    if operation in ("fill_missing", "leave_missing"):
        issue_missing = (
            f"{facts['missing']} missing values in `{column}` "
            f"({facts['missing'] / facts['rows'] * 100 if facts['rows'] else 0:.1f}% of {facts['rows']} rows)"
        )
    if operation == "fill_missing":
        method = item["params"]["method"]
        if method != "constant":
            what = f"the {method} ({facts['value']})"
        elif isinstance(item["params"]["value"], str):
            what = f"the value '{facts['value']}'"
        else:
            what = f"the value {facts['value']}"
        without = facts.get("excluded_outliers", 0)
        if without:
            what += f", computed without the {without} value(s) the user excluded as outliers"
        return issue_missing, f"filled the {facts['missing']} missing values in `{column}` with {what}"
    if operation == "leave_missing":
        later = facts.get("rows_removed_later", 0)
        return issue_missing, (
            f"left the {facts['missing']} missing values in `{column}` unchanged "
            "(nothing imputed, no rows removed)"
            + (f"; {later} of those rows were later removed by the user's row exclusion" if later else "")
        )
    return (  # flag_outliers
        f"{facts['outliers']} value(s) in `{column}` lie outside the IQR bounds "
        f"({facts['lower']} to {facts['upper']}) on the uploaded data",
        f"marked the {facts['marked']} row(s) holding these values in `{facts['flag_column']}` "
        "(1 = outside the IQR bounds); the values themselves are unchanged and stay in every statistic",
    )


def build_model_records(items: list, df_final: pd.DataFrame) -> tuple[list, dict, list]:
    """Python-written decision records for the Cleaner's decisions, in its order.

    Returns (records, outliers_flagged, discrepancies). An executed operation is
    stated from what ran, with Python's counts; a refused one says "Not
    executed" and why; a note says no data changed. The Cleaner's own wording
    appears only as its reasoning (or as a note's observation), never as the
    claim of what happened. A leave_missing is re-checked on the final frame.
    """
    records: list = []
    flagged: dict = {}
    discrepancies: list = []
    for item in items:
        column = item["column_name"]
        if item["operation"] == "leave_missing" and item["status"] == "executed" and column in df_final.columns:
            # Every row left missing that is still in the data must still be missing;
            # rows the user's exclude_rows removed afterwards are counted, not failed.
            present = item.pop("missing_rows").intersection(df_final.index)
            still_missing = int(df_final.loc[present, column].isna().sum())
            item["facts"]["rows_removed_later"] = item["facts"]["missing"] - len(present)
            if still_missing != len(present):
                item["verification"] = (
                    f"{len(present) - still_missing} of the {len(present)} values left missing in "
                    f"`{column}` were filled afterwards"
                )
        if item["status"] == "planned" and item["operation"] == "note":
            item["status"] = "noted"
        if item["operation"] == "flag_outliers" and item["status"] == "executed":
            flagged[column] = item["facts"]["marked"]
        if item.get("verification"):
            discrepancies.append(f"Decision {item['index'] + 1} ({_describe_request(item)}): {item['verification']}")
        if not item["printed"]:
            continue
        if item["status"] == "noted":
            observation = item["decision"].get("issue")
            columns = item["params"].get("columns") or []
            about = f" about {', '.join(f'`{c}`' for c in columns)}" if columns else ""
            records.append({
                "column_name": column,
                "issue": "The Cleaner's observation: " + (
                    observation.strip() if isinstance(observation, str) and observation.strip() else "(none given)"
                ),
                "action": f"No data changed: a note by the Cleaner{about}, not an operation",
                "reason": _cleaner_reason(item, acted=True),
            })
        elif item["status"] == "executed":
            issue, action = _executed_record(item)
            prefix = (
                f"Cleaner decision (verification failed: {item['verification']}): "
                if item.get("verification")
                else "Cleaner decision: "
            )
            records.append({
                "column_name": column,
                "issue": issue,
                "action": prefix + action,
                "reason": _cleaner_reason(item, acted=True),
            })
        else:
            target = f" on `{column}`" if column else ""
            records.append({
                "column_name": column,
                "issue": f"The Cleaner requested {_describe_request(item)}{target}",
                "action": f"Not executed: {item['detail']}. Nothing was changed.",
                "reason": _cleaner_reason(item, acted=False),
            })
    return records, flagged, discrepancies


def build_contract_record(items: list, decisions_field_ok: bool, total: Optional[int] = None) -> Optional[dict]:
    """One system record, placed first, when any Cleaner decision had no valid operation.

    The run still completes — raising would discard every answered pause — but
    a report whose decisions were mostly not run must say so where it is read.
    `total` is the number of decisions in the Cleaner's whole report (items holds
    only those filter_user_decided kept), matching the report-position numbering.
    """
    failures = [item for item in items if item["contract"]]
    if decisions_field_ok and not failures:
        return None
    total = len(items) if total is None else total
    if not decisions_field_ok:
        issue = "The Cleaner's report had no list of decisions"
        action = (
            "Contract check: the Cleaner's report had no valid decisions list, so none of its "
            "decisions could be run; the data was changed only by the system and the user's choices"
        )
    else:
        issue = f"{len(failures)} of the {total} decisions in the Cleaner's report did not name a valid operation"
        action = (
            f"Contract check: {len(failures)} of the Cleaner's {total} decisions had no valid operation "
            "and were not executed; the data was not changed by them"
        )
        unshown = sum(1 for item in failures if not item["printed"])
        if unshown:
            action += f". {unshown} of them named no column and {'is' if unshown == 1 else 'are'} not shown"
    reasons = Counter(item["detail"] for item in failures)
    summary = "; ".join(f"{reason} ({count})" for reason, count in reasons.most_common())
    return {
        "column_name": None,
        "issue": issue,
        "action": action,
        "reason": (
            "Recorded by the system, not written by the Cleaner. Every change the Cleaner makes must "
            "name one of its operations, which the system checks and runs; a decision without one is "
            "never guessed from its wording." + (f" Reasons: {summary}." if summary else "")
        ),
    }


def _json_safe(value: object) -> object:
    """Model-supplied params as plain JSON (anything else as its string)."""
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return str(value)


def build_operations_log(
    duplicate_entry: dict,
    items: list,
    dropped: list,
    user_record: list,
) -> tuple[list, dict]:
    """cleaning_report.operations (every operation, its status and facts) and its summary."""
    operations: list = [duplicate_entry]
    for item in items:
        operations.append({
            "source": "cleaner",
            "decision": item["index"] + 1,
            "phase": _PHASE_OF.get(item["operation"]),
            "operation": item["operation"],
            "column_name": item["column_name"],
            "params": _json_safe(item["params"]),
            "status": item["status"],
            "detail": item["detail"] or item.get("verification") or "",
            "facts": _json_safe(item["facts"]),
            "no_valid_operation": item["contract"],
        })
    for decision in dropped:
        operations.append({
            "source": "cleaner",
            "operation": _json_safe(decision.get("operation")),
            "column_name": decision.get("column_name"),
            "status": "dropped",
            "detail": "the user decided this column at a pause; the system runs the user's choice instead",
        })
    for entry in user_record:
        operations.append({
            "source": "user",
            "operation": entry["option_chosen"],
            "pause_type": entry["pause_type"],
            "column_name": entry["column_name"],
            "status": "not_executed" if entry["resolution_summary"].startswith("Not applied") else "executed",
            "detail": entry["resolution_summary"],
        })
    statuses = Counter(item["status"] for item in items)
    summary = {
        "cleaner_decisions": len(items) + len(dropped),
        "executed": statuses.get("executed", 0),
        "noted": statuses.get("noted", 0),
        "not_executed": statuses.get("not_executed", 0),
        "no_valid_operation": sum(1 for item in items if item["contract"]),
        "dropped_on_user_decided_columns": len(dropped),
    }
    return operations, summary


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
        # Computed once, off the event loop: the text columns sent in full (also
        # standardize_values' check) and the system's duplicate removal (its count is
        # sent; the frame is used after the call).
        shown = await asyncio.to_thread(_distinct_value_columns, df)
        df_deduped, duplicate_record, duplicate_entry = await asyncio.to_thread(remove_duplicate_rows, df)

        user_message = await asyncio.to_thread(
            build_cleaner_message,
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
            interactions=interactions,
            distinct_values=shown,
            duplicate_row_count=duplicate_entry["facts"]["duplicate_rows"],
        )
        system_prompt = load_system_prompt("cleaner")

        response = await asyncio.to_thread(
            lambda: client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=_CLEANER_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        )

        if response.stop_reason == "max_tokens":
            raise ValueError(
                "Cleaner LLM response truncated: reached the max_tokens ceiling "
                f"({_CLEANER_MAX_TOKENS}) before the JSON was complete."
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

        # The fixed order: the system's duplicate removal; the Cleaner's
        # conversions, value standardizations and fills; the user's
        # missing-value then outlier choices (F3's order, unchanged); the
        # Cleaner's outlier flags; then the records. Every Cleaner decision runs
        # by its named operation, checked by Python, never by its wording.
        df_cleaned = df_deduped
        decisions_field = parsed.get("decisions")
        decisions_list = decisions_field if isinstance(decisions_field, list) else []
        kept, dropped = filter_user_decided(decisions_list, resolutions)
        # Each kept decision's position in the full report (kept is an ordered
        # subsequence of the same objects), so records number them as the report does.
        numbers: list = []
        for position, decision in enumerate(decisions_list):
            if len(numbers) < len(kept) and decision is kept[len(numbers)]:
                numbers.append(position)
        plan = plan_model_decisions(kept, df, numbers)
        # The outlier values the user chose to exclude (set to missing): the Cleaner's
        # fills on the same column, which run first, are computed without them.
        excluded_outliers = {
            r["column_name"]: outlier_masks[r["column_name"]]
            for r in resolutions
            if r["pause_type"] == _OUTLIER_PAUSE
            and r["option_id"] not in _OUTLIER_KEEP_IDS
            and r["column_name"] in outlier_masks
        }
        df_cleaned = await asyncio.to_thread(
            run_model_operations, df_cleaned, plan, _MODEL_PHASES_BEFORE_USER, df, shown, excluded_outliers
        )
        (
            df_cleaned,
            user_decisions,
            user_excluded_columns,
            user_outliers_flagged,
            user_decisions_incorporated,
        ) = await asyncio.to_thread(apply_user_decisions, df_cleaned, resolutions, outlier_masks)
        df_cleaned = await asyncio.to_thread(
            run_model_operations, df_cleaned, plan, _MODEL_PHASES_AFTER_USER, df, shown
        )
        model_records, model_flagged, discrepancies = await asyncio.to_thread(
            build_model_records, plan, df_cleaned
        )
        contract_record = build_contract_record(plan, isinstance(decisions_field, list), len(decisions_list))
        # Appended last: never executed, never filtered (build_outlier_records).
        outlier_records = await asyncio.to_thread(
            build_outlier_records, df, df_cleaned, review_columns, routing, unrouted
        )
        decisions_data = (
            ([contract_record] if contract_record else [])
            + [duplicate_record]
            + model_records
            + user_decisions
            + outlier_records
        )
        # The Cleaner cannot remove a column; only the user's choices can.
        excluded_columns = user_excluded_columns
        outlier_flagged = {**model_flagged, **user_outliers_flagged}
        operations, operations_summary = build_operations_log(
            duplicate_entry, plan, dropped, user_decisions_incorporated
        )

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

        re_profile = await asyncio.to_thread(re_profile_dataframe, df_cleaned, discrepancies)

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

        # Not assessed: the text match this replaced compared a whole concern
        # object with decision text and was false on every run (errors.md
        # 2026-09-26). The real assessment is its own build.
        profiler_concerns_addressed = [
            {"concern": concern, "addressed": "not assessed"}
            for concern in (top_3_concerns or [])
        ]

        full_cleaning_report = {
            "decisions": decisions_data,
            "profiler_concerns_addressed": profiler_concerns_addressed,
            "summary": summary,
            "re_profile_verification": re_profile,
            "interactions_detected": interactions,
            "user_decisions_incorporated": user_decisions_incorporated,
            "outlier_review_summary": outlier_review_summary,
            "operations": operations,
            "operations_summary": operations_summary,
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
