"""Tests for backend/agents/cleaner.py.

All tests run from the project root (CWD must be the repo root) because
load_system_prompt resolves paths relative to CWD.

Note: load_system_prompt and parse_json_response are already tested in
test_profiler.py — not duplicated here.

Integration tests requiring a live ANTHROPIC_API_KEY and Supabase are skipped.
Group 7 runs cleaner_node with the Anthropic client, Supabase, Storage, the
LangSmith tracer, the file loader and the parquet write mocked; it is a plain
test driven by asyncio.run().
"""

import asyncio
import copy
import io
import json
import pathlib
from unittest.mock import DEFAULT, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.agents.cleaner import (
    analyze_missingness_patterns,
    build_cleaner_message,
    cleaner_node,
    detect_interactions,
    execute_cleaning_operations,
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Group 1 — analyze_missingness_patterns
# ---------------------------------------------------------------------------


def test_analyze_missingness_random() -> None:
    """DataFrame with unrelated NaN positions returns a dict without crashing."""
    df = pd.DataFrame({
        "a": [1.0, np.nan, 3.0, 4.0, 5.0],
        "b": [np.nan, 2.0, np.nan, 4.0, 5.0],
    })
    result = analyze_missingness_patterns(df)
    assert isinstance(result, dict)


def test_analyze_missingness_correlated() -> None:
    """return_flag and notes are co-empty — return_flag classified as correlated."""
    df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    result = analyze_missingness_patterns(df)
    assert isinstance(result, dict)
    assert "return_flag" in result
    assert result["return_flag"]["classification"] == "correlated-with-other-columns"


def test_analyze_missingness_no_missing() -> None:
    """iris.csv has no missing values — function returns an empty dict."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    result = analyze_missingness_patterns(df)
    assert isinstance(result, dict)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Group 2 — detect_interactions
# ---------------------------------------------------------------------------


def test_detect_interactions_co_missing_detected() -> None:
    """return_flag + notes co-missing (15 rows) exceeds both thresholds."""
    df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    result = detect_interactions(df, {})
    assert isinstance(result, list)
    assert len(result) >= 1


def test_detect_interactions_no_interactions() -> None:
    """iris.csv has no missing values — detect_interactions returns empty list."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    result = detect_interactions(df, {})
    assert isinstance(result, list)
    assert len(result) == 0


def test_detect_interactions_returns_list() -> None:
    """detect_interactions always returns a list, never a dict."""
    df = pd.read_csv(FIXTURES_DIR / "messy_data.csv")
    result = detect_interactions(df, {})
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Group 3 — build_cleaner_message
# ---------------------------------------------------------------------------


@pytest.fixture
def messy_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES_DIR / "messy_data.csv")


@pytest.fixture
def messy_missingness_patterns(messy_df: pd.DataFrame) -> dict:
    return analyze_missingness_patterns(messy_df)


def test_build_cleaner_message_structure(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    """Return value is valid JSON with all expected top-level keys."""
    result = build_cleaner_message(
        df=messy_df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        user_pause_response=None,
        missingness_patterns=messy_missingness_patterns,
    )
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert "row_count" in parsed
    assert "column_count" in parsed
    assert "column_info" in parsed
    assert "missingness_patterns" in parsed


def test_build_cleaner_message_includes_outlier_info(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    """Revenue has 4 outliers above IQR upper bound — outlier_count == 4."""
    result = build_cleaner_message(
        df=messy_df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        user_pause_response=None,
        missingness_patterns=messy_missingness_patterns,
    )
    parsed = json.loads(result)
    assert "revenue" in parsed["column_info"]
    assert parsed["column_info"]["revenue"]["outlier_count"] == 4


def test_build_cleaner_message_includes_missing_info(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    """missing_pct is on 0-100 scale: revenue ~35.0, notes ~45.5."""
    result = build_cleaner_message(
        df=messy_df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        user_pause_response=None,
        missingness_patterns=messy_missingness_patterns,
    )
    parsed = json.loads(result)
    col_info = parsed["column_info"]
    assert abs(col_info["revenue"]["missing_pct"] - 35.0) < 2
    assert abs(col_info["notes"]["missing_pct"] - 45.5) < 2


def test_build_cleaner_message_with_user_pause_response(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    """user_pause_response appears in parsed output when provided."""
    pause_response = {"decision": "impute_median", "column": "revenue"}
    result = build_cleaner_message(
        df=messy_df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        user_pause_response=pause_response,
        missingness_patterns=messy_missingness_patterns,
    )
    parsed = json.loads(result)
    assert "user_pause_response" in parsed
    assert parsed["user_pause_response"] == pause_response


def test_build_cleaner_message_categorical_sample_shows_every_category() -> None:
    """iris.csv is grouped by species — sample_values must show all 3, not the first block."""
    df = pd.read_csv(FIXTURES_DIR / "iris.csv")
    missingness_patterns = analyze_missingness_patterns(df)
    result = build_cleaner_message(
        df=df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        user_pause_response=None,
        missingness_patterns=missingness_patterns,
    )
    parsed = json.loads(result)
    assert len(set(parsed["column_info"]["species"]["sample_values"])) == 3


# ---------------------------------------------------------------------------
# Group 4 — execute_cleaning_operations
# ---------------------------------------------------------------------------


def test_execute_cleaning_median_fill() -> None:
    """Median fill decision removes all NaN from a numeric column."""
    df = pd.DataFrame({"value": [1.0, 2.0, np.nan, 4.0, 5.0]})
    decisions = [{"column_name": "value", "action": "fill median", "issue": "missing values"}]
    df_cleaned, excluded_cols, outlier_flagged = execute_cleaning_operations(df, decisions)
    assert df_cleaned["value"].isna().sum() == 0


def test_execute_cleaning_drop_column() -> None:
    """Drop column decision removes the column and reports it in excluded_cols."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})
    decisions = [{"column_name": "b", "action": "drop column", "issue": "too many missing"}]
    df_cleaned, excluded_cols, outlier_flagged = execute_cleaning_operations(df, decisions)
    assert "b" not in df_cleaned.columns
    assert len(df_cleaned.columns) == 2


def test_execute_cleaning_drop_duplicates() -> None:
    """column_name=None triggers deduplication across the full DataFrame."""
    df = pd.DataFrame({
        "x": [1, 2, 1, 2, 3],
        "y": [10, 20, 10, 20, 30],
    })
    decisions = [{"column_name": None, "action": "drop duplicates", "issue": "duplicate rows"}]
    df_cleaned, excluded_cols, outlier_flagged = execute_cleaning_operations(df, decisions)
    assert df_cleaned.duplicated().sum() == 0


def test_execute_cleaning_returns_tuple() -> None:
    """execute_cleaning_operations returns a 3-tuple: (DataFrame, list, dict)."""
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = execute_cleaning_operations(df, [])
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert isinstance(result[0], pd.DataFrame)
    assert isinstance(result[1], list)
    assert isinstance(result[2], dict)


# ---------------------------------------------------------------------------
# Group 5 — Integration tests (skipped — require live services)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_cleaner_node_full_run() -> None:
    pass


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_cleaner_node_missing_value_pause() -> None:
    pass


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_cleaner_node_outlier_pause() -> None:
    pass


@pytest.mark.skip(reason="Requires live Supabase Storage")
def test_cleaner_parquet_upload() -> None:
    pass


# ---------------------------------------------------------------------------
# Group 6 — bool-dtype (True/False) columns
# ---------------------------------------------------------------------------


def _bool_df(n: int) -> pd.DataFrame:
    """A bool column with n non-null values, plus a numeric column with gaps."""
    return pd.DataFrame({
        "flag": [i % 2 == 0 for i in range(n)],
        "amount": [float(i) if i % 3 else np.nan for i in range(n)],
    })


def _cleaner_message(df: pd.DataFrame) -> dict:
    return json.loads(build_cleaner_message(
        df=df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        user_pause_response=None,
        missingness_patterns={},
    ))


@pytest.mark.parametrize("n", [4, 5, 50])
def test_detect_interactions_bool_column_does_not_raise(n: int) -> None:
    """bool.quantile() raises TypeError; 4 values is the old crash threshold here."""
    result = detect_interactions(_bool_df(n), {})
    assert isinstance(result, list)


def test_build_cleaner_message_bool_column_does_not_raise() -> None:
    """A bool column gets no IQR stats; a real numeric column still does."""
    df = _bool_df(20)
    df["count"] = list(range(19)) + [500]
    column_info = _cleaner_message(df)["column_info"]

    assert "outlier_count" not in column_info["flag"]
    assert "outlier_bounds" not in column_info["flag"]
    assert column_info["count"]["outlier_count"] == 1
    assert "outlier_bounds" in column_info["count"]


def test_execute_cleaning_outlier_flag_on_bool_column_is_skipped() -> None:
    """Flagging outliers on a bool column is a no-op, like any non-numeric column."""
    df = _bool_df(20)
    decisions = [{"column_name": "flag", "action": "flag outliers", "issue": "outliers"}]
    df_cleaned, excluded_cols, outlier_flagged = execute_cleaning_operations(df, decisions)

    assert "flag_outlier_flag" not in df_cleaned.columns
    assert outlier_flagged == {}


def test_build_cleaner_message_imbalanced_bool_sample_shows_both_values() -> None:
    """990 False / 10 True — a random sample of 5 is almost always all False."""
    df = pd.DataFrame({"flag": [False] * 990 + [True] * 10})
    sample = _cleaner_message(df)["column_info"]["flag"]["sample_values"]
    assert set(sample) == {"True", "False"}


def test_build_cleaner_message_bool_with_missing_values_uses_distinct_sampling() -> None:
    """True/False with blanks loads from CSV as object dtype and keeps distinct-value sampling."""
    csv = "id,flag\n" + "\n".join(
        f"{i},{'True' if i < 990 else 'False' if i < 1000 else ''}" for i in range(1005)
    )
    df = pd.read_csv(io.StringIO(csv))
    assert df["flag"].dtype == object

    sample = _cleaner_message(df)["column_info"]["flag"]["sample_values"]
    assert set(sample) == {"True", "False"}


# ---------------------------------------------------------------------------
# Group 7 — cleaner_node with mocked services
# ---------------------------------------------------------------------------


def test_cleaner_node_completes_with_bool_column() -> None:
    """cleaner_node gets past detect_interactions to its LLM call and saves status=cleaned."""
    captured: list[dict] = []
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps({"decisions": []}))]
    state = {"analysis_id": "test-analysis-id", "stored_filename": "bool.csv"}

    with (
        patch("backend.agents.cleaner.client") as mock_client,
        patch("backend.agents.cleaner.get_supabase_client") as mock_get_supabase_client,
        patch("backend.agents.cleaner.create_tracer"),
        patch("backend.agents.cleaner.load_dataframe_from_uploads", return_value=_bool_df(20)),
        patch("backend.agents.cleaner.upload_to_storage"),
        patch("backend.agents.cleaner.cleanup_temp_file"),
        patch.object(pd.DataFrame, "to_parquet"),
    ):
        mock_client.messages.create.return_value = response
        mock_update = mock_get_supabase_client.return_value.table.return_value.update
        mock_update.side_effect = lambda payload: (captured.append(copy.deepcopy(payload)), DEFAULT)[1]
        result = asyncio.run(cleaner_node(state))

    mock_client.messages.create.assert_called_once()
    assert [payload["status"] for payload in captured] == ["cleaning", "cleaned"]
    assert not any("error_message" in payload for payload in captured)
    assert result["cleaning_report"]["summary"]["rows_after"] == 20
