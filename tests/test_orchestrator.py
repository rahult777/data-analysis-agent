"""Tests for backend/agents/orchestrator.py.

Integration tests requiring live LangGraph execution are skipped.
Unit tests cover routing logic and initial state construction.
"""

import asyncio
import copy
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from backend.agents.orchestrator import (
    build_initial_state,
    cleaner_pause_wait_node,
    domain_pause_wait_node,
    route_after_cleaner,
    route_after_profiler,
    run_pipeline,
)


def test_imports():
    """Verify all orchestrator exports import without error."""
    assert callable(build_initial_state)
    assert callable(route_after_profiler)
    assert callable(route_after_cleaner)
    assert callable(run_pipeline)


def test_build_initial_state_structure():
    """build_initial_state returns a dict with correct values and domain_confirmed=False."""
    state = asyncio.run(
        build_initial_state("test-id", "test.csv", "test context", "data_analyst")
    )
    assert state["analysis_id"] == "test-id"
    assert state["stored_filename"] == "test.csv"
    assert state["context"] == "test context"
    assert state["user_type"] == "data_analyst"
    assert state["domain_confirmed"] is False
    assert state["domain_confirmed"] is not None
    assert state["domain_pause_data"] is None
    assert "answered_domain_pause" in state and state["answered_domain_pause"] is None
    assert state["user_pause_response"] is None
    assert state["missing_value_pause_data"] is None
    assert state["outlier_pause_data"] is None


def test_route_after_profiler_no_pause():
    """Happy path — no domain pause, route directly to cleaner."""
    state = {"domain_pause_data": None, "user_pause_response": None}
    assert route_after_profiler(state) == "cleaner"


def test_route_after_profiler_first_pause():
    """Profiler paused for domain confirmation — no user response yet."""
    state = {
        "domain_pause_data": {"type": "domain_confirmation_required"},
        "user_pause_response": None,
    }
    assert route_after_profiler(state) == "domain_pause_wait"


def test_route_after_profiler_normal_second_run():
    """CRITICAL: profiler succeeded on second run, user_pause_response still in state.

    This is the case that prevents domain confirmation leaking to the cleaner.
    Without this branch, the cleaner would receive the domain confirmation
    response as if it were a cleaner pause response — silent data corruption.
    """
    state = {
        "domain_pause_data": None,
        "user_pause_response": {"confirmed_domain": "healthcare"},
    }
    assert route_after_profiler(state) == "clear_and_proceed"


def test_route_after_profiler_edge_case_repeat_raises():
    """User responded but the profiler still paused: raise — never proceed without a profile."""
    state = {
        "domain_pause_data": {"type": "domain_confirmation_required"},
        "user_pause_response": {"pause_type": "domain_pause", "option_id": "confirm"},
    }
    with pytest.raises(RuntimeError, match="without a profile"):
        route_after_profiler(state)


def test_route_after_cleaner_no_pause():
    """Cleaner succeeded — route to analyzer."""
    state = {"missing_value_pause_data": None, "outlier_pause_data": None}
    assert route_after_cleaner(state) == "analyzer"


def test_route_after_cleaner_missing_value_pause():
    """Cleaner paused for missing value decision."""
    state = {
        "missing_value_pause_data": {"type": "missing_value_decision_required"},
        "outlier_pause_data": None,
    }
    assert route_after_cleaner(state) == "cleaner_pause_wait"


def test_route_after_cleaner_outlier_pause():
    """Cleaner paused for outlier decision."""
    state = {
        "missing_value_pause_data": None,
        "outlier_pause_data": {"type": "outlier_decision_required"},
    }
    assert route_after_cleaner(state) == "cleaner_pause_wait"


# ---------------------------------------------------------------------------
# Pause wait nodes — pause_data persisted in the same update as the status
# ---------------------------------------------------------------------------

DOMAIN_PAUSE_DATA = {
    "type": "domain_confirmation_required",
    "domain_hypothesis": "retail sales",
    "domain_confidence_score": 62,
    "supporting_signals": ["revenue column", "sales_rep column"],
    "options": [
        {"id": "confirm", "label": "Yes, this is retail sales. Proceed.", "action": "proceed_with_hypothesis"},
        {"id": "correct", "label": "No, the correct domain is something else.", "action": "request_user_specified_domain"},
    ],
}
MISSING_VALUE_PAUSE_DATA = {
    "type": "missing_value_decision_required",
    "column_name": "revenue",
    "missing_pct": 35.0,
    "options": [{"id": "impute"}, {"id": "exclude_column"}, {"id": "exclude_rows"}],
}
OUTLIER_PAUSE_DATA = {
    "type": "outlier_decision_required",
    "domain_context": "financial",
    "column_name": "revenue",
    "options": [{"id": "treat_as_valid"}, {"id": "flag_as_suspected_error"}],
}


def make_orchestrator_supabase_mock(execute_side_effect=None):
    """Mock get_supabase_client for the orchestrator; records each update payload.

    Payloads are deep-copied at call time so a later mutation cannot make a
    wrong write look right.
    """
    mock_client = MagicMock()
    updates: list[dict] = []
    table = mock_client.table.return_value

    def record_update(payload: dict) -> MagicMock:
        updates.append(copy.deepcopy(payload))
        return table.update.return_value

    table.update.side_effect = record_update
    if execute_side_effect is not None:
        table.update.return_value.eq.return_value.execute.side_effect = execute_side_effect
    return mock_client, updates


def run_wait_node(node, state: dict) -> tuple[dict, list[dict]]:
    """Run a pause wait node with a response already waiting and no real sleep."""
    mock_client, updates = make_orchestrator_supabase_mock()
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=mock_client),
        patch("backend.agents.orchestrator.check_for_pause_response", new=AsyncMock(return_value={"pause_type": "x"})),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
    ):
        result = asyncio.run(node(state))
    return result, updates


def test_domain_pause_wait_writes_status_and_pause_data_in_one_update():
    result, updates = run_wait_node(
        domain_pause_wait_node,
        {"analysis_id": "test-id", "domain_pause_data": DOMAIN_PAUSE_DATA},
    )
    assert len(updates) == 1
    assert updates[0]["status"] == "domain_pause"
    assert updates[0]["pause_data"] == DOMAIN_PAUSE_DATA
    assert updates[0]["user_pause_response"] is None
    assert result["domain_pause_data"] is None


def test_domain_pause_wait_carries_the_answered_question_forward():
    """/resume clears the DB copy, so the answered question must survive in state."""
    result, _ = run_wait_node(
        domain_pause_wait_node,
        {"analysis_id": "test-id", "domain_pause_data": DOMAIN_PAUSE_DATA},
    )
    assert result["answered_domain_pause"] == DOMAIN_PAUSE_DATA
    assert result["domain_pause_data"] is None
    assert result["user_pause_response"] == {"pause_type": "x"}


@pytest.mark.parametrize(
    "state_key, pause_data, status",
    [
        ("missing_value_pause_data", MISSING_VALUE_PAUSE_DATA, "missing_value_pause"),
        ("outlier_pause_data", OUTLIER_PAUSE_DATA, "outlier_pause"),
    ],
)
def test_cleaner_pause_wait_writes_status_and_pause_data_in_one_update(state_key, pause_data, status):
    state = {
        "analysis_id": "test-id",
        "missing_value_pause_data": None,
        "outlier_pause_data": None,
        state_key: pause_data,
    }
    result, updates = run_wait_node(cleaner_pause_wait_node, state)
    assert len(updates) == 1
    assert updates[0]["status"] == status
    assert updates[0]["pause_data"] == pause_data
    assert updates[0]["user_pause_response"] is None
    assert result["missing_value_pause_data"] is None
    assert result["outlier_pause_data"] is None


def test_cleaner_pause_wait_fallback_branch_writes_null_pause_data():
    """Neither payload set (unreachable via routing): status defaults, pause_data is explicitly None."""
    _, updates = run_wait_node(
        cleaner_pause_wait_node,
        {"analysis_id": "test-id", "missing_value_pause_data": None, "outlier_pause_data": None},
    )
    assert len(updates) == 1
    assert updates[0]["status"] == "missing_value_pause"
    assert "pause_data" in updates[0]
    assert updates[0]["pause_data"] is None


def test_failed_pause_write_surfaces_through_run_pipeline_system_error():
    """A failing pause_data write uses the existing run_pipeline SYSTEM_ERROR path."""
    mock_client, updates = make_orchestrator_supabase_mock(
        execute_side_effect=[RuntimeError("db write failed"), MagicMock()]
    )
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=mock_client),
        patch("backend.agents.orchestrator.create_tracer", return_value=BaseCallbackHandler()),
        patch(
            "backend.agents.orchestrator.profiler_node",
            new=AsyncMock(return_value={"domain_pause_data": DOMAIN_PAUSE_DATA}),
        ),
    ):
        initial_state = asyncio.run(build_initial_state("test-id", "test.csv", None, None))
        with pytest.raises(RuntimeError, match="db write failed"):
            asyncio.run(run_pipeline(initial_state))
    assert len(updates) == 2
    assert updates[0]["status"] == "domain_pause"
    assert updates[0]["pause_data"] == DOMAIN_PAUSE_DATA
    assert updates[1]["status"] == "error"
    assert updates[1]["error_message"] == "SYSTEM_ERROR: db write failed"


# ---------------------------------------------------------------------------
# Graph-level domain resume — real profiler_node, mocked LLM and services (Build F1)
# ---------------------------------------------------------------------------

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
CORRECT_ANSWER = {
    "pause_type": "domain_pause",
    "option_id": "correct",
    "corrected_domain": "wholesale logistics",
}


def _llm_reply(payload: dict) -> MagicMock:
    reply = MagicMock()
    reply.content = [MagicMock(text=json.dumps(payload))]
    return reply


def _resumed_report() -> dict:
    return {
        "column_profiles": [],
        "domain_hypothesis": "model drifted domain",
        "domain_supporting_signals": ["s"],
        "domain_confidence_score": 55,
        "provenance_hypothesis": "manual entry",
        "provenance_supporting_signals": ["mixed casing"],
        "top_3_concerns": [{"issue": "c", "affected_columns": [], "why_it_matters": "w"}],
        "top_3_patterns": [{"what_was_noticed": "p", "why_its_interesting": "i"}],
    }


def run_resumed_pipeline(second_llm_payload: dict) -> tuple:
    """Pause on the first Profiler call, answer 'correct', then return the second call's payload.

    Returns (raised exception or final state, Cleaner mock, Profiler LLM mock, orchestrator updates).
    """
    orchestrator_client, updates = make_orchestrator_supabase_mock()
    # LangGraph 0.2.0 rejects a node update that writes no keys.
    cleaner = AsyncMock(side_effect=lambda state: {"error_message": None})
    with (
        patch("backend.agents.profiler.client") as llm,
        patch("backend.agents.profiler.get_supabase_client"),
        patch("backend.agents.profiler.create_tracer"),
        patch(
            "backend.agents.profiler.load_dataframe",
            new=AsyncMock(return_value=pd.read_csv(FIXTURES_DIR / "ambiguous_domain.csv")),
        ),
        patch("backend.agents.orchestrator.get_supabase_client", return_value=orchestrator_client),
        patch("backend.agents.orchestrator.create_tracer", return_value=BaseCallbackHandler()),
        patch("backend.agents.orchestrator.check_for_pause_response", new=AsyncMock(return_value=CORRECT_ANSWER)),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
        patch("backend.agents.orchestrator.cleaner_node", new=cleaner),
        patch("backend.agents.orchestrator.analyzer_node", new=AsyncMock(return_value={"error_message": None})),
        patch("backend.agents.orchestrator.explainer_node", new=AsyncMock(return_value={"error_message": None})),
    ):
        llm.messages.create.side_effect = [_llm_reply(DOMAIN_PAUSE_DATA), _llm_reply(second_llm_payload)]
        initial_state = asyncio.run(build_initial_state("test-id", "ambiguous_domain.csv", None, None))
        try:
            outcome = asyncio.run(run_pipeline(initial_state))
        except Exception as exc:
            outcome = exc
    return outcome, cleaner, llm.messages.create, updates


def test_run_pipeline_domain_resume_hands_cleaner_a_settled_profile():
    """End to end through the graph: the Cleaner gets a real profile with the user's domain."""
    outcome, cleaner, create, updates = run_resumed_pipeline(_resumed_report())

    assert not isinstance(outcome, Exception), outcome
    assert create.call_count == 2
    resume_message = json.loads(create.call_args_list[1].kwargs["messages"][0]["content"])
    assert resume_message["domain_resolution"]["domain"] == "wholesale logistics"
    assert "domain_resolution" not in json.loads(create.call_args_list[0].kwargs["messages"][0]["content"])

    cleaner.assert_awaited_once()
    cleaner_state = cleaner.await_args.args[0]
    assert cleaner_state["profile_report"] is not None
    assert cleaner_state["profile_report"]["domain_hypothesis"] == "wholesale logistics"
    assert cleaner_state["profile_report"]["domain_resolution"]["source"] == "user_corrected"
    assert cleaner_state["profiler_domain_hypothesis"] == "wholesale logistics"
    assert cleaner_state["profiler_provenance_hypothesis"] == "manual entry"
    assert cleaner_state["profiler_top_3_concerns"]
    assert cleaner_state["user_pause_response"] is None
    assert updates[0]["status"] == "domain_pause"


def test_run_pipeline_domain_resume_that_repauses_errors_without_reaching_cleaner():
    outcome, cleaner, create, updates = run_resumed_pipeline(DOMAIN_PAUSE_DATA)

    assert isinstance(outcome, ValueError)
    assert create.call_count == 2
    cleaner.assert_not_awaited()
    assert [u["status"] for u in updates] == ["domain_pause", "error"]
    assert "domain_pause" not in [u["status"] for u in updates[1:]]


@pytest.mark.skip(reason="requires live LangGraph execution with real Supabase and file uploads")
def test_run_pipeline_integration():
    """Full pipeline integration test — skipped in unit test suite."""
    pass
