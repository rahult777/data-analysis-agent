"""Tests for backend/agents/orchestrator.py.

Integration tests requiring live LangGraph execution are skipped.
Unit tests cover routing logic and initial state construction.
"""

import asyncio
import copy
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_route_after_profiler_edge_case_repeat():
    """Edge case: user responded but profiler still returned domain_confirmation_required."""
    state = {
        "domain_pause_data": {"type": "domain_confirmation_required"},
        "user_pause_response": {"confirmed_domain": "healthcare"},
    }
    assert route_after_profiler(state) == "clear_and_proceed"


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


@pytest.mark.skip(reason="requires live LangGraph execution with real Supabase and file uploads")
def test_run_pipeline_integration():
    """Full pipeline integration test — skipped in unit test suite."""
    pass
