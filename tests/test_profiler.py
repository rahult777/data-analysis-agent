"""Tests for backend/agents/profiler.py.

All tests run from the project root (CWD must be the repo root) because
load_system_prompt resolves paths relative to CWD.

Note: PipelineState is NOT imported and NOT used in any test.
build_profiler_message takes (df: pd.DataFrame, context: Optional[str]) directly.

Integration tests requiring a live ANTHROPIC_API_KEY and Supabase are skipped.
Group 8 runs profiler_node with the Anthropic client, Supabase, the LangSmith
tracer and the file loader mocked; it is a plain test driven by asyncio.run().
"""

import asyncio
import copy
import json
import logging
import pathlib
from unittest.mock import DEFAULT, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.agents.profiler import (
    apply_computed_column_stats,
    build_profiler_message,
    compute_column_stats,
    load_system_prompt,
    parse_json_response,
    profiler_node,
)

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Group 1 — load_system_prompt
# ---------------------------------------------------------------------------


def test_load_system_prompt_profiler_returns_content() -> None:
    """Valid agent name returns a non-empty string."""
    result = load_system_prompt("profiler")
    assert isinstance(result, str)
    assert len(result) > 0


def test_load_system_prompt_missing_agent_raises() -> None:
    """Unknown agent name raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_system_prompt("nonexistent_agent_xyz")


# ---------------------------------------------------------------------------
# Group 2 — parse_json_response
# ---------------------------------------------------------------------------


def test_parse_json_response_clean_json() -> None:
    """Plain JSON string is parsed into a dict."""
    raw = json.dumps({"key": "value", "count": 3})
    result = parse_json_response(raw)
    assert result == {"key": "value", "count": 3}


def test_parse_json_response_markdown_fence_json() -> None:
    """```json ... ``` fence is unwrapped and parsed."""
    raw = "```json\n" + json.dumps({"domain": "healthcare"}) + "\n```"
    result = parse_json_response(raw)
    assert result == {"domain": "healthcare"}


def test_parse_json_response_plain_fence() -> None:
    """Plain ``` ... ``` fence is unwrapped and parsed."""
    raw = "```\n" + json.dumps({"a": 1}) + "\n```"
    result = parse_json_response(raw)
    assert result == {"a": 1}


def test_parse_json_response_invalid_raises() -> None:
    """Non-JSON text raises ValueError with a descriptive message."""
    with pytest.raises(ValueError, match="Failed to parse model response as JSON"):
        parse_json_response("this is not json at all")


# ---------------------------------------------------------------------------
# Group 3 — build_profiler_message
# ---------------------------------------------------------------------------


@pytest.fixture
def iris_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES_DIR / "iris.csv")


def test_build_profiler_message_structure(iris_df: pd.DataFrame) -> None:
    """Return value is valid JSON with all expected top-level keys."""
    result = build_profiler_message(iris_df, None)
    parsed = json.loads(result)

    assert "row_count" in parsed
    assert "column_count" in parsed
    assert "columns_included" in parsed
    assert "first_5_rows" in parsed
    assert "column_info" in parsed
    assert "computed_column_stats" in parsed


def test_build_profiler_message_row_and_column_counts(iris_df: pd.DataFrame) -> None:
    """row_count and column_count match actual DataFrame dimensions."""
    result = build_profiler_message(iris_df, None)
    parsed = json.loads(result)

    assert parsed["row_count"] == len(iris_df)
    assert parsed["column_count"] == len(iris_df.columns)


def test_build_profiler_message_no_context(iris_df: pd.DataFrame) -> None:
    """When context=None, user_context key is absent from output."""
    result = build_profiler_message(iris_df, None)
    parsed = json.loads(result)

    assert "user_context" not in parsed


def test_build_profiler_message_with_context(iris_df: pd.DataFrame) -> None:
    """When context is provided, user_context appears with the correct value."""
    result = build_profiler_message(iris_df, "test context string")
    parsed = json.loads(result)

    assert "user_context" in parsed
    assert parsed["user_context"] == "test context string"


def test_build_profiler_message_categorical_sample_shows_every_category(
    iris_df: pd.DataFrame,
) -> None:
    """iris.csv is grouped by species — sample_values must show all 3, not the first block."""
    parsed = json.loads(build_profiler_message(iris_df, None))

    assert parsed["column_info"]["species"]["sample_values"] == [
        "setosa",
        "versicolor",
        "virginica",
    ]


def test_build_profiler_message_numeric_sample_not_limited_to_leading_rows(
    iris_df: pd.DataFrame,
) -> None:
    """Numeric sample_values are drawn from the whole column, not the first species block."""
    parsed = json.loads(build_profiler_message(iris_df, None))
    sample = parsed["column_info"]["sepal_length"]["sample_values"]
    first_block = {"5.1", "4.9", "4.7", "4.6", "5.0"}

    assert len(sample) == 5
    assert not set(sample) <= first_block


def test_build_profiler_message_numeric_sample_is_deterministic(
    iris_df: pd.DataFrame,
) -> None:
    """Repeated calls produce identical numeric sample_values (random_state is pinned)."""
    first = json.loads(build_profiler_message(iris_df, None))
    second = json.loads(build_profiler_message(iris_df, None))

    assert (
        first["column_info"]["sepal_length"]["sample_values"]
        == second["column_info"]["sepal_length"]["sample_values"]
    )


def test_build_profiler_message_small_numeric_column_does_not_raise() -> None:
    """A numeric column with fewer than 5 non-null values is sampled without error."""
    df = pd.DataFrame({"value": [1.0, 2.0, np.nan]})
    parsed = json.loads(build_profiler_message(df, None))

    assert sorted(parsed["column_info"]["value"]["sample_values"]) == ["1.0", "2.0"]


def test_build_profiler_message_includes_full_column_stats(iris_df: pd.DataFrame) -> None:
    """computed_column_stats is its own top-level key, computed over every row."""
    parsed = json.loads(build_profiler_message(iris_df, None))

    assert parsed["computed_column_stats"]["species"]["unique_count"] == 3
    assert "unique_count" not in parsed["column_info"]["species"]


# ---------------------------------------------------------------------------
# Group 4 — 50-column truncation
# ---------------------------------------------------------------------------


def test_build_profiler_message_truncates_at_50_columns() -> None:
    """Datasets wider than 50 columns: columns_included=50, columns_note present."""
    wide_df = pd.DataFrame(np.zeros((5, 55)), columns=[f"col_{i}" for i in range(55)])
    result = build_profiler_message(wide_df, None)
    parsed = json.loads(result)

    assert parsed["column_count"] == 55
    assert parsed["columns_included"] == 50
    assert "columns_note" in parsed


# ---------------------------------------------------------------------------
# Group 5 — profiler_node integration (skipped — requires live API + Supabase)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_profiler_node_happy_path() -> None:
    pass


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_profiler_node_domain_pause() -> None:
    pass


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY and Supabase")
def test_profiler_node_missing_file_raises() -> None:
    pass


# ---------------------------------------------------------------------------
# Group 6 — compute_column_stats
# ---------------------------------------------------------------------------


def test_compute_column_stats_counts_every_category(iris_df: pd.DataFrame) -> None:
    """unique_count reflects the full column: iris.csv has 3 species, not 1."""
    stats = compute_column_stats(iris_df, iris_df.columns.tolist())

    assert stats["species"]["unique_count"] == 3


def test_compute_column_stats_numeric_matches_full_column(iris_df: pd.DataFrame) -> None:
    """mean/std/min/max are computed over every row, not a leading sample."""
    stats = compute_column_stats(iris_df, iris_df.columns.tolist())["sepal_length"]
    full = iris_df["sepal_length"]

    assert stats["mean"] == pytest.approx(full.mean())
    assert stats["std"] == pytest.approx(full.std())
    assert stats["min_value"] == pytest.approx(full.min())
    assert stats["max_value"] == pytest.approx(full.max())


def test_compute_column_stats_non_numeric_fields_are_none(iris_df: pd.DataFrame) -> None:
    """A text column gets unique_count only; every numeric field is None."""
    stats = compute_column_stats(iris_df, ["species"])

    assert stats["species"] == {
        "unique_count": 3,
        "mean": None,
        "std": None,
        "min_value": None,
        "max_value": None,
        "outlier_count": None,
        "outlier_pct": None,
    }


def test_compute_column_stats_counts_iqr_outliers_on_both_sides() -> None:
    """IQR bounds flag values below Q1 - 1.5*IQR and above Q3 + 1.5*IQR."""
    df = pd.DataFrame({"value": [-50.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 100.0]})
    stats = compute_column_stats(df, ["value"])["value"]

    # Q1=2.25, Q3=6.75, IQR=4.5 -> bounds [-4.5, 13.5]: -50 and 100 are outliers.
    assert stats["outlier_count"] == 2
    assert stats["outlier_pct"] == pytest.approx(20.0)


def test_compute_column_stats_small_column_has_no_outlier_stats() -> None:
    """Fewer than 5 values is too few for a reliable IQR — outlier fields are None."""
    df = pd.DataFrame({"value": [1.0, 2.0, np.nan]})
    stats = compute_column_stats(df, ["value"])["value"]

    assert stats["mean"] == pytest.approx(1.5)
    assert stats["outlier_count"] is None
    assert stats["outlier_pct"] is None


def test_compute_column_stats_all_nan_column_returns_none() -> None:
    """An all-NaN numeric column yields None for every stat — never NaN."""
    df = pd.DataFrame({"value": [np.nan, np.nan, np.nan]})
    stats = compute_column_stats(df, ["value"])

    assert stats["value"] == {
        "unique_count": 0,
        "mean": None,
        "std": None,
        "min_value": None,
        "max_value": None,
        "outlier_count": None,
        "outlier_pct": None,
    }


def test_compute_column_stats_bool_column_is_non_numeric() -> None:
    """True/False columns are categorical — no numeric stats and no quantile crash."""
    df = pd.DataFrame({"flag": [True, False, True, True, False, True]})
    stats = compute_column_stats(df, ["flag"])

    assert stats["flag"] == {
        "unique_count": 2,
        "mean": None,
        "std": None,
        "min_value": None,
        "max_value": None,
        "outlier_count": None,
        "outlier_pct": None,
    }


# ---------------------------------------------------------------------------
# Group 7 — apply_computed_column_stats
# ---------------------------------------------------------------------------


def _bad_iris_profile_report() -> dict:
    """ProfileReport as the LLM emitted it in the bad run — stats read off the leading
    setosa block — plus deliberately wrong dtype/missing_count values."""
    return {
        "domain_hypothesis": "Botany — iris flower measurements",
        "column_profiles": [
            {
                "column_name": "sepal_length",
                "dtype": "int64",
                "missing_count": 3,
                "missing_pct": 20.0,
                "unique_count": 5,
                "sample_values": ["5.1", "4.9", "4.7", "4.6", "5.0"],
                "is_numeric": True,
                "is_categorical": False,
                "is_datetime": False,
                "outlier_count": 2,
                "outlier_pct": 13.33,
                "min_value": 4.7,
                "max_value": 5.1,
                "mean": 4.86,
                "std": 0.19,
            },
            {
                "column_name": "species",
                "dtype": "category",
                "missing_count": 1,
                "missing_pct": 6.67,
                "unique_count": 1,
                "sample_values": ["setosa"],
                "is_numeric": False,
                "is_categorical": True,
                "is_datetime": False,
                "outlier_count": 0,
                "outlier_pct": None,
                "min_value": "setosa",
                "max_value": "setosa",
                "mean": 1.0,
                "std": None,
            },
        ],
    }


def test_apply_computed_column_stats_overwrites_llm_copied_fields(
    iris_df: pd.DataFrame,
) -> None:
    """Python's full-column values replace the LLM's copies; model-owned fields are kept."""
    message_inputs = json.loads(build_profiler_message(iris_df, None))
    report = _bad_iris_profile_report()

    apply_computed_column_stats(
        report, message_inputs["computed_column_stats"], message_inputs["column_info"]
    )

    sepal, species = report["column_profiles"]
    assert sepal["mean"] == pytest.approx(5.906666666666666)
    assert sepal["std"] == pytest.approx(0.8737984948051866)
    assert sepal["min_value"] == pytest.approx(4.6)
    assert sepal["max_value"] == pytest.approx(7.1)
    assert sepal["unique_count"] == 13
    assert sepal["outlier_count"] == 0
    assert sepal["outlier_pct"] == 0.0
    assert sepal["sample_values"] == ["6.5", "5.8", "5.1", "6.3", "7.0"]
    assert sepal["dtype"] == "float64"
    assert sepal["missing_count"] == 0

    assert species["unique_count"] == 3
    assert species["min_value"] is None
    assert species["max_value"] is None
    assert species["mean"] is None
    assert species["outlier_count"] is None
    assert species["sample_values"] == ["setosa", "versicolor", "virginica"]
    assert species["dtype"] == "object"
    assert species["missing_count"] == 0

    # missing_pct has no Python-computed counterpart, so it stays as the LLM emitted it.
    emitted = _bad_iris_profile_report()
    model_owned = ("column_name", "is_categorical", "is_numeric", "is_datetime", "missing_pct")
    for corrected, original in zip(report["column_profiles"], emitted["column_profiles"]):
        for field in model_owned:
            assert corrected[field] == original[field]
    assert report["domain_hypothesis"] == emitted["domain_hypothesis"]


def test_apply_computed_column_stats_tolerates_malformed_report(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed column_profiles are logged and left alone — never raised."""
    message_inputs = json.loads(
        build_profiler_message(pd.DataFrame({"value": [1.0, 2.0, 3.0]}), None)
    )
    stats = message_inputs["computed_column_stats"]
    info = message_inputs["column_info"]
    caplog.set_level(logging.WARNING, logger="backend.agents.profiler")

    for report in ({}, {"column_profiles": None}, {"column_profiles": {"value": {}}}):
        caplog.clear()
        apply_computed_column_stats(report, stats, info)
        assert caplog.messages == [
            "ProfileReport has no column_profiles list; computed stats not applied"
        ]

    # A non-dict item is skipped without a warning of its own; an unmatched name is warned
    # about and left untouched; the matched entry is still corrected.
    caplog.clear()
    unmatched = {"column_name": "ghost", "mean": 99.0}
    report = {"column_profiles": ["not a dict", unmatched, {"column_name": "value", "mean": 0.0}]}
    apply_computed_column_stats(report, stats, info)
    assert caplog.messages == [
        "column_profiles entry 'ghost' matches no profiled column; left as emitted"
    ]
    assert report["column_profiles"][0] == "not a dict"
    assert unmatched == {"column_name": "ghost", "mean": 99.0}
    assert report["column_profiles"][2]["mean"] == pytest.approx(2.0)

    # With only a non-dict item, the column surfaces solely through the final warning.
    caplog.clear()
    apply_computed_column_stats({"column_profiles": ["not a dict"]}, stats, info)
    assert caplog.messages == ["ProfileReport has no column_profiles entry for: ['value']"]


# ---------------------------------------------------------------------------
# Group 8 — profiler_node with mocked services
# ---------------------------------------------------------------------------


def test_profiler_node_saves_python_computed_column_stats(iris_df: pd.DataFrame) -> None:
    """The profile_report written to Supabase already carries Python's values."""
    captured: list[dict] = []
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(_bad_iris_profile_report()))]
    state = {"analysis_id": "test-analysis-id", "stored_filename": "iris.csv", "context": None}

    with (
        patch("backend.agents.profiler.client") as mock_client,
        patch("backend.agents.profiler.get_supabase_client") as mock_get_supabase_client,
        patch("backend.agents.profiler.create_tracer"),
        patch("backend.agents.profiler.load_dataframe", return_value=iris_df),
    ):
        mock_client.messages.create.return_value = response
        mock_update = mock_get_supabase_client.return_value.table.return_value.update
        # MagicMock records a reference to the payload, and profiler_node mutates it in
        # place — snapshot it at call time so the assertions see what was actually saved.
        mock_update.side_effect = lambda payload: (captured.append(copy.deepcopy(payload)), DEFAULT)[1]
        result = asyncio.run(profiler_node(state))

    assert len(captured) == 3
    saved = [payload for payload in captured if "profile_report" in payload]
    assert len(saved) == 1
    sepal, species = saved[0]["profile_report"]["column_profiles"]
    assert sepal["mean"] == pytest.approx(5.9067, abs=1e-4)
    assert species["unique_count"] == 3
    assert result["profile_report"] == saved[0]["profile_report"]
