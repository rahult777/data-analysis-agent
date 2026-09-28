"""Tests for the Explainer agent — Agent 4 in the data analysis pipeline."""

import pytest
import pandas as pd

from backend.tools.code_executor import run_question, validate_code
from backend.agents.explainer import build_explainer_message


# ---------------------------------------------------------------------------
# Code executor unit tests (no live services required)
# ---------------------------------------------------------------------------


def test_code_execution_valid():
    df = pd.read_csv("tests/fixtures/iris.csv")
    result, err = run_question(df, "result = df['sepal_length'].mean()")
    assert err is None
    assert isinstance(result, float)


def test_code_execution_no_result():
    df = pd.read_csv("tests/fixtures/iris.csv")
    _, err = run_question(df, "x = df.mean(numeric_only=True)")
    assert err is not None


def test_code_execution_forbidden():
    error = validate_code("import os; result = 1")
    assert error is not None


# ---------------------------------------------------------------------------
# build_explainer_message unit test (exercises explainer.py directly)
# ---------------------------------------------------------------------------


def test_build_explainer_message_structure():
    state = {
        "analysis_id": "test-id",
        "stored_filename": "test.csv",
        "context": None,
        "user_type": None,
        "profile_report": None,
        "domain_confirmed": False,
        "domain_pause_data": None,
        "cleaning_report": None,
        "analysis_report": None,
        "insight_report": None,
        "error_message": None,
        "profiler_domain_hypothesis": None,
        "profiler_domain_confidence_score": None,
        "profiler_provenance_hypothesis": None,
        "profiler_top_3_concerns": None,
        "profiler_top_3_patterns": None,
        "cleaner_key_decisions": None,
        "cleaner_excluded_columns": None,
        "cleaner_outliers_handled": None,
        "cleaner_user_decisions_incorporated": None,
        "missing_value_pause_data": None,
        "outlier_pause_data": None,
        "user_pause_response": None,
        "chart_paths": None,
        "data_quality_score": None,
        "analyzer_most_important_finding": None,
        "executive_summary": None,
        "explainer_lead": None,
    }
    result = build_explainer_message(state)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Integration tests — require live Supabase and Anthropic API
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live Supabase and Anthropic API — not run in CI")
def test_answer_question_integration():
    pass


@pytest.mark.skip(reason="Requires live Supabase and Anthropic API — not run in CI")
def test_explainer_node_integration():
    pass


# ---------------------------------------------------------------------------
# Supabase writes survive one transient failure (Build L.2)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import json  # noqa: E402
import pathlib  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from backend.agents.explainer import answer_question, explainer_node  # noqa: E402
from tests.fake_supabase import recording_client  # noqa: E402

EXPLAINER_REPLY = {
    "executive_summary": {"bullets": [{"finding": "Revenue is flat."}]},
    "insight_report": {"open_questions": []},
}


def _run_explainer_node_failing(llm: object, fail_updates: frozenset) -> tuple:
    supabase, updates = recording_client(fail_updates)
    message = MagicMock()
    message.stop_reason = "end_turn"
    message.content = [MagicMock(text=json.dumps(llm))] if isinstance(llm, dict) else []
    manager = MagicMock()
    manager.__enter__.return_value.get_final_message.return_value = message
    with (
        patch("backend.agents.explainer.client") as mock_client,
        patch("backend.agents.explainer.get_supabase_client", return_value=supabase),
        patch("backend.agents.explainer.create_tracer"),
    ):
        if isinstance(llm, Exception):
            mock_client.messages.stream.side_effect = llm
        else:
            mock_client.messages.stream.return_value = manager
        try:
            result = asyncio.run(explainer_node({"analysis_id": "test-id"}))
        except Exception as exc:
            result = exc
    return result, [payload for _, payload in updates]


def test_explainer_report_save_survives_one_transient_failure() -> None:
    result, payloads = _run_explainer_node_failing(EXPLAINER_REPLY, frozenset({1}))
    assert result["executive_summary"] == EXPLAINER_REPLY["executive_summary"]
    assert [p["status"] for p in payloads] == ["explaining", "complete", "complete"]
    assert payloads[1]["insight_report"] == payloads[2]["insight_report"] == EXPLAINER_REPLY["insight_report"]


def test_explainer_error_write_survives_one_transient_failure() -> None:
    result, payloads = _run_explainer_node_failing(RuntimeError("llm down"), frozenset({1}))
    assert isinstance(result, RuntimeError)
    assert [p["status"] for p in payloads] == ["explaining", "error", "error"]
    assert payloads[-1]["error_message"] == "SYSTEM_ERROR: llm down"


def _reply(payload: dict) -> MagicMock:
    reply = MagicMock()
    reply.content = [MagicMock(text=json.dumps(payload))]
    return reply


def _answer_question_failing(tmp_path: pathlib.Path, code: str, fail_updates: frozenset, download_error: Exception | None = None) -> tuple:
    parquet = tmp_path / "q.parquet"
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(parquet, index=False)
    supabase, updates = recording_client(fail_updates)
    download = AsyncMock(side_effect=download_error) if download_error else AsyncMock(return_value=str(parquet))
    with (
        patch("backend.agents.explainer.client") as mock_client,
        patch("backend.agents.explainer.get_supabase_client", return_value=supabase),
        patch("backend.agents.explainer.create_tracer"),
        patch("backend.agents.explainer.download_from_storage", new=download),
        patch("backend.agents.explainer.cleanup_temp_file", new=AsyncMock()),
    ):
        mock_client.messages.create.side_effect = [_reply({"pandas_code": code}), _reply({"answer": "The total is 6."})]
        result = asyncio.run(answer_question("test-id", "q-1", "What is the total?"))
    assert all(table == "questions" for table, _ in updates)
    return result, [payload for _, payload in updates]


@pytest.mark.parametrize("failing", [0, 1], ids=["answering", "complete"])
def test_question_writes_survive_one_transient_failure(tmp_path: pathlib.Path, failing: int) -> None:
    result, payloads = _answer_question_failing(tmp_path, "result = df['a'].sum()", frozenset({failing}))
    assert result["answer"] == "The total is 6."
    statuses = ["answering", "complete"]
    statuses.insert(failing, statuses[failing])
    assert [p["status"] for p in payloads] == statuses


@pytest.mark.parametrize(
    "code, expected",
    [("", "The code generator did not produce pandas code."), ("result = df['zzz'].sum()", None)],
    ids=["no-code", "run-error"],
)
def test_question_error_writes_survive_one_transient_failure(tmp_path: pathlib.Path, code: str, expected: str | None) -> None:
    _, payloads = _answer_question_failing(tmp_path, code, frozenset({1}))
    assert [p["status"] for p in payloads] == ["answering", "error", "error"]
    assert payloads[1] == payloads[2]
    if expected is not None:
        assert payloads[-1]["answer"] == expected


def test_question_failure_write_survives_one_transient_failure(tmp_path: pathlib.Path) -> None:
    result, payloads = _answer_question_failing(tmp_path, "", frozenset({0}), download_error=RuntimeError("no parquet"))
    assert result["answer"] == "An error occurred while computing the answer."
    assert payloads == [{"status": "error"}, {"status": "error"}]
