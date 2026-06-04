"""The Translator and Advisor — Agent 4 in the data analysis pipeline.

Reads the full pipeline state from all three predecessor agents, synthesises
their findings into three simultaneous output layers (Executive, Analyst,
Technical), and handles custom user questions after the initial analysis
completes by executing pandas operations on the cleaned dataset.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from anthropic import Anthropic

from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from backend.models.schemas import (
    AnalysisStatus,
    ExecutiveSummary,
    ExplainerOutput,
    FullInsightReport,
    QuestionAnswerResult,
    QuestionStatus,
)
from backend.tools.code_executor import run_question
from backend.utils.file_handler import cleanup_temp_file, download_from_storage
from backend.utils.langsmith_client import create_tracer
from backend.utils.supabase_client import get_supabase_client
from backend.agents.profiler import PipelineState, load_system_prompt, parse_json_response

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Output-token ceiling for the explainer's synthesis call. Raised from 8000 to
# match the analyzer fix (errors.md 2026-06-03): the explainer emits a large
# three-layer report (5 executive bullets + analyst narrative + technical
# methodology and code blocks) that can exceed 8000 tokens and truncate mid-JSON
# (stop_reason="max_tokens"). NOTE: 32000 is above the SDK's non-streaming ceiling
# (~21.3K, beyond which messages.create raises "Streaming is required..."), so the
# synthesis call MUST use messages.stream(). The smaller custom-question calls
# (max_tokens=2000/1000) stay non-streaming. See errors.md 2026-06-04.
EXPLAINER_MAX_TOKENS = 32000


def build_explainer_message(state: PipelineState) -> str:
    """Build the Anthropic user message for the explainer LLM call."""
    analysis_report = state.get("analysis_report") or {}

    message_data: dict[str, Any] = {
        "profile_report": state.get("profile_report"),
        "cleaning_report": state.get("cleaning_report"),
        "analysis_report": analysis_report,
        "profiler_domain_hypothesis": state.get("profiler_domain_hypothesis"),
        "profiler_provenance_hypothesis": state.get("profiler_provenance_hypothesis"),
        "profiler_top_3_concerns": state.get("profiler_top_3_concerns"),
        "profiler_top_3_patterns": state.get("profiler_top_3_patterns"),
        "chart_paths": state.get("chart_paths"),
        "data_quality_score": state.get("data_quality_score"),
        "analyzer_most_important_finding": state.get("analyzer_most_important_finding"),
        "cleaner_key_decisions": state.get("cleaner_key_decisions"),
    }

    context = state.get("context")
    if context:
        message_data["USER INTENT — what the user wants to understand"] = context

    return json.dumps(message_data, default=str)


async def explainer_node(state: PipelineState) -> dict:
    """LangGraph node — runs the full Translator and Advisor pipeline."""
    analysis_id = state["analysis_id"]

    try:
        tracer = create_tracer("explainer")  # noqa: F841

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "explaining",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )

        # Memory MCP read — 15 inheritance keys from predecessor agents.
        # Keys sourced from PipelineState; missing keys are logged as warnings.
        analysis_report = state.get("analysis_report") or {}
        memory_read = {
            "profiler.domain_hypothesis": state.get("profiler_domain_hypothesis"),
            "profiler.top_3_concerns": state.get("profiler_top_3_concerns"),
            "profiler.top_3_patterns": state.get("profiler_top_3_patterns"),
            "cleaner.key_cleaning_decisions": state.get("cleaner_key_decisions"),
            "cleaner.excluded_columns": state.get("cleaner_excluded_columns"),
            "cleaner.outliers_handled": state.get("cleaner_outliers_handled"),
            "cleaner.user_decisions_incorporated": state.get("cleaner_user_decisions_incorporated"),
            "analyzer.most_important_finding": state.get("analyzer_most_important_finding"),
            "analyzer.most_surprising_finding": analysis_report.get("most_surprising_finding"),
            "analyzer.strong_correlations": analysis_report.get("strong_correlations"),
            "analyzer.anomalies_found": analysis_report.get("anomalies_found"),
            "analyzer.chart_paths": state.get("chart_paths"),
            "analyzer.data_quality_score": state.get("data_quality_score"),
            "analyzer.open_questions": analysis_report.get("open_questions"),
            "analyzer.user_question_addressed": analysis_report.get("user_question_addressed"),
        }

        # Documented deviation from explainer_system.md §3 refusal instruction:
        # cleaner/analyzer LLM closing rituals may not write all required keys
        # reliably, so refusing here would break the pipeline.
        missing_keys = [k for k, v in memory_read.items() if not v]
        if missing_keys:
            logger.warning(
                "Memory MCP read for explainer (analysis_id=%s): "
                "missing or empty keys=%s — proceeding without them",
                analysis_id,
                missing_keys,
            )

        logger.info(
            "Memory MCP read for explainer (analysis_id=%s): retrieved %d/%d keys",
            analysis_id,
            len(memory_read) - len(missing_keys),
            len(memory_read),
        )

        message = build_explainer_message(state)
        system_prompt = load_system_prompt("explainer")

        def _run_explainer_stream():
            # Must stream: EXPLAINER_MAX_TOKENS exceeds the SDK's non-streaming
            # ceiling (see the constant's note). get_final_message() returns the
            # same Message shape messages.create() would, so the stop_reason
            # guard and JSON parsing below are unchanged.
            with client.messages.stream(
                model=ANTHROPIC_MODEL,
                max_tokens=EXPLAINER_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
            ) as stream:
                return stream.get_final_message()

        response = await asyncio.to_thread(_run_explainer_stream)

        if response.stop_reason == "max_tokens":
            raise ValueError(
                "Explainer LLM response truncated: reached the max_tokens "
                f"ceiling ({EXPLAINER_MAX_TOKENS}) before the JSON was complete. "
                "Raise EXPLAINER_MAX_TOKENS or reduce the explainer's output size."
            )

        explainer_response = parse_json_response(response.content[0].text)

        # Save raw dicts to Supabase JSONB — do NOT validate through pydantic.
        # The LLM output contract and pydantic schema field names differ; see decisions.md.
        executive_summary = explainer_response.get("executive_summary", {})
        insight_report = explainer_response.get("insight_report", {})

        # Single atomic write: executive_summary, insight_report, status, updated_at.
        # Merged to eliminate the race window between separate calls; status="complete"
        # lands atomically with the data it is signalling as ready.
        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "executive_summary": executive_summary,
                "insight_report": insight_report,
                "status": "complete",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute()
        )

        # Memory MCP write — three explainer keys persisted for downstream runs.
        explainer_lead_value: str = (
            explainer_response.get("executive_summary", {})
            .get("bullets", [{}])[0]
            .get("finding", "")
        )
        memory_writes = {
            "explainer.lead": explainer_lead_value,
            "explainer.open_questions": insight_report.get("open_questions", []),
            "explainer.questions_answered": [],
        }
        logger.info(
            "Memory MCP write for explainer (analysis_id=%s): keys=%s",
            analysis_id,
            list(memory_writes.keys()),
        )

        return {
            "executive_summary": executive_summary,
            "insight_report": insight_report,
            "explainer_lead": explainer_lead_value,
        }

    except Exception as exc:
        logger.exception("Explainer node failed for analysis_id=%s", analysis_id)
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


async def answer_question(
    analysis_id: str,
    question_id: str,
    question: str,
) -> dict:
    """Answer a custom user question by executing pandas code on the cleaned dataset.

    Called directly by main.py — not by the orchestrator. question_id is required
    to update the questions table record throughout execution.
    """
    tracer = create_tracer("explainer-question")  # noqa: F841

    # Memory MCP read — required per explainer_system.md §10 even in Custom Questions Mode.
    # Keys are not available without PipelineState in this standalone function; log gracefully.
    memory_keys = [
        "profiler.domain_hypothesis", "profiler.top_3_concerns", "profiler.top_3_patterns",
        "cleaner.key_cleaning_decisions", "cleaner.excluded_columns", "cleaner.outliers_handled",
        "cleaner.user_decisions_incorporated", "analyzer.most_important_finding",
        "analyzer.most_surprising_finding", "analyzer.strong_correlations",
        "analyzer.anomalies_found", "analyzer.chart_paths", "analyzer.data_quality_score",
        "analyzer.open_questions", "analyzer.user_question_addressed",
    ]
    logger.info(
        "Memory MCP read for explainer-question (analysis_id=%s question_id=%s): "
        "attempting %d keys — not available in standalone context, treating as missing",
        analysis_id,
        question_id,
        len(memory_keys),
    )

    try:
        file_path = await download_from_storage(analysis_id)
        df = await asyncio.to_thread(pd.read_parquet, file_path)

        try:
            await cleanup_temp_file(f"{analysis_id}.parquet")
        except Exception as cleanup_exc:
            logger.warning(
                "Failed to clean up local parquet for analysis_id=%s: %s",
                analysis_id,
                cleanup_exc,
            )

        columns_info: dict[str, str] = {col: str(df[col].dtype) for col in df.columns}
        sample = df.head(3).to_dict(orient="records")

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("questions")
            .update({"status": "answering"})
            .eq("id", question_id)
            .execute()
        )

        # First LLM call — generate pandas code for the question.
        code_system_prompt = load_system_prompt("question_code_generator")
        code_message = json.dumps(
            {
                "question": question,
                "columns_info": columns_info,
                "sample_rows": sample,
            },
            default=str,
        )

        code_api_response = await asyncio.to_thread(
            lambda: client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2000,
                system=code_system_prompt,
                messages=[{"role": "user", "content": code_message}],
            )
        )

        code_response = parse_json_response(code_api_response.content[0].text)
        pandas_code: str = code_response.get("pandas_code", "")

        if not pandas_code:
            await asyncio.to_thread(
                lambda: get_supabase_client()
                .table("questions")
                .update({
                    "status": "error",
                    "answer": "The code generator did not produce pandas code.",
                    "pandas_code": "",
                })
                .eq("id", question_id)
                .execute()
            )
            return {
                "answer": "The code generator did not produce pandas code.",
                "pandas_code": "",
            }

        result_value, error = await asyncio.to_thread(run_question, df, pandas_code)

        if error is not None:
            await asyncio.to_thread(
                lambda: get_supabase_client()
                .table("questions")
                .update({
                    "status": "error",
                    "answer": error,
                    "pandas_code": pandas_code,
                })
                .eq("id", question_id)
                .execute()
            )
            return {
                "answer": f"I could not compute the answer: {error}",
                "pandas_code": pandas_code,
            }

        # Second LLM call — translate computed result to plain-English answer.
        answer_system_prompt = load_system_prompt("question_answer")
        answer_message = json.dumps(
            {
                "question": question,
                "pandas_code": pandas_code,
                "result": str(result_value),
            },
            default=str,
        )

        answer_api_response = await asyncio.to_thread(
            lambda: client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1000,
                system=answer_system_prompt,
                messages=[{"role": "user", "content": answer_message}],
            )
        )

        answer_response = parse_json_response(answer_api_response.content[0].text)
        answer_text: str = answer_response.get("answer", "I could not formulate an answer.")

        await asyncio.to_thread(
            lambda: get_supabase_client()
            .table("questions")
            .update({
                "status": "complete",
                "answer": answer_text,
                "pandas_code": pandas_code,
            })
            .eq("id", question_id)
            .execute()
        )

        return {"answer": answer_text, "pandas_code": pandas_code}

    except Exception as exc:
        logger.exception(
            "answer_question failed for analysis_id=%s question_id=%s",
            analysis_id,
            question_id,
        )
        try:
            await asyncio.to_thread(
                lambda: get_supabase_client()
                .table("questions")
                .update({"status": "error"})
                .eq("id", question_id)
                .execute()
            )
        except Exception:
            logger.warning(
                "Failed to update questions error status for question_id=%s",
                question_id,
            )
        return {
            "answer": "An error occurred while computing the answer.",
            "pandas_code": "",
        }
