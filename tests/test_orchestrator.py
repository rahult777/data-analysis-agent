"""Tests for backend/agents/orchestrator.py.

Integration tests requiring live LangGraph execution are skipped.
Unit tests cover routing logic and initial state construction.
"""

import asyncio
import copy
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
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


def run_pipeline_capturing_config(tracer: BaseCallbackHandler | None) -> dict:
    """Run run_pipeline with a stub graph and return the config it passes to ainvoke."""
    graph_class = MagicMock()
    ainvoke = AsyncMock(return_value={"analysis_id": "test-id"})
    graph_class.return_value.compile.return_value.ainvoke = ainvoke
    with (
        patch("backend.agents.orchestrator.StateGraph", graph_class),
        patch("backend.agents.orchestrator.create_tracer", return_value=tracer),
    ):
        asyncio.run(run_pipeline({"analysis_id": "test-id"}))
    return ainvoke.call_args.kwargs["config"]


def test_run_pipeline_passes_no_callbacks_when_tracing_is_off() -> None:
    """create_tracer returns None with tracing off; the graph must get no callbacks, not [None]."""
    run_config = run_pipeline_capturing_config(None)
    assert "callbacks" not in run_config
    assert run_config["recursion_limit"] == 1000


def test_run_pipeline_passes_the_tracer_as_its_callback_when_tracing_is_on() -> None:
    tracer = BaseCallbackHandler()
    run_config = run_pipeline_capturing_config(tracer)
    assert run_config["callbacks"] == [tracer]
    assert run_config["recursion_limit"] == 1000


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


def run_resumed_pipeline(
    second_llm_payload: dict,
    first_llm_payload: dict = DOMAIN_PAUSE_DATA,
    answer: dict = CORRECT_ANSWER,
) -> tuple:
    """Pause on the first Profiler call, answer it (default 'correct'), then return the second call's payload.

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
        patch("backend.agents.orchestrator.check_for_pause_response", new=AsyncMock(return_value=answer)),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
        patch("backend.agents.orchestrator.cleaner_node", new=cleaner),
        patch("backend.agents.orchestrator.analyzer_node", new=AsyncMock(return_value={"error_message": None})),
        patch("backend.agents.orchestrator.explainer_node", new=AsyncMock(return_value={"error_message": None})),
    ):
        llm.messages.create.side_effect = [_llm_reply(first_llm_payload), _llm_reply(second_llm_payload)]
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


def test_run_pipeline_sub_80_full_report_is_gated_into_a_pause_then_confirmed_unknown():
    """Build F2: a full ProfileReport at 35 with no pause signal still routes to domain_pause_wait,
    stores the synthesized question, and a confirmed 'unknown' reaches the Cleaner without re-gating."""
    first = {**_resumed_report(), "domain_hypothesis": "unknown", "domain_confidence_score": 35}
    outcome, cleaner, create, updates = run_resumed_pipeline(
        {**_resumed_report(), "domain_hypothesis": "unknown", "domain_confidence_score": 30},
        first_llm_payload=first,
        answer={"pause_type": "domain_pause", "option_id": "confirm"},
    )

    assert not isinstance(outcome, Exception), outcome
    assert create.call_count == 2
    pause_writes = [u for u in updates if u.get("status") == "domain_pause"]
    assert len(pause_writes) == 1
    stored = pause_writes[0]["pause_data"]
    assert stored["type"] == "domain_confirmation_required"
    assert stored["domain_hypothesis"] == "unknown"
    assert stored["domain_confidence_score"] == 35
    assert [option["id"] for option in stored["options"]] == ["confirm", "correct"]

    cleaner.assert_awaited_once()
    profile = cleaner.await_args.args[0]["profile_report"]
    assert profile["domain_hypothesis"] == "unknown"
    assert profile["domain_confidence_score"] == 35
    assert profile["domain_resolution"]["source"] == "user_confirmed"


# ---------------------------------------------------------------------------
# Graph-level Cleaner pauses — real cleaner_node and cleaner_pause_wait_node,
# mocked LLM and services (Build F3)
# ---------------------------------------------------------------------------

from tests.test_cleaner import (  # noqa: E402
    ADVERSARIAL_OUTLIERS,
    ADVERSARIAL_REVENUE,
    OUTLIER_ROWS,
    _mv_question,
    _outlier_question,
    _report,
)

MESSY = FIXTURES_DIR / "messy_data.csv"
PROFILE_STATE = {
    "profile_report": {"domain_hypothesis": "retail"},
    "profiler_domain_hypothesis": "retail",
    "profiler_provenance_hypothesis": "system export",
    "profiler_top_3_concerns": [],
}


def _answer(pause_type: str, option_id: str, column: str) -> dict:
    return {"pause_type": pause_type, "option_id": option_id, "column_name": column}


def run_cleaner_pauses(llm_payloads: list, answers: list, frame: pd.DataFrame | None = None) -> tuple:
    """Run the graph from a finished profile through the Cleaner's pauses.

    Returns (raised exception or final state, the Analyzer mock, the Cleaner LLM
    mock, orchestrator updates, the frame the Cleaner wrote to parquet or None).
    """
    orchestrator_client, updates = make_orchestrator_supabase_mock()
    saved: dict = {}
    analyzer = AsyncMock(side_effect=lambda state: {"error_message": None})

    def capture_parquet(frame: pd.DataFrame, *args, **kwargs) -> None:
        saved["df"] = frame.copy()

    with (
        patch("backend.agents.orchestrator.profiler_node", new=AsyncMock(return_value=PROFILE_STATE)),
        patch("backend.agents.cleaner.client") as llm,
        patch("backend.agents.cleaner.get_supabase_client"),
        patch("backend.agents.cleaner.create_tracer"),
        patch(
            "backend.agents.cleaner.load_dataframe_from_uploads",
            new=AsyncMock(side_effect=lambda name: pd.read_csv(MESSY) if frame is None else frame.copy()),
        ),
        patch("backend.agents.cleaner.upload_to_storage"),
        patch("backend.agents.cleaner.cleanup_temp_file"),
        patch.object(pd.DataFrame, "to_parquet", autospec=True, side_effect=capture_parquet),
        patch("backend.agents.orchestrator.get_supabase_client", return_value=orchestrator_client),
        patch("backend.agents.orchestrator.create_tracer", return_value=BaseCallbackHandler()),
        patch("backend.agents.orchestrator.check_for_pause_response", new=AsyncMock(side_effect=answers)),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
        patch("backend.agents.orchestrator.analyzer_node", new=analyzer),
        patch("backend.agents.orchestrator.explainer_node", new=AsyncMock(return_value={"error_message": None})),
    ):
        llm.messages.create.side_effect = [_llm_reply(payload) for payload in llm_payloads]
        initial_state = asyncio.run(build_initial_state("test-id", "messy_data.csv", None, None))
        try:
            outcome = asyncio.run(run_pipeline(initial_state))
        except Exception as exc:
            outcome = exc
    return outcome, analyzer, llm.messages.create, updates, saved.get("df")


def _sent(create, call: int) -> dict:
    return json.loads(create.call_args_list[call].kwargs["messages"][0]["content"])


def test_cleaner_pause_wait_accumulates_every_answered_question():
    earlier = {"pause_type": "missing_value_pause", "column_name": "revenue", "question": {"q": 1}, "response": {"r": 1}}
    result, _ = run_wait_node(
        cleaner_pause_wait_node,
        {
            "analysis_id": "test-id",
            "missing_value_pause_data": None,
            "outlier_pause_data": OUTLIER_PAUSE_DATA,
            "answered_cleaner_pauses": [earlier],
        },
    )
    assert result["answered_cleaner_pauses"] == [
        earlier,
        {"pause_type": "outlier_pause", "column_name": "revenue", "question": OUTLIER_PAUSE_DATA, "response": {"pause_type": "x"}},
    ]


def test_run_pipeline_three_cleaner_pauses_accumulate_and_every_choice_is_executed():
    """revenue missing → notes missing → revenue outliers → report. Each answer reaches
    every later call, revenue is never re-asked, and the saved frame reflects all three
    choices exactly, whatever the model wrote about them."""
    outcome, analyzer, create, updates, saved = run_cleaner_pauses(
        [
            _mv_question("revenue", "median"),
            _mv_question("notes", "mode"),
            _outlier_question("revenue"),
            _report([*ADVERSARIAL_REVENUE, *ADVERSARIAL_OUTLIERS]),
        ],
        [
            _answer("missing_value_pause", "impute", "revenue"),
            _answer("missing_value_pause", "preserve_missingness", "notes"),
            _answer("outlier_pause", "flag_as_suspected_error", "revenue"),
        ],
    )

    assert not isinstance(outcome, Exception), outcome
    assert create.call_count == 4
    assert "resolved_pauses" not in _sent(create, 0)
    resolved = [(r["pause_type"], r["column_name"], r["option_id"]) for r in _sent(create, 3)["resolved_pauses"]]
    assert resolved == [
        ("missing_value_pause", "revenue", "impute"),
        ("missing_value_pause", "notes", "preserve_missingness"),
        ("outlier_pause", "revenue", "flag_as_suspected_error"),
    ]
    assert len(_sent(create, 1)["resolved_pauses"]) == 1

    pauses = [u for u in updates if u.get("status") in ("missing_value_pause", "outlier_pause")]
    assert [(u["status"], u["pause_data"]["column_name"]) for u in pauses] == [
        ("missing_value_pause", "revenue"),
        ("missing_value_pause", "notes"),
        ("outlier_pause", "revenue"),
    ]
    assert pauses[0]["pause_data"]["options"][-1]["id"] == "preserve_missingness"
    assert pauses[2]["pause_data"]["outlier_count"] == 4

    deduped = pd.read_csv(MESSY).drop_duplicates()
    assert len(saved) == 185
    assert saved.index[saved["revenue"].isna()].tolist() == OUTLIER_ROWS
    assert saved.index[saved["revenue_outlier_flag"] == 1].tolist() == OUTLIER_ROWS
    assert saved["notes"].isna().sum() == deduped["notes"].isna().sum() == 84

    analyzer.assert_awaited_once()
    analyzer_state = analyzer.await_args.args[0]
    assert len(analyzer_state["answered_cleaner_pauses"]) == 3
    assert [r["option_chosen"] for r in analyzer_state["cleaner_user_decisions_incorporated"]] == [
        "impute", "preserve_missingness", "flag_as_suspected_error",
    ]


def test_run_pipeline_cleaner_repeat_pause_errors_instead_of_looping():
    """The logged loop: after both answers the model asks about revenue again."""
    outcome, analyzer, create, updates, saved = run_cleaner_pauses(
        [_mv_question("revenue"), _mv_question("notes", "mode"), _mv_question("revenue")],
        [
            _answer("missing_value_pause", "impute", "revenue"),
            _answer("missing_value_pause", "preserve_missingness", "notes"),
        ],
    )

    assert isinstance(outcome, ValueError)
    assert "asked again" in str(outcome)
    assert create.call_count == 3
    analyzer.assert_not_awaited()
    assert saved is None
    assert [u["status"] for u in updates] == ["missing_value_pause", "missing_value_pause", "error"]


def test_run_pipeline_survives_more_cleaner_pauses_than_langgraphs_default_step_limit():
    """12 columns over 30% missing, each asked about once via the backstop: 24 pause
    supersteps on top of the pipeline's own, past LangGraph's default limit of 25."""
    columns = {f"c{i}": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, np.nan, np.nan, np.nan, np.nan] for i in range(12)}
    # A distinct row id: since Build G the system always removes exact duplicate
    # rows, and rows 6-9 would otherwise be four identical all-missing rows.
    frame = pd.DataFrame({"row": list(range(10)), **columns})
    outcome, analyzer, create, updates, saved = run_cleaner_pauses(
        [_report([])] * 13,
        [_answer("missing_value_pause", "preserve_missingness", f"c{i}") for i in range(12)],
        frame=frame,
    )
    assert not isinstance(outcome, Exception), outcome
    assert create.call_count == 13
    assert [u["pause_data"]["column_name"] for u in updates if u.get("status") == "missing_value_pause"] == [
        f"c{i}" for i in range(12)
    ]
    analyzer.assert_awaited_once()
    assert saved.isna().sum().sum() == 12 * 4


# ---------------------------------------------------------------------------
# Transient Supabase failures in the pause-wait nodes (Build L.2)
# ---------------------------------------------------------------------------

import httpx  # noqa: E402

from backend.agents import orchestrator  # noqa: E402
from backend.agents.orchestrator import _write_pause, check_for_pause_response  # noqa: E402
from tests.fake_supabase import Fault, FakeSupabase  # noqa: E402

UNITS_PAUSE = {**MISSING_VALUE_PAUSE_DATA, "column_name": "units_sold"}
PREVIOUS_ANSWER = {"pause_type": "outlier_pause", "column_name": "revenue", "option_id": "treat_as_valid"}
UNITS_ANSWER = {"pause_type": "missing_value_pause", "column_name": "units_sold", "option_id": "impute"}
POLL = lambda payload: payload.get("columns") == "user_pause_response"  # noqa: E731


def cleaning_row(answer: dict | None = PREVIOUS_ANSWER, status: str = "cleaning") -> FakeSupabase:
    """The row as cleaner_node leaves it before its next pause: the previous answer still stored."""
    return FakeSupabase(rows={"analyses": [{
        "id": "test-id", "status": status, "pause_data": None,
        "user_pause_response": answer, "updated_at": "t0",
    }]})


def answer_units(fake: FakeSupabase) -> None:
    """The user answered the pause through /resume."""
    fake.row("analyses", "test-id").update({
        "status": "cleaning", "pause_data": None, "user_pause_response": UNITS_ANSWER, "updated_at": "t1",
    })


def write_units_pause(fake: FakeSupabase) -> None:
    with patch("backend.agents.orchestrator.get_supabase_client", return_value=fake):
        asyncio.run(_write_pause("test-id", "missing_value_pause", UNITS_PAUSE))


def poll_once(fake: FakeSupabase) -> dict | None:
    with patch("backend.agents.orchestrator.get_supabase_client", return_value=fake):
        return asyncio.run(check_for_pause_response("test-id"))


def test_pause_write_landed_with_its_response_lost_is_not_rewritten() -> None:
    fake = cleaning_row()
    fake.faults.append(Fault("update", "analyses", mode="after"))
    write_units_pause(fake)
    assert len(fake.executes("update", "analyses")) == 1
    row = fake.row("analyses", "test-id")
    assert (row["status"], row["pause_data"], row["user_pause_response"]) == ("missing_value_pause", UNITS_PAUSE, None)


def test_pause_write_landed_and_answered_meanwhile_never_erases_the_answer() -> None:
    fake = cleaning_row()
    fake.faults.append(Fault("update", "analyses", mode="after", after_raise=answer_units))
    write_units_pause(fake)
    assert len(fake.executes("update", "analyses")) == 1
    assert poll_once(fake) == UNITS_ANSWER


def test_pause_write_not_landed_is_rewritten() -> None:
    fake = cleaning_row(answer=None, status="profiling")
    fake.faults.append(Fault("update", "analyses", mode="before"))
    write_units_pause(fake)
    assert len(fake.executes("update", "analyses")) == 2
    assert fake.row("analyses", "test-id")["status"] == "missing_value_pause"


def test_pause_write_not_landed_while_the_previous_answer_is_stored_is_rewritten() -> None:
    """The previous pause's answer is still in the row: it is not an answer to this
    pause, so the write did not land; the rewrite clears it and the poll never returns it."""
    fake = cleaning_row(answer=PREVIOUS_ANSWER)
    fake.faults.append(Fault("update", "analyses", mode="before"))
    write_units_pause(fake)
    assert len(fake.executes("update", "analyses")) == 2
    row = fake.row("analyses", "test-id")
    assert (row["status"], row["pause_data"]) == ("missing_value_pause", UNITS_PAUSE)
    assert poll_once(fake) is None


def test_pause_write_same_column_but_other_pause_type_answer_is_not_landed() -> None:
    """messy_data.csv's revenue gets an outlier pause and a missing-value pause: the
    outlier answer on the same column must not count as this pause's answer."""
    previous = {"pause_type": "outlier_pause", "column_name": "revenue", "option_id": "treat_as_valid"}
    fake = cleaning_row(answer=previous)
    fake.faults.append(Fault("update", "analyses", mode="before"))
    with patch("backend.agents.orchestrator.get_supabase_client", return_value=fake):
        asyncio.run(_write_pause("test-id", "missing_value_pause", MISSING_VALUE_PAUSE_DATA))
    assert len(fake.executes("update", "analyses")) == 2
    assert poll_once(fake) is None


@pytest.mark.parametrize("answered", [False, True])
def test_domain_pause_write_landed_is_not_rewritten(answered: bool) -> None:
    def answer_domain(fake: FakeSupabase) -> None:
        fake.row("analyses", "test-id").update({
            "status": "profiling", "pause_data": None,
            "user_pause_response": {"pause_type": "domain_pause", "option_id": "confirm"},
        })

    fake = cleaning_row(answer=None, status="profiling")
    fake.faults.append(Fault("update", "analyses", mode="after", after_raise=answer_domain if answered else None))
    with patch("backend.agents.orchestrator.get_supabase_client", return_value=fake):
        asyncio.run(_write_pause("test-id", "domain_pause", DOMAIN_PAUSE_DATA))
    assert len(fake.executes("update", "analyses")) == 1
    assert fake.row("analyses", "test-id")["status"] == ("profiling" if answered else "domain_pause")


def test_domain_pause_write_not_landed_is_rewritten() -> None:
    fake = cleaning_row(answer=None, status="profiling")
    fake.faults.append(Fault("update", "analyses", mode="before"))
    with patch("backend.agents.orchestrator.get_supabase_client", return_value=fake):
        asyncio.run(_write_pause("test-id", "domain_pause", DOMAIN_PAUSE_DATA))
    assert len(fake.executes("update", "analyses")) == 2
    assert fake.row("analyses", "test-id")["pause_data"] == DOMAIN_PAUSE_DATA


def test_poll_read_is_retried_by_the_helper() -> None:
    fake = cleaning_row(answer=UNITS_ANSWER)
    fake.faults.append(Fault("select", "analyses", when=POLL))
    assert poll_once(fake) == UNITS_ANSWER
    assert len(fake.executes("select", "analyses")) == 2


def test_wait_node_keeps_polling_through_a_failed_poll_and_picks_up_the_answer(caplog: pytest.LogCaptureFixture) -> None:
    """The helper gave up on one poll (3 transient failures); the wait loop polls again."""
    fake = cleaning_row(answer=None)
    fake.faults.extend(Fault("select", "analyses", when=POLL) for _ in range(3))
    polls = {"n": 0}
    real_check = check_for_pause_response

    async def check(analysis_id: str) -> dict | None:
        polls["n"] += 1
        if polls["n"] == 2:
            answer_units(fake)
        return await real_check(analysis_id)

    state = {"analysis_id": "test-id", "missing_value_pause_data": UNITS_PAUSE, "outlier_pause_data": None}
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=fake),
        patch("backend.agents.orchestrator.check_for_pause_response", new=check),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
        caplog.at_level("WARNING"),
    ):
        result = asyncio.run(cleaner_pause_wait_node(state))
    assert result["user_pause_response"] == UNITS_ANSWER
    assert polls["n"] == 2
    assert any("still polling" in r.getMessage() for r in caplog.records)


def test_wait_node_raises_after_120_seconds_of_consecutive_poll_failures() -> None:
    fake = cleaning_row(answer=None)
    failing = AsyncMock(side_effect=httpx.RemoteProtocolError("Server disconnected"))
    state = {"analysis_id": "test-id", "missing_value_pause_data": UNITS_PAUSE, "outlier_pause_data": None}
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=fake),
        patch("backend.agents.orchestrator.check_for_pause_response", new=failing),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
        patch.object(orchestrator, "_monotonic", side_effect=[1000.0, 1060.0, 1119.9, 1120.0]),
    ):
        with pytest.raises(httpx.RemoteProtocolError):
            asyncio.run(cleaner_pause_wait_node(state))
    assert failing.await_count == 4


def test_wait_node_failure_clock_restarts_after_a_successful_poll() -> None:
    fake = cleaning_row(answer=None)
    outcomes = [httpx.ReadError("x"), None, httpx.ReadError("x"), UNITS_ANSWER]
    check = AsyncMock(side_effect=outcomes)
    state = {"analysis_id": "test-id", "missing_value_pause_data": UNITS_PAUSE, "outlier_pause_data": None}
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=fake),
        patch("backend.agents.orchestrator.check_for_pause_response", new=check),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
        # Two failures 500 s apart, separated by a good poll: never 120 s consecutive.
        patch.object(orchestrator, "_monotonic", side_effect=[0.0, 500.0]),
    ):
        result = asyncio.run(cleaner_pause_wait_node(state))
    assert result["user_pause_response"] == UNITS_ANSWER


def test_wait_node_raises_a_non_transient_poll_error_at_once() -> None:
    fake = cleaning_row(answer=None)
    check = AsyncMock(side_effect=RuntimeError("bad row"))
    state = {"analysis_id": "test-id", "missing_value_pause_data": UNITS_PAUSE, "outlier_pause_data": None}
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=fake),
        patch("backend.agents.orchestrator.check_for_pause_response", new=check),
        patch("backend.agents.orchestrator.asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(RuntimeError, match="bad row"):
            asyncio.run(cleaner_pause_wait_node(state))
    assert check.await_count == 1


def test_run_pipeline_error_write_survives_one_transient_failure() -> None:
    fake = cleaning_row(answer=None, status="profiling")
    fake.faults.append(Fault("update", "analyses", mode="before", when=lambda p: p.get("status") == "error"))
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=fake),
        patch("backend.agents.orchestrator.create_tracer", return_value=BaseCallbackHandler()),
        patch("backend.agents.orchestrator.profiler_node", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        initial_state = asyncio.run(build_initial_state("test-id", "test.csv", None, None))
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(run_pipeline(initial_state))
    row = fake.row("analyses", "test-id")
    assert (row["status"], row["error_message"]) == ("error", "SYSTEM_ERROR: boom")
    assert len(fake.executes("update", "analyses")) == 2


def test_pause_write_without_a_column_never_takes_a_stored_answer_as_its_own() -> None:
    """The fallback pause (no pause_data): an earlier answer of the same type with no
    column_name must not count as landed (Code Review, Build L.2)."""
    earlier = {"pause_type": "missing_value_pause", "option_id": "impute"}
    fake = cleaning_row(answer=earlier)
    fake.faults.append(Fault("update", "analyses", mode="before"))
    with patch("backend.agents.orchestrator.get_supabase_client", return_value=fake):
        asyncio.run(_write_pause("test-id", "missing_value_pause", None))
    assert len(fake.executes("update", "analyses")) == 2
    assert poll_once(fake) is None
