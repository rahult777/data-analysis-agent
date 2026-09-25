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
    answered_domain_pause: Optional[dict]
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
    answered_cleaner_pauses: Optional[list]
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


def build_domain_resolution(pause_data: Optional[dict], response: Optional[dict]) -> Optional[dict]:
    """The settled domain from a domain-pause answer; None when this is not a resume."""
    if not isinstance(response, dict) or response.get("pause_type") != "domain_pause":
        return None
    question = pause_data if isinstance(pause_data, dict) else {}
    original = question.get("domain_hypothesis")
    option_id = response.get("option_id")
    if option_id == "confirm":
        if not isinstance(original, str) or not original.strip():
            raise ValueError("Domain confirmed, but the paused question recorded no domain_hypothesis.")
        source, domain = "user_confirmed", original.strip()
    elif option_id == "correct":
        corrected = response.get("corrected_domain")
        if not isinstance(corrected, str) or not corrected.strip():
            raise ValueError("Domain correction received with an empty corrected_domain.")
        source, domain = "user_corrected", corrected.strip()
    else:
        raise ValueError(f"Unrecognized domain-pause option_id: {option_id!r}")
    return {
        "source": source,
        "domain": domain,
        "original_hypothesis": original,
        "original_confidence_score": question.get("domain_confidence_score"),
        "original_supporting_signals": question.get("supporting_signals"),
    }


def build_profiler_message(
    df: pd.DataFrame,
    context: Optional[str],
    domain_resolution: Optional[dict] = None,
) -> str:
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
    if domain_resolution is not None:
        message_data["domain_resolution"] = domain_resolution

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


def apply_domain_resolution(profile_report: dict, domain_resolution: dict) -> None:
    """Make the user's settled domain authoritative in the ProfileReport.

    The score is never raised because the user answered: on confirm the pause
    score is kept (same hypothesis, same evidence); on correct the model's
    evidential score for the user's domain stands.
    """
    profile_report["domain_hypothesis"] = domain_resolution["domain"]
    score = domain_resolution.get("original_confidence_score")
    if (
        domain_resolution["source"] == "user_confirmed"
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
    ):
        profile_report["domain_confidence_score"] = score
    profile_report["domain_resolution"] = domain_resolution


DOMAIN_CONFIDENCE_THRESHOLD = 80  # profiler_system.md Step 2 / Section 8


def apply_confidence_gate(parsed: dict) -> dict:
    """Backstop for the <80 domain-confidence gate on a first (non-resume) call.

    The prompt tells the model to self-gate; this converts a full ProfileReport
    that arrives below the threshold anyway into the standard domain pause.
    Never call it on a resume: a settled domain keeps its honest score and is
    never re-gated.
    """
    if parsed.get("type") == "domain_confirmation_required":
        return parsed
    score = parsed.get("domain_confidence_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        raise ValueError(f"ProfileReport has no usable domain_confidence_score: {score!r}")
    if score >= DOMAIN_CONFIDENCE_THRESHOLD:
        return parsed
    hypothesis = parsed.get("domain_hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("ProfileReport scored below the confidence gate with no domain_hypothesis to confirm.")
    signals = parsed.get("domain_supporting_signals")
    logger.warning(
        "Profiler returned a full ProfileReport at domain_confidence_score %s (< %d); converted to a domain pause.",
        score, DOMAIN_CONFIDENCE_THRESHOLD,
    )
    return {
        "type": "domain_confirmation_required",
        "domain_hypothesis": hypothesis,
        "domain_confidence_score": score,
        "supporting_signals": signals if isinstance(signals, list) else [],
        "options": [
            {"id": "confirm", "label": f"Yes, this is {hypothesis}. Proceed.", "action": "proceed_with_hypothesis"},
            {"id": "correct", "label": "No, the correct domain is something else.", "action": "request_user_specified_domain"},
        ],
    }


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
        domain_resolution = build_domain_resolution(
            state.get("answered_domain_pause"), state.get("user_pause_response")
        )
        user_message = build_profiler_message(df, state.get("context"), domain_resolution)

        response = await asyncio.to_thread(
            lambda: client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=8000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        )

        parsed = parse_json_response(response.content[0].text)
        if domain_resolution is None:
            parsed = apply_confidence_gate(parsed)

        if parsed.get("type") == "domain_confirmation_required":
            if domain_resolution is not None:
                raise ValueError(
                    "Profiler asked for domain confirmation again after the user answered."
                )
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
        if domain_resolution is not None:
            apply_domain_resolution(parsed, domain_resolution)

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
