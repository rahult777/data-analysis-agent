"""LangGraph orchestrator — wires the 4-agent pipeline together.

Defines the StateGraph with pause-state nodes and polling loops so the
pipeline can pause for user input and resume automatically when the user
responds via the /api/analysis/{id}/resume endpoint. Business logic lives
in the individual agent files; this file contains graph structure only.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from langgraph.graph import END, StateGraph

from backend.agents.analyzer import analyzer_node
from backend.agents.cleaner import cleaner_node
from backend.agents.explainer import explainer_node
from backend.agents.profiler import PipelineState, profiler_node
from backend.utils.langsmith_client import create_tracer
from backend.utils.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


async def build_initial_state(
    analysis_id: str,
    stored_filename: str,
    context: Optional[str],
    user_type: Optional[str],
) -> PipelineState:
    """Construct the initial PipelineState from run_pipeline_task parameters.

    context and user_type are passed directly — they are not stored in the
    analyses table and must not be read from Supabase here.
    """
    return PipelineState(
        analysis_id=analysis_id,
        stored_filename=stored_filename,
        context=context,
        user_type=user_type,
        profile_report=None,
        domain_confirmed=False,
        domain_pause_data=None,
        cleaning_report=None,
        analysis_report=None,
        insight_report=None,
        error_message=None,
        profiler_domain_hypothesis=None,
        profiler_domain_confidence_score=None,
        profiler_provenance_hypothesis=None,
        profiler_top_3_concerns=None,
        profiler_top_3_patterns=None,
        cleaner_key_decisions=None,
        cleaner_excluded_columns=None,
        cleaner_outliers_handled=None,
        cleaner_user_decisions_incorporated=None,
        missing_value_pause_data=None,
        outlier_pause_data=None,
        user_pause_response=None,
        chart_paths=None,
        data_quality_score=None,
        analyzer_most_important_finding=None,
        executive_summary=None,
        explainer_lead=None,
    )


async def check_for_pause_response(analysis_id: str) -> Optional[dict]:
    """Read user_pause_response from the analyses record.

    Returns the value if non-None, otherwise returns None.
    """
    response = await asyncio.to_thread(
        lambda: get_supabase_client()
        .table("analyses")
        .select("user_pause_response")
        .eq("id", analysis_id)
        .execute()
    )
    if not response.data:
        return None
    return response.data[0].get("user_pause_response")


async def domain_pause_wait_node(state: PipelineState) -> dict:
    """Set status to domain_pause and poll until the user responds."""
    analysis_id = state["analysis_id"]

    # Clear any leftover user_pause_response from a prior pause cycle before
    # polling — otherwise check_for_pause_response would read the stale value
    # and return immediately with the wrong response.
    await asyncio.to_thread(
        lambda: get_supabase_client()
        .table("analyses")
        .update({
            "status": "domain_pause",
            "user_pause_response": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", analysis_id)
        .execute()
    )

    while True:
        await asyncio.sleep(3)
        response = await check_for_pause_response(analysis_id)
        if response is not None:
            logger.info(
                "domain_pause_wait_node: user response received for analysis_id=%s",
                analysis_id,
            )
            break

    return {
        "user_pause_response": response,
        "domain_pause_data": None,
    }


async def clear_user_pause_response_node(state: PipelineState) -> dict:
    """Clear user_pause_response so it never reaches the cleaner's LLM context.

    Handles both the normal second-profiler-run path (profiler succeeded but
    user_pause_response is still in state) and the edge-case repeat path
    (profiler returned domain_confirmation_required again despite user response).
    """
    return {"user_pause_response": None}


async def cleaner_pause_wait_node(state: PipelineState) -> dict:
    """Disambiguate which cleaner pause is active, update status, and poll."""
    analysis_id = state["analysis_id"]

    if state.get("missing_value_pause_data") is not None:
        status = "missing_value_pause"
    elif state.get("outlier_pause_data") is not None:
        status = "outlier_pause"
    else:
        status = "missing_value_pause"
        logger.warning(
            "cleaner_pause_wait_node: neither pause field set for analysis_id=%s, "
            "defaulting status to missing_value_pause",
            analysis_id,
        )

    # Clear any leftover user_pause_response before polling — the domain pause
    # response may still be in the DB and would cause an immediate false return.
    await asyncio.to_thread(
        lambda: get_supabase_client()
        .table("analyses")
        .update({
            "status": status,
            "user_pause_response": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", analysis_id)
        .execute()
    )

    while True:
        await asyncio.sleep(3)
        response = await check_for_pause_response(analysis_id)
        if response is not None:
            logger.info(
                "cleaner_pause_wait_node: user response received for analysis_id=%s "
                "(pause_type=%s)",
                analysis_id,
                status,
            )
            break

    return {
        "user_pause_response": response,
        "missing_value_pause_data": None,
        "outlier_pause_data": None,
    }


def route_after_profiler(state: PipelineState) -> str:
    """Route from profiler based on all four possible pause-state combinations.

    (a) domain_pause_data set  + user_pause_response not set  → domain_pause_wait
    (b) domain_pause_data set  + user_pause_response set      → clear_and_proceed
    (c) domain_pause_data None + user_pause_response set      → clear_and_proceed
        CRITICAL: normal second-profiler-run path — profiler succeeded but
        user_pause_response is still in state and must be cleared before cleaner.
    (d) domain_pause_data None + user_pause_response None     → cleaner
    """
    domain_pause_data = state.get("domain_pause_data")
    user_pause_response = state.get("user_pause_response")

    if domain_pause_data is not None and user_pause_response is None:
        return "domain_pause_wait"
    if domain_pause_data is not None and user_pause_response is not None:
        return "clear_and_proceed"
    if domain_pause_data is None and user_pause_response is not None:
        return "clear_and_proceed"
    return "cleaner"


def route_after_cleaner(state: PipelineState) -> str:
    """Route from cleaner based on whether a pause is active."""
    if state.get("missing_value_pause_data") is not None:
        return "cleaner_pause_wait"
    if state.get("outlier_pause_data") is not None:
        return "cleaner_pause_wait"
    return "analyzer"


async def run_pipeline(initial_state: PipelineState) -> PipelineState:
    """Build and run the full 4-agent LangGraph pipeline.

    Creates a LangSmith tracer and passes it as a config callback so every
    node execution is traced — required by CLAUDE.md Rule 8.
    """
    analysis_id = initial_state["analysis_id"]
    tracer = create_tracer("pipeline")

    graph_builder = StateGraph(PipelineState)

    graph_builder.add_node("profiler", profiler_node)
    graph_builder.add_node("domain_pause_wait", domain_pause_wait_node)
    graph_builder.add_node("clear_and_proceed", clear_user_pause_response_node)
    graph_builder.add_node("cleaner", cleaner_node)
    graph_builder.add_node("cleaner_pause_wait", cleaner_pause_wait_node)
    graph_builder.add_node("analyzer", analyzer_node)
    graph_builder.add_node("explainer", explainer_node)

    graph_builder.set_entry_point("profiler")

    graph_builder.add_conditional_edges("profiler", route_after_profiler)
    graph_builder.add_edge("domain_pause_wait", "profiler")
    graph_builder.add_edge("clear_and_proceed", "cleaner")
    graph_builder.add_conditional_edges("cleaner", route_after_cleaner)
    graph_builder.add_edge("cleaner_pause_wait", "cleaner")
    graph_builder.add_edge("analyzer", "explainer")
    graph_builder.add_edge("explainer", END)

    graph = graph_builder.compile()

    try:
        final_state = await graph.ainvoke(
            initial_state,
            config={"callbacks": [tracer]},
        )
        return final_state
    except Exception as exc:
        logger.exception("Pipeline failed for analysis_id=%s", analysis_id)
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
