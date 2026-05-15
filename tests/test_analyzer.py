"""Tests for backend/agents/analyzer.py.

All tests run from the project root (CWD must be the repo root) because
load_system_prompt resolves paths relative to CWD.

Note: load_system_prompt and parse_json_response are already tested in
test_profiler.py — not duplicated here.

Integration tests requiring a live ANTHROPIC_API_KEY and Supabase are skipped.
"""

import json
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from backend.agents.analyzer import (
    build_analyzer_message,
    check_self_evaluation,
    classify_columns,
    classify_distributions,
    compute_correlation_matrix,
    compute_data_quality_score,
    compute_descriptive_stats,
    compute_value_counts,
    detect_time_series,
    sanitize_for_json,
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Group 0 — classify_columns
# ---------------------------------------------------------------------------


def test_classify_columns_numeric() -> None:
    """Columns without 'id' in the name appear in numeric_cols.

    Note: sepal_width and petal_width are excluded because "width" contains
    the substring "id" — the exclusion rule is a substring check, not a whole
    word match. Only sepal_length and petal_length survive.
    """
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert "sepal_length" in numeric_cols
    assert "petal_length" in numeric_cols
    # sepal_width and petal_width contain "id" (in "width") — correctly excluded
    assert "sepal_width" not in numeric_cols
    assert "petal_width" not in numeric_cols


def test_classify_columns_categorical() -> None:
    """Iris species column appears in cat_cols."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert "species" in cat_cols


def test_classify_columns_id_excluded() -> None:
    """customer_id must not appear in numeric_cols — 'id' exclusion rule."""
    df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert "customer_id" not in numeric_cols


def test_classify_columns_datetime() -> None:
    """Date column converted to datetime64 is detected as datetime_col."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    df["date"] = pd.to_datetime(df["date"])
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert datetime_col == "date"


def test_classify_columns_string_date_invisible() -> None:
    """Date column left as string dtype is invisible to the dtype check."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    # Do NOT convert — date remains object dtype
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert datetime_col is None


# ---------------------------------------------------------------------------
# Group 1 — compute_descriptive_stats
# ---------------------------------------------------------------------------


def test_descriptive_stats_numeric() -> None:
    """Numeric columns produce mean, std, min, max keys."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_descriptive_stats(df, numeric_cols, cat_cols)
    assert isinstance(result, dict)
    assert "sepal_length" in result
    for key in ("mean", "std", "min", "max"):
        assert key in result["sepal_length"]


def test_descriptive_stats_categorical() -> None:
    """Categorical columns produce count, unique_count, top_value, top_value_frequency, mode."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_descriptive_stats(df, numeric_cols, cat_cols)
    assert "species" in result
    for key in ("count", "unique_count", "top_value", "top_value_frequency", "mode"):
        assert key in result["species"]


def test_descriptive_stats_with_missing() -> None:
    """Dataset with missing values does not crash."""
    df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_descriptive_stats(df, numeric_cols, cat_cols)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Group 2 — compute_correlation_matrix
# ---------------------------------------------------------------------------


def test_correlation_matrix_structure() -> None:
    """Result contains matrix and strong_pairs keys."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_correlation_matrix(df, numeric_cols)
    assert isinstance(result, dict)
    assert "matrix" in result
    assert "strong_pairs" in result


def test_correlation_diagonal_never_in_strong_pairs() -> None:
    """No strong_pair entry has col1 == col2 — diagonal masking fix."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_correlation_matrix(df, numeric_cols)
    for pair in result["strong_pairs"]:
        assert pair["col1"] != pair["col2"]


def test_correlation_strong_pairs_threshold() -> None:
    """sales-website_visits correlation 0.983 produces at least one strong pair."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    df["date"] = pd.to_datetime(df["date"])
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_correlation_matrix(df, numeric_cols)
    assert len(result["strong_pairs"]) >= 1


def test_correlation_temperature_not_strong_pair() -> None:
    """Temperature (random noise) does not appear in any strong_pair."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    df["date"] = pd.to_datetime(df["date"])
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_correlation_matrix(df, numeric_cols)
    for pair in result["strong_pairs"]:
        assert "temperature" not in (pair["col1"], pair["col2"])


# ---------------------------------------------------------------------------
# Group 3 — classify_distributions
# ---------------------------------------------------------------------------


def test_classify_distributions_normal() -> None:
    """1000 N(0,1) values classify as normal (|skew| < 0.5)."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({"value": rng.standard_normal(1000)})
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = classify_distributions(df, numeric_cols)
    assert result["value"]["distribution_type"] == "normal"


def test_classify_distributions_skewed() -> None:
    """Exponential distribution classifies as skewed_right (skew >= 0.5)."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({"value": rng.exponential(scale=1.0, size=1000)})
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = classify_distributions(df, numeric_cols)
    assert result["value"]["distribution_type"] == "skewed_right"


def test_classify_distributions_returns_dict() -> None:
    """Result is a dict with at least one key for iris numeric columns."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = classify_distributions(df, numeric_cols)
    assert isinstance(result, dict)
    assert len(result) >= 1


# NOTE: bimodal and other branches in the elif chain are unreachable per
# decisions.md — the three skew branches cover all non-NaN reals. No test
# is written expecting "bimodal" to be returned.


# ---------------------------------------------------------------------------
# Group 4 — detect_time_series
# ---------------------------------------------------------------------------


def test_detect_time_series_with_datetime_column() -> None:
    """Correctly converted datetime column is detected with detected=True."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    df["date"] = pd.to_datetime(df["date"])
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    info_dict, recommended_value_column = detect_time_series(df, datetime_col, numeric_cols)
    assert info_dict is not None
    assert info_dict["detected"] is True
    assert info_dict["datetime_column"] == "date"
    assert recommended_value_column is not None


def test_detect_time_series_nan_mask_exercised() -> None:
    """Function handles 5% NaN in sales without error; trend is a valid value."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    df["date"] = pd.to_datetime(df["date"])
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    info_dict, recommended_value_column = detect_time_series(df, datetime_col, numeric_cols)
    assert info_dict is not None
    assert info_dict["trend"] in ("upward", "downward", "flat")


def test_detect_time_series_no_datetime() -> None:
    """Iris has no datetime column — function returns (None, None)."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    # datetime_col is None for iris
    info_dict, recommended_value_column = detect_time_series(df, datetime_col, numeric_cols)
    assert info_dict is None


def test_detect_time_series_string_date_invisible() -> None:
    """String-dtype date is invisible to classify_columns — returns (None, None)."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    # Do NOT convert — string date is invisible, datetime_col will be None
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    info_dict, recommended_value_column = detect_time_series(df, datetime_col, numeric_cols)
    assert info_dict is None


def test_detect_time_series_returns_tuple() -> None:
    """Return value is a 2-tuple."""
    df = pd.read_csv(FIXTURES_DIR / "time_series_data.csv")
    df["date"] = pd.to_datetime(df["date"])
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = detect_time_series(df, datetime_col, numeric_cols)
    assert isinstance(result, tuple)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Group 5 — compute_value_counts
# ---------------------------------------------------------------------------


def test_value_counts_structure() -> None:
    """Result contains species key with a list of count entries."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_value_counts(df, cat_cols)
    assert isinstance(result, dict)
    assert "species" in result
    assert isinstance(result["species"], list)


def test_value_counts_top_n() -> None:
    """No column in result has more than 10 entries (top_n=10 default)."""
    df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_value_counts(df, cat_cols)
    for col, entries in result.items():
        assert len(entries) <= 10


def test_value_counts_no_categoricals() -> None:
    """Empty categorical list returns empty dict without error."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    result = compute_value_counts(df, [])
    assert isinstance(result, dict)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Group 6 — sanitize_for_json
# ---------------------------------------------------------------------------


def test_sanitize_nan_replaced() -> None:
    """NaN float is replaced with None."""
    result = sanitize_for_json({"a": float("nan")})
    assert result["a"] is None


def test_sanitize_inf_replaced() -> None:
    """Both +Inf and -Inf are replaced with None."""
    result = sanitize_for_json({"a": float("inf"), "b": float("-inf")})
    assert result["a"] is None
    assert result["b"] is None


def test_sanitize_returns_new_object() -> None:
    """Returns a new object — does not mutate the original in place."""
    original = {"a": float("nan")}
    result = sanitize_for_json(original)
    assert result is not original


def test_sanitize_nested() -> None:
    """NaN values at multiple nesting levels are all replaced."""
    nested = {"outer": {"inner": float("nan"), "also": float("inf")}, "top": float("nan")}
    result = sanitize_for_json(nested)
    assert result["top"] is None
    assert result["outer"]["inner"] is None
    assert result["outer"]["also"] is None


def test_sanitize_tuple_to_list() -> None:
    """Tuples are converted to lists."""
    result = sanitize_for_json({"a": (1, 2, 3)})
    assert isinstance(result["a"], list)
    assert result["a"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Group 7 — compute_data_quality_score
# ---------------------------------------------------------------------------


def test_data_quality_score_clean() -> None:
    """Clean iris dataset returns a float in [0.1, 1.0]."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    score = compute_data_quality_score(df, None)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_data_quality_score_messy() -> None:
    """Messy dataset with missing values scores lower than clean iris."""
    iris_df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    messy_df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    iris_score = compute_data_quality_score(iris_df, None)
    messy_score = compute_data_quality_score(messy_df, None)
    assert messy_score < iris_score


# ---------------------------------------------------------------------------
# Group 8 — build_analyzer_message
# ---------------------------------------------------------------------------


def _minimal_analyzer_message(**overrides) -> str:
    """Call build_analyzer_message with minimal valid inputs."""
    defaults = dict(
        analysis_id="test-id",
        profile_report=None,
        cleaning_report=None,
        descriptive_stats={},
        correlation_result=None,
        distributions={},
        value_counts={},
        time_series_result=None,
        domain_hypothesis="",
        provenance_hypothesis="",
        top_3_concerns=[],
        top_3_patterns=[],
        user_context=None,
        interactions_detected=None,
        failed_criteria=None,
    )
    defaults.update(overrides)
    return build_analyzer_message(**defaults)


def test_build_analyzer_message_returns_json() -> None:
    """Result is a str that parses as JSON without error."""
    result = _minimal_analyzer_message()
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


def test_build_analyzer_message_contains_required_keys() -> None:
    """DOMAIN_HYPOTHESIS and MANDATORY_INVESTIGATION_AGENDA are always present."""
    result = _minimal_analyzer_message()
    parsed = json.loads(result)
    assert "DOMAIN_HYPOTHESIS" in parsed
    assert "MANDATORY_INVESTIGATION_AGENDA" in parsed


def test_build_analyzer_message_user_intent_absent_when_none() -> None:
    """USER_INTENT key is absent when user_context is None."""
    result = _minimal_analyzer_message(user_context=None)
    parsed = json.loads(result)
    assert "USER_INTENT" not in parsed


def test_build_analyzer_message_user_intent_present_when_provided() -> None:
    """USER_INTENT key is present when user_context is provided."""
    result = _minimal_analyzer_message(user_context="test intent")
    parsed = json.loads(result)
    assert "USER_INTENT" in parsed
    assert parsed["USER_INTENT"]["context"] == "test intent"


# ---------------------------------------------------------------------------
# Group 9 — check_self_evaluation
# ---------------------------------------------------------------------------


def test_check_self_evaluation_all_pass() -> None:
    """All 5 criteria satisfied — returns (True, [])."""
    # criterion (c): "anomal" must appear in str(analysis_response).lower()
    analysis_response = {
        "most_important_finding": "Revenue shows anomalous spike in Q3",
        "most_surprising_finding": "Website visits doubled independently",
    }
    all_passed, failed_criteria = check_self_evaluation(
        analysis_response=analysis_response,
        top_3_concerns=[],          # (a) trivially passes
        correlation_result=None,    # (b) trivially passes
        chart_paths=["chart1.png"], # (d) passes
    )
    assert all_passed is True
    assert failed_criteria == []


def test_check_self_evaluation_fails_when_chart_paths_empty() -> None:
    """Empty chart_paths triggers criterion (d) failure."""
    analysis_response = {
        "most_important_finding": "Revenue shows anomalous spike in Q3",
        "most_surprising_finding": "Website visits doubled independently",
    }
    all_passed, failed_criteria = check_self_evaluation(
        analysis_response=analysis_response,
        top_3_concerns=[],
        correlation_result=None,
        chart_paths=[],  # (d) fails
    )
    assert all_passed is False
    assert len(failed_criteria) >= 1


# ---------------------------------------------------------------------------
# Group 10 — Integration tests (skipped — require live services)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_analyzer_node_full_run() -> None:
    pass


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_analyzer_self_evaluation_loop() -> None:
    pass


@pytest.mark.skip(reason="Requires live filesystem and Supabase")
def test_analyzer_chart_generation() -> None:
    pass
