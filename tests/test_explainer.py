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
