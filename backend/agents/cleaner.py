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


async def load_dataframe_from_uploads(stored_filename: str) -> pd.DataFrame:
    file_path = Path("backend") / "uploads" / stored_filename
    if not await asyncio.to_thread(file_path.exists):
        raise FileNotFoundError(
            f"Uploaded file not found at expected path: {file_path.resolve()}"
        )
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return await asyncio.to_thread(pd.read_csv, file_path)
    elif suffix in (".xls", ".xlsx"):
        return await asyncio.to_thread(pd.read_excel, file_path)
    else:
        raise ValueError(
            f"Unsupported file extension '{suffix}' for '{file_path.name}'. "
            "Only .csv, .xls, and .xlsx files are supported."
        )


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
    user_pause_response: Optional[dict],
    missingness_patterns: dict,
) -> str:
    columns = df.columns[:50].tolist()
    df_subset = df[columns]

    col_info: dict = {}
    for col in columns:
        series = df_subset[col]
        non_null_vals = series.dropna()
        sample = [str(v) for v in non_null_vals.head(3).tolist()]
        col_info[col] = {
            "dtype": str(series.dtype),
            "missing_pct": round(float(series.isna().mean() * 100), 2),
            "missing_count": int(series.isna().sum()),
            "sample_values": sample,
        }

    for col in columns:
        if pd.api.types.is_numeric_dtype(df_subset[col]):
            series = df_subset[col].dropna()
            if len(series) > 4:
                q1 = float(series.quantile(0.25))
                q3 = float(series.quantile(0.75))
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                col_info[col]["outlier_count"] = int(
                    ((series < lower) | (series > upper)).sum()
                )
                col_info[col]["outlier_bounds"] = {"lower": lower, "upper": upper}

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

    if user_pause_response:
        message_data["user_pause_response"] = user_pause_response

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
    numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
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

        # 1. DUPLICATE REMOVAL — column_name is null for dataset-level decisions
        if col is None:
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
        if "median" in combined:
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].median())
            continue

        # 3. MEAN FILL (not median)
        if "mean" in combined and "median" not in combined:
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].fillna(df[col].mean())
            continue

        # 4. MODE FILL
        if "mode" in combined:
            mode_vals = df[col].mode()
            if len(mode_vals) > 0:
                df[col] = df[col].fillna(mode_vals.iloc[0])
            continue

        # 5. SPECIFIC VALUE FILL
        if any(
            kw in combined
            for kw in ("fill with", "impute with", "replace with", "set to", "replace missing")
        ):
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
        if any(
            kw in combined
            for kw in (
                "drop column", "exclude column", "remove column",
                "exclude from analysis", "drop from dataset",
            )
        ):
            df = df.drop(columns=[col])
            excluded_columns.append(col)
            continue

        # 7. DROP ROWS
        if any(
            kw in combined
            for kw in (
                "drop rows", "remove rows", "drop records",
                "remove records", "exclude rows",
            )
        ):
            df = df.dropna(subset=[col])
            continue

        # 8. DTYPE CONVERT
        if any(kw in combined for kw in ("convert", "cast", "change type", "dtype", "type to")):
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
        if "outlier" in combined or "flag" in combined:
            if not any(kw in combined for kw in ("remove", "delete", "drop")):
                if pd.api.types.is_numeric_dtype(df[col]):
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
        user_pause_response = state.get("user_pause_response")

        user_message = build_cleaner_message(
            df=df,
            profile_report=profile_report,
            domain_hypothesis=domain_hypothesis,
            provenance_hypothesis=provenance_hypothesis,
            top_3_concerns=top_3_concerns,
            user_pause_response=user_pause_response,
            missingness_patterns=missingness_patterns,
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

        if parsed.get("type") == "missing_value_decision_required":
            return {
                "missing_value_pause_data": parsed,
                "user_pause_response": None,
            }

        if parsed.get("type") == "outlier_decision_required":
            return {
                "outlier_pause_data": parsed,
                "user_pause_response": None,
            }

        decisions_data = parsed.get("decisions", [])

        df_cleaned, excluded_columns, outlier_flagged = await asyncio.to_thread(
            execute_cleaning_operations, df, decisions_data
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
