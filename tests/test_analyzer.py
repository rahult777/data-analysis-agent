"""Tests for backend/agents/analyzer.py.

All tests run from the project root (CWD must be the repo root) because
load_system_prompt resolves paths relative to CWD.

Note: load_system_prompt and parse_json_response are already tested in
test_profiler.py — not duplicated here.

Integration tests requiring a live ANTHROPIC_API_KEY and Supabase are skipped.
"""

import asyncio
import copy
import json
import math
import pathlib
from typing import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.agents import analyzer
from backend.agents.profiler import load_system_prompt
from backend.agents.analyzer import (
    CORRELATION_MIN_PAIRS,
    _is_id_column,
    analyzer_node,
    apply_correlation_floor,
    build_analyzer_message,
    check_self_evaluation,
    classify_columns,
    classify_distributions,
    compute_correlation_matrix,
    compute_data_quality_score,
    compute_descriptive_stats,
    compute_value_counts,
    count_complete_pairs,
    detect_time_series,
    sanitize_for_json,
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Group 0 — classify_columns
# ---------------------------------------------------------------------------


def test_classify_columns_numeric() -> None:
    """Columns without a standalone "id" name component appear in numeric_cols.

    sepal_width and petal_width contain "id" only as a substring of "width",
    so they are numeric (errors.md 2026-05-15).
    """
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert "sepal_length" in numeric_cols
    assert "petal_length" in numeric_cols
    assert "sepal_width" in numeric_cols
    assert "petal_width" in numeric_cols


def test_classify_columns_iris_all_four_numeric() -> None:
    """All four iris measurements are numeric, in file order."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert numeric_cols == ["sepal_length", "sepal_width", "petal_length", "petal_width"]


def test_classify_columns_applies_token_rule() -> None:
    """classify_columns excludes id-like names and keeps substring false positives."""
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "CustomerID": [101, 102, 103],
        "paid_amount": [9.5, 12.0, 3.25],
        "humidity": [0.4, 0.55, 0.61],
    })
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    assert numeric_cols == ["paid_amount", "humidity"]


@pytest.mark.parametrize("name", [
    "id", "ID", "Id", "customer_id", "customer-id", "customer id", "id_customer",
    "CustomerId", "CustomerID", "Customer_Id",
    "grid_id",  # excluded by its "_id" component; "grid" alone is not an id name
])
def test_is_id_column_true_positives(name: str) -> None:
    assert _is_id_column(name) is True


@pytest.mark.parametrize("name", [
    "width", "valid", "paid_amount", "dividend", "residual", "humidity",
    "rapid_response_time", "sepal_width", "petal_width", "avoid", "rigid", "arid",
])
def test_is_id_column_false_positives(name: str) -> None:
    assert _is_id_column(name) is False


@pytest.mark.parametrize("name", [
    # ID acronym immediately followed by another capitalized word, anywhere in the
    # name — there is no lowercase-to-uppercase boundary between "ID" and the next word.
    "IDCustomer", "IDNumber", "CustomerIDNumber",
    # uuid/guid values load as text, so they never reach the numeric filter.
    "uuid", "guid",
    # Trailing digit or plural.
    "id1", "id2", "related_ids",
    # Separator-less concatenation — indistinguishable from "valid"/"rapid" by tokens.
    "userid", "customerid", "USERID",
])
def test_is_id_column_known_limitations(name: str) -> None:
    """Documented, accepted misses (decisions.md 2026-09-19) — locked in, not solved."""
    assert _is_id_column(name) is False


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


def test_correlation_iris_highest_pair_uses_recovered_columns() -> None:
    """The width columns reach the correlation analysis: petal_length–petal_width is the top pair."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    numeric_cols, cat_cols, datetime_col = classify_columns(df)
    result = compute_correlation_matrix(df, numeric_cols)
    assert result["highest_pair"] == ["petal_length", "petal_width"]
    assert result["highest_value"] == pytest.approx(0.986, abs=1e-3)
    assert len(result["strong_pairs"]) == 3


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


# ---------------------------------------------------------------------------
# Group 11 — column names after the Cleaner's parquet round trip
# ---------------------------------------------------------------------------


def test_analyzer_handles_stringified_headers_after_parquet_roundtrip(tmp_path) -> None:
    """classify_columns assumes every column name is a string — pin that assumption.

    _is_id_column runs re.sub on the name and raises TypeError on a non-string
    label, so an Excel upload with uniform integer (or date) headers would crash
    the Analyzer if such a label could reach it. It cannot: the Analyzer's only
    input is the Cleaner's parquet, and pyarrow stringifies non-string column
    names on the way out. This test fails if that pyarrow behaviour ever changes.
    It does NOT exercise the loader fix in cleaner.py — the round trip alone
    already yields strings — see decisions.md 2026-09-20.
    """
    df = pd.DataFrame({2021: [1.0, 2.0, 3.0], 2022: [4.0, 5.0, 6.0]})
    assert all(isinstance(column, int) for column in df.columns)
    assert not df.isna().to_numpy().any()

    with pytest.raises(TypeError):
        _is_id_column(df.columns[0])

    parquet_path = tmp_path / "cleaned.parquet"
    # The exact call execute_cleaning_operations makes.
    df.to_parquet(parquet_path, index=False)
    loaded = pd.read_parquet(parquet_path)

    assert list(loaded.columns) == ["2021", "2022"]
    numeric_columns, categorical_columns, datetime_column = classify_columns(loaded)
    assert numeric_columns == ["2021", "2022"]
    assert categorical_columns == []
    assert datetime_column is None


# ---------------------------------------------------------------------------
# Group 12 — the 30-pair correlation floor (Build I)
# ---------------------------------------------------------------------------

_CD = "Cannot Determine"


def _sparse() -> pd.DataFrame:
    """60 rows; x*y share 50 complete pairs, y*z 24, x*z 14 (x and z miss different rows)."""
    return pd.read_csv(FIXTURES_DIR / "sparse_pairs.csv")


def _correlation_for(df: pd.DataFrame) -> dict:
    numeric_columns, _, _ = classify_columns(df)
    return compute_correlation_matrix(df, numeric_columns)


def _pairs_by_key(correlation_result: dict) -> dict:
    return {frozenset((p["col1"], p["col2"])): p for p in correlation_result["strong_pairs"]}


def _entry(col_a: object, col_b: object, r: float = 0.9, n: int = 60, confidence: str = "Low") -> dict:
    return {
        "column_a": col_a,
        "column_b": col_b,
        "r": r,
        "n": n,
        "confidence_level": confidence,
        "mechanisms": ["m1", "m2"],
        "confounders": ["c1", "c2"],
        "what_would_establish_causality": "an experiment",
        "causality_label": "This is correlation, not causation.",
    }


def _response(*entries: dict, parent: str = "Low") -> dict:
    return {
        "correlation": {
            "strong_correlations": list(entries),
            "confidence_level": parent,
            "confidence_reasoning": "model reasoning",
        }
    }


def _paired_frame(n_complete: int, n_rows: int = 40) -> pd.DataFrame:
    """Two near-perfectly correlated columns sharing exactly n_complete complete pairs."""
    a = np.arange(n_rows, dtype=float)
    b = 2 * a + np.where(np.arange(n_rows) % 2 == 0, 0.5, -0.5)
    b[n_complete:] = np.nan
    return pd.DataFrame({"a": a, "b": b})


def test_sparse_pairs_fixture_every_pair_is_strong_with_its_complete_pairs() -> None:
    """All three pairs are strong, each n is the pair's complete rows — not the 60 rows,
    and not either column's own count (x and z miss different rows)."""
    df = _sparse()
    assert len(df) == 60
    pairs = _pairs_by_key(_correlation_for(df))
    assert {k: p["n"] for k, p in pairs.items()} == {
        frozenset(("x", "y")): 50,
        frozenset(("y", "z")): 24,
        frozenset(("x", "z")): 14,
    }
    for pair in pairs.values():
        assert abs(pair["correlation_value"]) > 0.7


def test_strong_pairs_n_on_iris_is_15() -> None:
    pairs = _correlation_for(pd.read_csv(FIXTURES_DIR / "iris.csv"))["strong_pairs"]
    assert len(pairs) == 3
    assert all(pair["n"] == 15 for pair in pairs)


def test_count_complete_pairs_matches_what_corr_uses_including_inf() -> None:
    """An inf is excluded by df.corr() (np.isfinite mask) and must not be counted."""
    df = _paired_frame(35)
    df.loc[0, "a"] = np.inf
    n = count_complete_pairs(df, "a", "b")
    assert n == 34
    finite = df[np.isfinite(df["a"]) & np.isfinite(df["b"])]
    assert df.corr().loc["a", "b"] == pytest.approx(finite["a"].corr(finite["b"]))
    assert len(df[["a", "b"]].dropna()) == 35  # what a plain dropna() would wrongly count


@pytest.mark.parametrize("n_complete, expected", [(29, _CD), (30, "Low")])
def test_floor_boundary_29_and_30(n_complete: int, expected: str) -> None:
    df = _paired_frame(n_complete)
    response = _response(_entry("a", "b", n=40, confidence="Low"))
    apply_correlation_floor(response, _correlation_for(df), df)
    entry = response["correlation"]["strong_correlations"][0]
    assert entry["n"] == n_complete
    assert entry["confidence_level"] == expected
    assert ("floor_override" in entry) is (expected == _CD)


def test_floor_never_raises_a_label() -> None:
    """n >= 30 labels are untouched; an existing Cannot Determine gets no record."""
    df = _sparse()
    response = _response(
        _entry("x", "y", confidence="Low"),
        _entry("y", "z", confidence=_CD),
    )
    apply_correlation_floor(response, _correlation_for(df), df)
    xy, yz = response["correlation"]["strong_correlations"]
    assert xy["confidence_level"] == "Low" and "floor_override" not in xy
    assert yz["confidence_level"] == _CD and "floor_override" not in yz


def test_floor_high_at_n_50_stays_high() -> None:
    df = _sparse()
    response = _response(_entry("x", "y", confidence="High"))
    apply_correlation_floor(response, _correlation_for(df), df)
    assert response["correlation"]["strong_correlations"][0]["confidence_level"] == "High"


def test_floor_lowers_with_exact_override_record() -> None:
    df = _sparse()
    response = _response(_entry("y", "z", confidence="Moderate"))
    apply_correlation_floor(response, _correlation_for(df), df)
    entry = response["correlation"]["strong_correlations"][0]
    assert entry["confidence_level"] == _CD
    assert entry["floor_override"] == {
        "original_confidence_level": "Moderate",
        "reason": (
            "System check: Python counted 24 complete pairs for y × z, below the "
            "30-pair reliability floor, so the confidence is Cannot Determine."
        ),
    }


def test_floor_matches_either_order_and_overwrites_r_and_n() -> None:
    df = _sparse()
    correlation_result = _correlation_for(df)
    python_r = _pairs_by_key(correlation_result)[frozenset(("x", "z"))]["correlation_value"]
    response = _response(_entry("z", "x", r=0.74, n=15, confidence="Low"))
    apply_correlation_floor(response, correlation_result, df)
    entry = response["correlation"]["strong_correlations"][0]
    assert entry["r"] == python_r
    assert entry["n"] == 14
    assert entry["confidence_level"] == _CD
    assert response["correlation"]["unverified_correlations"] == []


def test_floor_enforces_every_entry() -> None:
    df = _sparse()
    response = _response(
        _entry("x", "y", confidence="Low"),
        _entry("y", "z", confidence="Low"),
        _entry("x", "z", confidence="High"),
    )
    apply_correlation_floor(response, _correlation_for(df), df)
    labels = [e["confidence_level"] for e in response["correlation"]["strong_correlations"]]
    assert labels == ["Low", _CD, _CD]


@pytest.mark.parametrize("col_a, col_b", [("X", "y"), (" x", "y"), ("x ", "y"), ("y", "y")])
def test_floor_matches_exact_names_only(col_a: str, col_b: str) -> None:
    """No case or whitespace normalization; the same column twice is not a pair."""
    df = _sparse()
    response = _response(_entry(col_a, col_b))
    apply_correlation_floor(response, _correlation_for(df), df)
    assert response["correlation"]["strong_correlations"] == []
    assert len(response["correlation"]["unverified_correlations"]) == 1


def test_floor_non_strong_matrix_pair_is_matched_not_moved() -> None:
    """A model entry for a matrix pair Python did not flag as strong is still verified:
    Python's r and n replace the model's, and the floor applies."""
    df = _sparse()
    df["w"] = (np.arange(60) % 7).astype(float)
    df.loc[25:, "w"] = np.nan  # w*x share 25 complete pairs
    correlation_result = _correlation_for(df)
    assert frozenset(("w", "x")) not in _pairs_by_key(correlation_result)
    response = _response(_entry("x", "w", r=0.91, n=60, confidence="Moderate"))
    apply_correlation_floor(response, correlation_result, df)
    entry = response["correlation"]["strong_correlations"][0]
    assert entry["r"] == correlation_result["matrix"]["x"]["w"]
    assert abs(entry["r"]) < 0.7
    assert entry["n"] == 25
    assert entry["confidence_level"] == _CD
    assert response["correlation"]["unverified_correlations"] == []


def test_floor_moves_pair_absent_from_matrix_with_exact_reason() -> None:
    df = _sparse()
    model_entry = _entry("x", "batch", r=0.74, n=15)
    response = _response(_entry("x", "y"), model_entry)
    apply_correlation_floor(response, _correlation_for(df), df)
    correlation = response["correlation"]
    assert [(e["column_a"], e["column_b"]) for e in correlation["strong_correlations"]] == [("x", "y")]
    assert correlation["unverified_correlations"] == [{
        "column_a": "x",
        "column_b": "batch",
        "reason": (
            "System check: x × batch is not a pair in the system's correlation matrix "
            "(a column is non-numeric, excluded or absent), so its r and n could not "
            "be verified. It is not reported as a correlation."
        ),
        "original_entry": _entry("x", "batch", r=0.74, n=15),
    }]


def test_floor_python_strong_pair_omitted_by_model_is_not_fabricated() -> None:
    df = _sparse()
    response = _response(_entry("x", "y"))
    apply_correlation_floor(response, _correlation_for(df), df)
    assert len(response["correlation"]["strong_correlations"]) == 1


def test_floor_nan_r_pair_does_not_raise_and_is_cannot_determine() -> None:
    """An undefined r (NaN, stored as None) cannot carry any confidence, even at n >= 30."""
    df = _sparse()
    df["const"] = 5.0
    correlation_result = _correlation_for(df)
    assert correlation_result["matrix"]["x"]["const"] is None
    response = _response(_entry("x", "const", confidence="High"))
    apply_correlation_floor(response, correlation_result, df)
    entry = response["correlation"]["strong_correlations"][0]
    assert entry["r"] is None
    assert entry["n"] == 50
    assert entry["confidence_level"] == _CD
    assert entry["floor_override"] == {
        "original_confidence_level": "High",
        "reason": (
            "System check: Python could not compute r for x × const (r is undefined on "
            "their 50 complete pairs, e.g. a constant column), so the confidence is "
            "Cannot Determine."
        ),
    }


def test_floor_parent_lowered_when_every_strong_pair_is_below_30() -> None:
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    response = _response(_entry("sepal_length", "petal_length"), parent="Low")
    apply_correlation_floor(response, _correlation_for(df), df)
    correlation = response["correlation"]
    assert correlation["confidence_level"] == _CD
    assert correlation["floor_override"] == {
        "original_confidence_level": "Low",
        "reason": (
            "System check: every strong correlation rests on fewer than 30 complete "
            "pairs (lowest n = 15), so the overall correlation confidence is Cannot Determine."
        ),
    }
    assert correlation["confidence_reasoning"] == "model reasoning"


def test_floor_parent_untouched_when_any_strong_pair_reaches_30() -> None:
    df = _sparse()  # 50, 24, 14
    response = _response(_entry("y", "z"), parent="Moderate")
    apply_correlation_floor(response, _correlation_for(df), df)
    assert response["correlation"]["confidence_level"] == "Moderate"
    assert "floor_override" not in response["correlation"]


def test_floor_parent_untouched_without_strong_pairs_or_when_already_cd() -> None:
    df = _paired_frame(10)
    df["b"] = np.where(np.arange(40) % 2 == 0, 1.0, -1.0)  # no strong pair
    df.loc[10:, "b"] = np.nan
    no_strong = _correlation_for(df)
    assert no_strong["strong_pairs"] == []
    response = _response(parent="Low")
    apply_correlation_floor(response, no_strong, df)
    assert response["correlation"]["confidence_level"] == "Low"

    iris = pd.read_csv(FIXTURES_DIR / "iris.csv")
    response = _response(parent=_CD)
    apply_correlation_floor(response, _correlation_for(iris), iris)
    assert "floor_override" not in response["correlation"]


def test_floor_without_python_matrix_moves_every_entry() -> None:
    df = _sparse()
    response = _response(_entry("x", "y"))
    apply_correlation_floor(response, None, df)
    assert response["correlation"]["strong_correlations"] == []
    assert len(response["correlation"]["unverified_correlations"]) == 1


@pytest.mark.parametrize("analysis_response", [
    [],
    {},
    {"correlation": None},
    {"correlation": "not an object"},
    {"correlation": {"strong_correlations": "not a list", "confidence_level": "Low"}},
    {"correlation": {"strong_correlations": ["not an object", 7, None]}},
])
def test_floor_never_raises_on_malformed_input(analysis_response: object) -> None:
    df = _sparse()
    before = copy.deepcopy(analysis_response)
    apply_correlation_floor(analysis_response, _correlation_for(df), df)
    correlation = before.get("correlation") if isinstance(before, dict) else None
    entries = correlation.get("strong_correlations") if isinstance(correlation, dict) else None
    if isinstance(entries, list) and not all(isinstance(e, dict) for e in entries):
        assert analysis_response["correlation"]["strong_correlations"] == entries
    elif not isinstance(entries, list) or not entries:
        assert analysis_response == before


def test_floor_malformed_python_strong_pairs_leave_parent_unchanged() -> None:
    df = _sparse()
    correlation_result = _correlation_for(df)
    correlation_result["strong_pairs"] = ["garbage", {"col1": "y", "col2": "z", "n": "24"}]
    response = _response(parent="Low")
    apply_correlation_floor(response, correlation_result, df)
    assert response["correlation"]["confidence_level"] == "Low"


def test_build_analyzer_message_sends_n_for_every_strong_pair() -> None:
    df = _sparse()
    sent = json.loads(_minimal_analyzer_message(correlation_result=_correlation_for(df)))
    assert sorted(p["n"] for p in sent["correlation"]["strong_pairs"]) == [14, 24, 50]


def test_analyzer_prompt_states_the_floor_as_a_confidence_ceiling() -> None:
    prompt = load_system_prompt("analyzer")
    assert "copy both verbatim and never infer n from row counts" in prompt
    assert "The 30-pair rule is a ceiling on confidence, not a condition for computing r" in prompt
    assert "Any confidence other than Cannot Determine (High, Moderate or Low) on a correlation with n below 30 complete pairs" in prompt
    assert "floors, not ceilings" not in prompt
    assert "the correlation is computed but tagged as Cannot Determine" not in prompt
    assert "- High confidence assigned to a correlation with n below 30 pairs." not in prompt


def _stream_returning(payload: dict) -> Callable[..., MagicMock]:
    def stream(**kwargs: object) -> MagicMock:
        message = MagicMock()
        message.stop_reason = "end_turn"
        message.content = [MagicMock(text=json.dumps(payload))]
        manager = MagicMock()
        manager.__enter__.return_value.get_final_message.return_value = message
        return manager
    return stream


def test_analyzer_node_saves_the_floored_report_once(tmp_path: pathlib.Path) -> None:
    """Node level: n comes from the cleaned parquet (not the Profiler's 60 rows), the
    floor runs before the single analysis_report save, and the returned state is the
    saved object."""
    parquet_path = tmp_path / "cleaned.parquet"
    _sparse().to_parquet(parquet_path, index=False)
    cleaned = pd.read_parquet(parquet_path)

    model_payload = {
        "correlation": {
            "strong_correlations": [
                _entry("y", "x", r=0.99, n=60, confidence="High"),
                _entry("z", "y", r=0.97, n=60, confidence="Low"),
                _entry("x", "z", r=0.95, n=60, confidence="Low"),
                _entry("x", "batch", r=0.74, n=60, confidence="Low"),
            ],
            "confidence_level": "Low",
            "confidence_reasoning": "n=60 clears the 30-pair floor",
        },
        "most_important_finding": "x and y move together; one anomaly in batch A",
        "most_surprising_finding": "z tracks y closely",
        "open_questions": [],
    }
    supabase = MagicMock()
    at_save_time: list = []  # deep copies: what was written, not the object afterwards

    def update(payload: dict) -> MagicMock:
        at_save_time.append(copy.deepcopy(payload))
        return MagicMock()

    supabase.table.return_value.update.side_effect = update
    state = {
        "analysis_id": "build-i-node",
        "profile_report": {"row_count": 60},
        "cleaning_report": {"decisions": [], "summary": ""},
        "profiler_top_3_concerns": [],
        "profiler_top_3_patterns": [],
    }
    with (
        patch("backend.agents.analyzer.get_supabase_client", return_value=supabase),
        patch("backend.agents.analyzer.load_cleaned_dataframe", new=AsyncMock(return_value=cleaned)),
        patch("backend.agents.analyzer.cleanup_temp_file", new=AsyncMock()),
        patch("backend.agents.analyzer.generate_all_charts", return_value=["chart.png"]),
        patch("backend.agents.analyzer.create_tracer", return_value=MagicMock()),
        patch.object(analyzer.client.messages, "stream", side_effect=_stream_returning(model_payload)) as stream,
    ):
        result = asyncio.run(analyzer_node(state))

    assert stream.call_count == 1
    sent = json.loads(stream.call_args.kwargs["messages"][0]["content"])
    assert sorted(p["n"] for p in sent["correlation"]["strong_pairs"]) == [14, 24, 50]

    save_calls = [
        c.args[0] for c in supabase.table.return_value.update.call_args_list
        if "analysis_report" in c.args[0]
    ]
    assert len(save_calls) == 1
    assert result["analysis_report"] is save_calls[0]["analysis_report"]
    saved = next(p for p in at_save_time if "analysis_report" in p)["analysis_report"]
    assert result["analysis_report"] == saved

    entries = saved["correlation"]["strong_correlations"]
    by_pair = {frozenset((e["column_a"], e["column_b"])): e for e in entries}
    assert {k: (e["n"], e["confidence_level"]) for k, e in by_pair.items()} == {
        frozenset(("x", "y")): (50, "High"),
        frozenset(("y", "z")): (24, _CD),
        frozenset(("x", "z")): (14, _CD),
    }
    python_pairs = _pairs_by_key(saved["correlation_matrix"])
    for key, entry in by_pair.items():
        assert entry["r"] == python_pairs[key]["correlation_value"]
    assert "floor_override" not in by_pair[frozenset(("x", "y"))]
    assert [u["column_b"] for u in saved["correlation"]["unverified_correlations"]] == ["batch"]
    assert saved["correlation"]["confidence_level"] == "Low"  # the n = 50 pair clears the floor
    assert CORRELATION_MIN_PAIRS == 30


def test_floor_unhashable_column_names_are_unverified_not_raised() -> None:
    df = _sparse()
    response = _response({"column_a": ["x"], "column_b": {"y": 1}, "confidence_level": "Low"})
    apply_correlation_floor(response, _correlation_for(df), df)
    assert response["correlation"]["strong_correlations"] == []
    assert response["correlation"]["unverified_correlations"][0]["column_a"] == ["x"]


def test_count_complete_pairs_excludes_timedelta_nat() -> None:
    """to_numpy(dtype=float) turns NaT into a finite sentinel; it is still a missing value."""
    df = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "t": pd.to_timedelta([1, 2, None, 4, 5, 6], unit="D"),
    })
    assert count_complete_pairs(df, "a", "t") == 5


def test_floor_parent_rule_applies_even_when_entries_are_malformed() -> None:
    """The parent rule reads only Python's strong pairs (iris: all n = 15)."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    response = {"correlation": {"strong_correlations": "not a list", "confidence_level": "Low"}}
    apply_correlation_floor(response, _correlation_for(df), df)
    assert response["correlation"]["strong_correlations"] == "not a list"
    assert response["correlation"]["confidence_level"] == _CD
    assert response["correlation"]["floor_override"]["original_confidence_level"] == "Low"
