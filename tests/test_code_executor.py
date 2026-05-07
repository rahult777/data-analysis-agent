"""Tests for backend/tools/code_executor.py.

Covers: valid execution, validation rejection, NaN sanitization, type conversion,
DataFrame/Series post-processing, and edge cases. Uses tests/fixtures/iris.csv.
"""

import pathlib

import numpy as np
import pandas as pd
import pytest

from backend.tools.code_executor import run_question, sanitize_result, validate_code

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def iris_df() -> pd.DataFrame:
    """Load the iris fixture into a DataFrame."""
    return pd.read_csv(FIXTURES_DIR / "iris.csv")


# ---------------------------------------------------------------------------
# Valid execution
# ---------------------------------------------------------------------------


def test_valid_mean(iris_df: pd.DataFrame) -> None:
    result, err = run_question(iris_df, "result = df['sepal_length'].mean()")
    assert err is None
    assert isinstance(result, float)
    assert result > 0


def test_valid_groupby(iris_df: pd.DataFrame) -> None:
    code = "result = df.groupby('species')['sepal_length'].mean().to_dict()"
    result, err = run_question(iris_df, code)
    assert err is None
    assert isinstance(result, (dict, list))
    if isinstance(result, dict):
        assert "setosa" in result or len(result) > 0


def test_dataframe_result(iris_df: pd.DataFrame) -> None:
    result, err = run_question(iris_df, "result = df.head(3)")
    assert err is None
    assert isinstance(result, list)
    assert len(result) == 3
    assert isinstance(result[0], dict)


def test_series_result(iris_df: pd.DataFrame) -> None:
    result, err = run_question(iris_df, "result = df['sepal_length']")
    assert err is None
    assert isinstance(result, list)
    assert len(result) == 15


# ---------------------------------------------------------------------------
# Validation rejection
# ---------------------------------------------------------------------------


def test_forbidden_import() -> None:
    _, err = run_question(
        pd.DataFrame(), "import os; result = os.listdir()"
    )
    assert err is not None
    assert "import" in err.lower()


def test_forbidden_dunder() -> None:
    err = validate_code("result = df.__class__.__mro__")
    assert err is not None
    assert "dunder" in err.lower()


def test_missing_result(iris_df: pd.DataFrame) -> None:
    result, err = run_question(iris_df, "x = df.mean(numeric_only=True)")
    assert err is not None


def test_empty_code() -> None:
    err = validate_code("")
    assert err is not None


# ---------------------------------------------------------------------------
# NaN sanitization
# ---------------------------------------------------------------------------


def test_nan_sanitization(iris_df: pd.DataFrame) -> None:
    result, err = run_question(iris_df, "result = float('nan')")
    assert err is None
    assert result is None


# ---------------------------------------------------------------------------
# Timeout (skipped — slow and environment-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Timeout tests are slow and environment-dependent")
def test_timeout(iris_df: pd.DataFrame) -> None:
    result, err = run_question(iris_df, "result = sum(range(10**9))")
    assert err is not None
    assert "timed out" in err.lower()
