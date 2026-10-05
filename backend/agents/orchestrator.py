"""LangGraph orchestrator — wires the 4-agent pipeline together.

Defines the StateGraph with pause-state nodes and polling loops so the
pipeline can pause for user input and resume automatically when the user
responds via the /api/analysis/{id}/resume endpoint. Business logic lives
in the individual agent files; this file contains graph structure only.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from langgraph.graph import END, StateGraph

from backend.agents.analyzer import analyzer_node
from backend.agents.cleaner import cleaner_node
from backend.agents.explainer import explainer_node
from backend.agents.profiler import PipelineState, profiler_node
from backend.utils.langsmith_client import create_tracer
from backend.utils.supabase_client import get_supabase_client
from backend.utils.supabase_retry import TRANSIENT, supabase_call

logger = logging.getLogger(__name__)

# LangGraph stops a run after 25 supersteps by default, and every Cleaner pause
# costs two (cleaner_pause_wait -> cleaner), so a file needing about ten pauses
# would fail after the user had answered them. Loops are bounded by the Cleaner's
# repeat-pause guard (one pause per pause type and column), not by this limit.
_RECURSION_LIMIT = 1000

# A pause can wait hours for its answer, so a short outage must not end it: a
# poll that still fails after supabase_call's own retries is logged and polling
# continues. Only this long a run of consecutive failures raises (Build L.2).
_POLL_INTERVAL_SECONDS = 3
_POLL_FAILURE_BUDGET_SECONDS = 120.0
_monotonic = time.monotonic  # module-level so tests can drive the clock


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
        answered_domain_pause=None,
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
        answered_cleaner_pauses=None,
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
    response = await supabase_call(
        lambda: get_supabase_client()
        .table("analyses")
        .select("user_pause_response")
        .eq("id", analysis_id)
        .execute(),
        what="pause poll",
    )
    if not response.data:
        return None
    return response.data[0].get("user_pause_response")


def _field(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None


def _answers_this_pause(answer: object, status: str, pause_data: Optional[dict]) -> bool:
    """True when a stored user_pause_response was written for this pause.

    /resume accepts only an answer whose pause_type is the active status and,
    for a Cleaner pause, whose column_name is the pause's column; the Cleaner's
    repeat guard (Build F3) means a (pause type, column) never recurs. Any other
    stored answer is the previous pause's: cleaner_node writes only its status,
    so that answer is still in the row when the next pause is written.
    """
    if _field(answer, "pause_type") != status:
        return False
    if status == "domain_pause":
        return True
    # A Cleaner pause without a column name cannot be told apart from an earlier one
    # of its type, so no stored answer counts as its answer: re-showing the question
    # is recoverable, applying an earlier answer to it is not.
    column = _field(pause_data, "column_name")
    return isinstance(column, str) and bool(column) and _field(answer, "column_name") == column


def _shows_this_pause(stored_pause_data: object, status: str, pause_data: Optional[dict]) -> bool:
    if status == "domain_pause":
        return isinstance(stored_pause_data, dict) and stored_pause_data.get("type") == _field(pause_data, "type")
    return _field(stored_pause_data, "column_name") == _field(pause_data, "column_name")


async def _write_pause(analysis_id: str, status: str, pause_data: Optional[dict]) -> None:
    """Set the pause status and its question, clearing any earlier answer, in one update.

    Clearing the leftover user_pause_response matters: check_for_pause_response
    would otherwise read the previous pause's answer and return at once.
    pause_data rides in the same update so the status never shows a pause
    without its question.

    Re-sent blindly after a lost response, this write would erase an answer that
    arrived in between, so a transient failure is resolved by reading the row
    first (Build L.2). It landed if the row shows this pause, or already holds
    an answer to it; a stored answer to any other pause means it did not land.
    """

    def landed() -> bool:
        rows = (
            get_supabase_client()
            .table("analyses")
            .select("status, pause_data, user_pause_response")
            .eq("id", analysis_id)
            .execute()
            .data
        )
        if not rows:
            return False
        row = rows[0]
        if row.get("status") == status and _shows_this_pause(row.get("pause_data"), status, pause_data):
            return True
        return _answers_this_pause(row.get("user_pause_response"), status, pause_data)

    await supabase_call(
        lambda: get_supabase_client()
        .table("analyses")
        .update({
            "status": status,
            "pause_data": pause_data,
            "user_pause_response": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", analysis_id)
        .execute(),
        what=f"{status} write",
        landed=landed,
    )


async def _wait_for_answer(analysis_id: str, node: str) -> dict:
    """Poll every few seconds until the user's answer is stored, then return it."""
    failing_since: Optional[float] = None
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        try:
            response = await check_for_pause_response(analysis_id)
        except TRANSIENT as exc:
            now = _monotonic()
            if failing_since is None:
                failing_since = now
            if now - failing_since >= _POLL_FAILURE_BUDGET_SECONDS:
                logger.error(
                    "%s: pause poll has failed for %.0f s for analysis_id=%s; giving up",
                    node, now - failing_since, analysis_id,
                )
                raise
            logger.warning(
                "%s: pause poll failed (%s: %s) for analysis_id=%s; still polling "
                "(failing for %.0f s of %.0f s allowed)",
                node, type(exc).__name__, exc, analysis_id,
                now - failing_since, _POLL_FAILURE_BUDGET_SECONDS,
            )
            continue
        failing_since = None
        if response is not None:
            return response


async def domain_pause_wait_node(state: PipelineState) -> dict:
    """Set status to domain_pause and poll until the user responds."""
    analysis_id = state["analysis_id"]

    await _write_pause(analysis_id, "domain_pause", state.get("domain_pause_data"))

    response = await _wait_for_answer(analysis_id, "domain_pause_wait_node")
    logger.info(
        "domain_pause_wait_node: user response received for analysis_id=%s",
        analysis_id,
    )

    return {
        "user_pause_response": response,
        # /resume has already cleared the DB copy; the Profiler's resume call
        # needs the question that was answered.
        "answered_domain_pause": state.get("domain_pause_data"),
        "domain_pause_data": None,
    }


async def clear_user_pause_response_node(state: PipelineState) -> dict:
    """Clear user_pause_response so it never reaches the cleaner's LLM context.

    Handles the normal second-profiler-run path: the profiler succeeded but
    user_pause_response is still in state. (A repeat domain pause after the
    user answered no longer routes here — see route_after_profiler case (b).)
    """
    return {"user_pause_response": None}


async def cleaner_pause_wait_node(state: PipelineState) -> dict:
    """Disambiguate which cleaner pause is active, update status, and poll."""
    analysis_id = state["analysis_id"]

    if state.get("missing_value_pause_data") is not None:
        status = "missing_value_pause"
        pause_data = state["missing_value_pause_data"]
    elif state.get("outlier_pause_data") is not None:
        status = "outlier_pause"
        pause_data = state["outlier_pause_data"]
    else:
        status = "missing_value_pause"
        pause_data = None
        logger.warning(
            "cleaner_pause_wait_node: neither pause field set for analysis_id=%s, "
            "defaulting status to missing_value_pause",
            analysis_id,
        )

    # The domain pause's answer, or an earlier Cleaner pause's, may still be in
    # the DB; _write_pause clears it so the poll cannot return it at once.
    await _write_pause(analysis_id, status, pause_data)

    response = await _wait_for_answer(analysis_id, "cleaner_pause_wait_node")
    logger.info(
        "cleaner_pause_wait_node: user response received for analysis_id=%s "
        "(pause_type=%s)",
        analysis_id,
        status,
    )

    # /resume clears the DB copy of the question, and the Cleaner's next run
    # must honor every earlier answer, not only this one — so each answered
    # question is kept, in order. Returns the whole list: the state key has no
    # reducer, so a returned value replaces the previous one.
    answered = list(state.get("answered_cleaner_pauses") or [])
    answered.append({
        "pause_type": status,
        "column_name": pause_data.get("column_name") if isinstance(pause_data, dict) else None,
        "question": pause_data,
        "response": response,
    })

    return {
        "user_pause_response": response,
        "answered_cleaner_pauses": answered,
        "missing_value_pause_data": None,
        "outlier_pause_data": None,
    }


def route_after_profiler(state: PipelineState) -> str:
    """Route from profiler based on all four possible pause-state combinations.

    (a) domain_pause_data set  + user_pause_response not set  → domain_pause_wait
    (b) domain_pause_data set  + user_pause_response set      → raise
        profiler_node already raises when its resume call re-pauses; this is
        defense in depth, since proceeding without a profile is always wrong.
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
        raise RuntimeError(
            "Profiler requested domain confirmation again after the user answered; "
            "refusing to continue without a profile."
        )
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
    node execution is traced — required by CLAUDE.md Rule 8. With tracing off
    create_tracer returns None and no callback is passed; the agent-work routes
    refuse before a pipeline can start (backend/utils/agent_guard.py).
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

    run_config: dict = {"recursion_limit": _RECURSION_LIMIT}
    if tracer is not None:
        run_config["callbacks"] = [tracer]

    try:
        final_state = await graph.ainvoke(initial_state, config=run_config)
        return final_state
    except Exception as exc:
        logger.exception("Pipeline failed for analysis_id=%s", analysis_id)
        await supabase_call(
            lambda: get_supabase_client()
            .table("analyses")
            .update({
                "status": "error",
                "error_message": f"SYSTEM_ERROR: {str(exc)}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", analysis_id)
            .execute(),
            what="pipeline error write",
        )
        raise
