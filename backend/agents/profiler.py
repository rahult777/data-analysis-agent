"""The Comprehender — Agent 1 in the data analysis pipeline.

Reads every uploaded dataset before any other agent touches it, forms a
domain hypothesis, profiles every column, assesses data capability, and
flags the top concerns and patterns for downstream agents.
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

import pandas as pd
from anthropic import Anthropic

from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from backend.models.schemas import AnalysisStatus, ColumnProfile, ProfileReport
from backend.utils.langsmith_client import create_tracer
from backend.utils.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)


class PipelineState(TypedDict):
    analysis_id: str
    stored_filename: str
    context: Optional[str]
    user_type: Optional[str]
    profile_report: Optional[dict]
    domain_confirmed: bool
    domain_pause_data: Optional[dict]
    cleaning_report: Optional[dict]
    analysis_report: Optional[dict]
    insight_report: Optional[dict]
    error_message: Optional[str]
    profiler_domain_hypothesis: Optional[str]
    profiler_domain_confidence_score: Optional[int]
    profiler_provenance_hypothesis: Optional[str]
    profiler_top_3_concerns: Optional[list]
    profiler_top_3_patterns: Optional[list]
    cleaner_key_decisions: Optional[list]
    cleaner_excluded_columns: Optional[list]
    cleaner_outliers_handled: Optional[dict]
    cleaner_user_decisions_incorporated: Optional[list]
    missing_value_pause_data: Optional[dict]
    outlier_pause_data: Optional[dict]
    user_pause_response: Optional[dict]
    chart_paths: Optional[list]
    data_quality_score: Optional[float]
    analyzer_most_important_finding: Optional[str]
    executive_summary: Optional[dict]
    explainer_lead: Optional[str]


def load_system_prompt(agent_name: str) -> str:
    prompt_path = Path("backend") / "prompts" / f"{agent_name}_system.md"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"System prompt not found at expected path: {prompt_path.resolve()}"
        )
    return prompt_path.read_text(encoding="utf-8")


async def load_dataframe(stored_filename: str) -> pd.DataFrame:
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


# Same contract as analyzer._safe_stat; not imported because analyzer imports this module.
def _safe_stat(func: Callable[[], Any]) -> Optional[float]:
    try:
        value = float(func())
    except Exception:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def compute_column_stats(df: pd.DataFrame, columns: list[str]) -> dict[str, dict]:
    """Full-column deterministic stats per column, keyed by column name.
    Numeric: unique_count, mean, std, min_value, max_value, outlier_count,
    outlier_pct (IQR method). Non-numeric (including datetime — out of
    scope for numeric stats per the 2026-09-17 decision): unique_count
    only, all other fields None — mirrors ColumnProfile's
    null-for-non-numeric convention."""
    stats: dict[str, dict] = {}
    for col in columns:
        series = df[col]
        non_null = series.dropna()
        col_stats: dict = {
            "unique_count": int(non_null.nunique()),
            "mean": None,
            "std": None,
            "min_value": None,
            "max_value": None,
            "outlier_count": None,
            "outlier_pct": None,
        }
        # is_numeric_dtype is True for bool, but bool has no quantile and is categorical here.
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            col_stats["mean"] = _safe_stat(non_null.mean)
            col_stats["std"] = _safe_stat(non_null.std)
            col_stats["min_value"] = _safe_stat(non_null.min)
            col_stats["max_value"] = _safe_stat(non_null.max)
            # Same >4-value floor as cleaner.py's IQR block, so both agents agree on when
            # outlier stats exist.
            if len(non_null) > 4:
                q1 = non_null.quantile(0.25)
                q3 = non_null.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                outlier_count = int(((non_null < lower) | (non_null > upper)).sum())
                col_stats["outlier_count"] = outlier_count
                col_stats["outlier_pct"] = round(outlier_count / len(non_null) * 100, 2)
        stats[col] = col_stats
    return stats


def build_profiler_message(df: pd.DataFrame, context: Optional[str]) -> str:
    # shared pandas operations will be extracted to data_tools.py in a later task
    total_cols = len(df.columns)
    columns = df.columns[:50].tolist()
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
            "missing_count": int(series.isna().sum()),
            "sample_values": sample,
        }

    # pandas to_json handles NaN→null and numpy type serialization
    rows = json.loads(df_subset.head(5).to_json(orient="records"))

    message_data: dict = {
        "row_count": len(df),
        "column_count": total_cols,
        "columns_included": len(columns),
        "first_5_rows": rows,
        "column_info": col_info,
        "computed_column_stats": compute_column_stats(df_subset, columns),
    }
    if total_cols > 50:
        message_data["columns_note"] = (
            f"Dataset has {total_cols} columns total. "
            "First 50 included to prevent token bloat."
        )
    if context:
        message_data["user_context"] = context

    return json.dumps(message_data, default=str)


def apply_computed_column_stats(
    profile_report: dict,
    computed_column_stats: dict[str, dict],
    column_info: dict[str, dict],
) -> None:
    column_profiles = profile_report.get("column_profiles")
    if not isinstance(column_profiles, list):
        logger.warning("ProfileReport has no column_profiles list; computed stats not applied")
        return
    stats_by_name = {str(name): stats for name, stats in computed_column_stats.items()}
    info_by_name = {str(name): info for name, info in column_info.items()}
    applied: set[str] = set()
    for profile in column_profiles:
        if not isinstance(profile, dict):
            continue
        name = str(profile.get("column_name"))
        if name not in stats_by_name:
            logger.warning("column_profiles entry %r matches no profiled column; left as emitted", name)
            continue
        profile.update(stats_by_name[name])
        info = info_by_name[name]
        profile["dtype"] = info["dtype"]
        profile["missing_count"] = info["missing_count"]
        profile["sample_values"] = info["sample_values"]
        applied.add(name)
    missing = sorted(set(stats_by_name) - applied)
    if missing:
        logger.warning("ProfileReport has no column_profiles entry for: %s", missing)


def parse_json_response(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse model response as JSON: {exc}. "
            f"Response preview (first 500 chars): {text[:500]}"
        ) from exc


async def profiler_node(state: PipelineState) -> PipelineState:
    analysis_id = state["analysis_id"]

    try:
        # LangGraph traces this node automatically when the tracer is passed as a
        # callback to graph.invoke() in the orchestrator — not to the Anthropic SDK.
        tracer = create_tracer("profiler")

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "profiling",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )

        df = await load_dataframe(state["stored_filename"])
        system_prompt = load_system_prompt("profiler")
        user_message = build_profiler_message(df, state.get("context"))

        response = await asyncio.to_thread(
            lambda: client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=8000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        )

        parsed = parse_json_response(response.content[0].text)

        if parsed.get("type") == "domain_confirmation_required":
            state["domain_pause_data"] = parsed
            state["domain_confirmed"] = False
            await asyncio.to_thread(
                lambda: get_supabase_client()
                .table("analyses")
                .update({"updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", analysis_id)
                .execute()
            )
            return state

        message_inputs = json.loads(user_message)
        apply_computed_column_stats(parsed, message_inputs["computed_column_stats"], message_inputs["column_info"])

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "profile_report": parsed,
                "row_count": len(df),
                "column_count": len(df.columns),
            })
            .eq("id", analysis_id)
            .execute()
        )

        state["profile_report"] = parsed
        state["domain_confirmed"] = True

        state["profiler_domain_hypothesis"] = parsed.get("domain_hypothesis")
        state["profiler_domain_confidence_score"] = parsed.get("domain_confidence_score")
        state["profiler_provenance_hypothesis"] = parsed.get("provenance_hypothesis")
        state["profiler_top_3_concerns"] = parsed.get("top_3_concerns")
        state["profiler_top_3_patterns"] = parsed.get("top_3_patterns")

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({"updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", analysis_id)
            .execute()
        )

        return state

    except Exception as exc:
        logger.exception("Profiler node failed for analysis_id=%s", analysis_id)
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
