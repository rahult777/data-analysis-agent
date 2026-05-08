"""Tests for backend/agents/orchestrator.py.

Integration tests requiring live LangGraph execution are skipped.
Unit tests cover routing logic and initial state construction.
"""

import asyncio
import pytest

from backend.agents.orchestrator import (
    build_initial_state,
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


@pytest.mark.skip(reason="requires live LangGraph execution with real Supabase and file uploads")
def test_run_pipeline_integration():
    """Full pipeline integration test — skipped in unit test suite."""
    pass
