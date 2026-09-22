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
import datetime
import io
import json
import logging
import pathlib
from unittest.mock import DEFAULT, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.agents.profiler import (
    DOMAIN_CONFIDENCE_THRESHOLD,
    apply_computed_column_stats,
    apply_confidence_gate,
    apply_domain_resolution,
    build_domain_resolution,
    build_profiler_message,
    compute_column_stats,
    load_dataframe,
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
        "domain_confidence_score": 97,
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


# ---------------------------------------------------------------------------
# Group 9 — bool-dtype (True/False) columns in build_profiler_message
# ---------------------------------------------------------------------------


@pytest.fixture
def imbalanced_bool_df() -> pd.DataFrame:
    return pd.DataFrame({"flag": [False] * 990 + [True] * 10})


def test_build_profiler_message_imbalanced_bool_sample_shows_both_values(
    imbalanced_bool_df: pd.DataFrame,
) -> None:
    """990 False / 10 True — a random sample of 5 is almost always all False."""
    parsed = json.loads(build_profiler_message(imbalanced_bool_df, None))
    assert set(parsed["column_info"]["flag"]["sample_values"]) == {"True", "False"}


def test_build_profiler_message_bool_unique_count_is_two(
    imbalanced_bool_df: pd.DataFrame,
) -> None:
    """The full-column unique_count is unaffected by how sample_values is drawn."""
    parsed = json.loads(build_profiler_message(imbalanced_bool_df, None))
    assert parsed["computed_column_stats"]["flag"]["unique_count"] == 2


def test_build_profiler_message_bool_with_missing_values_uses_distinct_sampling() -> None:
    """True/False with blanks loads from CSV as object dtype and keeps distinct-value sampling."""
    csv = "id,flag\n" + "\n".join(
        f"{i},{'True' if i < 990 else 'False' if i < 1000 else ''}" for i in range(1005)
    )
    df = pd.read_csv(io.StringIO(csv))
    assert df["flag"].dtype == object

    parsed = json.loads(build_profiler_message(df, None))
    assert set(parsed["column_info"]["flag"]["sample_values"]) == {"True", "False"}


# ---------------------------------------------------------------------------
# Group 10 — non-string header labels in load_dataframe
# ---------------------------------------------------------------------------

UPLOADS_DIR = pathlib.Path("backend") / "uploads"

# Excel keeps a date header cell as datetime and a number header cell as int.
# str() of a datetime column label is what parquet also produces, so these are
# the names every downstream agent sees. See errors.md 2026-09-17.
DATE_HEADERS = [datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)]
DATE_HEADER_NAMES = ["2024-01-01 00:00:00", "2024-02-01 00:00:00"]


def _stage_xlsx(path: pathlib.Path, columns: list) -> None:
    frame = pd.DataFrame(
        {index: [index + row + 0.5 for row in range(6)] for index in range(len(columns))}
    )
    frame.columns = pd.Index(columns)
    frame.to_excel(path, index=False)


@pytest.fixture
def staged_upload():
    """Write a file into backend/uploads — where both loaders look — and remove it after."""
    created: list[pathlib.Path] = []

    def _stage(filename: str, writer) -> str:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOADS_DIR / filename
        writer(path)
        created.append(path)
        return filename

    yield _stage

    for path in created:
        path.unlink(missing_ok=True)


def test_load_dataframe_stringifies_uniform_date_headers(staged_upload) -> None:
    """All-date header cells load as a DatetimeIndex; str() must match parquet's form."""
    name = staged_upload(
        "test_profiler_dates.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    df = asyncio.run(load_dataframe(name))

    assert list(df.columns) == DATE_HEADER_NAMES
    assert all(isinstance(column, str) for column in df.columns)


def test_load_dataframe_stringifies_integer_headers(staged_upload) -> None:
    """Year headers load as int labels, which no message builder can key a dict by safely."""
    name = staged_upload(
        "test_profiler_ints.xlsx", lambda path: _stage_xlsx(path, [2021, 2022, 2023])
    )
    df = asyncio.run(load_dataframe(name))

    assert list(df.columns) == ["2021", "2022", "2023"]


def test_load_dataframe_stringifies_mixed_string_and_date_headers(staged_upload) -> None:
    """A label row of `region | 2024-01-01 | 2024-02-01` — the reported failing shape."""
    name = staged_upload(
        "test_profiler_mixed.xlsx",
        lambda path: _stage_xlsx(path, pd.Index(["region", *DATE_HEADERS], dtype=object)),
    )
    df = asyncio.run(load_dataframe(name))

    assert list(df.columns) == ["region", *DATE_HEADER_NAMES]


def test_load_dataframe_leaves_ordinary_xlsx_headers_unchanged(staged_upload) -> None:
    """Normalizing labels must not rewrite names that are already strings."""
    name = staged_upload(
        "test_profiler_plain.xlsx",
        lambda path: _stage_xlsx(path, ["sepal_width", "petal_width"]),
    )
    df = asyncio.run(load_dataframe(name))

    assert list(df.columns) == ["sepal_width", "petal_width"]


def test_load_dataframe_leaves_csv_headers_unchanged(staged_upload) -> None:
    """CSV headers are always parsed as strings — the CSV path must be a no-op."""
    name = staged_upload(
        "test_profiler_headers.csv",
        lambda path: path.write_text("2021,region\n1.0,north\n2.0,south\n"),
    )
    df = asyncio.run(load_dataframe(name))

    assert list(df.columns) == ["2021", "region"]


def test_load_dataframe_preserves_row_values_and_dtypes(staged_upload) -> None:
    """Only the labels are normalized — the data itself is untouched."""
    name = staged_upload(
        "test_profiler_values.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    df = asyncio.run(load_dataframe(name))

    assert len(df) == 6
    assert df[DATE_HEADER_NAMES[0]].tolist() == [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
    assert all(str(dtype) == "float64" for dtype in df.dtypes)


def test_build_profiler_message_succeeds_on_date_header_upload(staged_upload) -> None:
    """The regression: json.dumps raised TypeError on datetime dict keys."""
    name = staged_upload(
        "test_profiler_message.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    df = asyncio.run(load_dataframe(name))

    parsed = json.loads(build_profiler_message(df, None))

    assert list(parsed["column_info"].keys()) == DATE_HEADER_NAMES
    assert list(parsed["computed_column_stats"].keys()) == DATE_HEADER_NAMES


# ---------------------------------------------------------------------------
# Group 11 — consuming a domain-pause answer (Build F1)
# ---------------------------------------------------------------------------

AMBIGUOUS_PAUSE = {
    "type": "domain_confirmation_required",
    "domain_hypothesis": "operational performance tracking",
    "domain_confidence_score": 41,
    "supporting_signals": ["generic metric columns x1-x3", "period index 1-8"],
    "options": [
        {"id": "confirm", "label": "Yes. Proceed.", "action": "proceed_with_hypothesis"},
        {"id": "correct", "label": "No.", "action": "request_user_specified_domain"},
    ],
}
CONFIRM = {"pause_type": "domain_pause", "option_id": "confirm"}
CORRECT = {
    "pause_type": "domain_pause",
    "option_id": "correct",
    "corrected_domain": "  school classroom assessment records  ",
}
# Every ProfileReport key the Cleaner, Analyzer or Explainer reads (errors.md / decisions.md F1).
DOWNSTREAM_KEYS = (
    "domain_hypothesis",
    "domain_supporting_signals",
    "domain_confidence_score",
    "provenance_hypothesis",
    "provenance_supporting_signals",
    "top_3_concerns",
    "top_3_patterns",
)


@pytest.fixture
def ambiguous_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURES_DIR / "ambiguous_domain.csv")


def _ambiguous_profile_report(domain: str, score: int) -> dict:
    """A full ProfileReport as the LLM might emit it on the resume call."""
    return {
        "column_profiles": [
            {"column_name": name}
            for name in ["ref", "period", "grp", "x1", "x2", "x3", "cat"]
        ],
        "duplicate_row_count": 0,
        "data_quality_score": 0.97,
        "domain_hypothesis": domain,
        "domain_supporting_signals": ["period index"],
        "domain_confidence_score": score,
        "provenance_hypothesis": "system export",
        "provenance_supporting_signals": ["consistent R### identifiers"],
        "semantically_categorical_columns": [],
        "co_emptiness_patterns": [],
        "co_completeness_patterns": [],
        "default_value_frequencies": [],
        "potential_merge_artifacts": [],
        "capability_assessment": {
            "can_reliably_answer": [],
            "can_partially_answer": [],
            "cannot_answer": [],
            "user_question_classification": None,
        },
        "top_3_concerns": [{"issue": "c", "affected_columns": ["x1"], "why_it_matters": "w"}] * 3,
        "top_3_patterns": [{"what_was_noticed": "p", "why_its_interesting": "i"}] * 3,
    }


def _run_profiler_node(df: pd.DataFrame, state: dict, llm_payload: dict) -> tuple:
    """Run profiler_node with every service mocked; return (result, saved payloads, llm mock)."""
    captured: list[dict] = []
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(llm_payload))]
    with (
        patch("backend.agents.profiler.client") as mock_client,
        patch("backend.agents.profiler.get_supabase_client") as mock_get_supabase_client,
        patch("backend.agents.profiler.create_tracer"),
        patch("backend.agents.profiler.load_dataframe", return_value=df),
    ):
        mock_client.messages.create.return_value = response
        mock_update = mock_get_supabase_client.return_value.table.return_value.update
        mock_update.side_effect = lambda payload: (captured.append(copy.deepcopy(payload)), DEFAULT)[1]
        try:
            result = asyncio.run(profiler_node(state))
        except Exception as exc:  # returned so the caller can also inspect what was written
            result = exc
    return result, captured, mock_client.messages.create


def _resume_state(response: dict) -> dict:
    return {
        "analysis_id": "test-analysis-id",
        "stored_filename": "ambiguous_domain.csv",
        "context": None,
        "domain_pause_data": None,
        "answered_domain_pause": copy.deepcopy(AMBIGUOUS_PAUSE),
        "user_pause_response": response,
    }


def test_build_profiler_message_without_resolution_is_unchanged(ambiguous_df: pd.DataFrame) -> None:
    """No resume: exactly the pre-F1 key set, and identical to passing None explicitly."""
    default = build_profiler_message(ambiguous_df, None)
    assert set(json.loads(default)) == {
        "row_count", "column_count", "columns_included",
        "first_5_rows", "column_info", "computed_column_stats",
    }
    assert build_profiler_message(ambiguous_df, None, None) == default


def test_build_profiler_message_with_resolution_adds_only_that_key(ambiguous_df: pd.DataFrame) -> None:
    resolution = build_domain_resolution(AMBIGUOUS_PAUSE, CONFIRM)
    plain = json.loads(build_profiler_message(ambiguous_df, "ctx"))
    resumed = json.loads(build_profiler_message(ambiguous_df, "ctx", resolution))
    assert resumed.pop("domain_resolution") == resolution
    assert resumed == plain


def test_build_domain_resolution_returns_none_when_not_resuming() -> None:
    assert build_domain_resolution(AMBIGUOUS_PAUSE, None) is None
    assert build_domain_resolution(
        AMBIGUOUS_PAUSE, {"pause_type": "missing_value_pause", "option_id": "impute"}
    ) is None


def test_build_domain_resolution_confirm_uses_original_hypothesis() -> None:
    assert build_domain_resolution(AMBIGUOUS_PAUSE, CONFIRM) == {
        "source": "user_confirmed",
        "domain": "operational performance tracking",
        "original_hypothesis": "operational performance tracking",
        "original_confidence_score": 41,
        "original_supporting_signals": AMBIGUOUS_PAUSE["supporting_signals"],
    }


def test_build_domain_resolution_correct_uses_stripped_correction() -> None:
    resolution = build_domain_resolution(AMBIGUOUS_PAUSE, CORRECT)
    assert resolution["source"] == "user_corrected"
    assert resolution["domain"] == "school classroom assessment records"
    assert resolution["original_hypothesis"] == "operational performance tracking"


@pytest.mark.parametrize(
    "pause_data, response, match",
    [
        (None, CONFIRM, "no domain_hypothesis"),
        ({**AMBIGUOUS_PAUSE, "domain_hypothesis": "  "}, CONFIRM, "no domain_hypothesis"),
        (AMBIGUOUS_PAUSE, {**CORRECT, "corrected_domain": "   "}, "empty corrected_domain"),
        (AMBIGUOUS_PAUSE, {"pause_type": "domain_pause", "option_id": "correct"}, "empty corrected_domain"),
        (AMBIGUOUS_PAUSE, {"pause_type": "domain_pause", "option_id": "maybe"}, "Unrecognized"),
        (AMBIGUOUS_PAUSE, {"pause_type": "domain_pause"}, "Unrecognized"),
    ],
    ids=["confirm-no-question", "confirm-blank-hypothesis", "correct-blank",
         "correct-missing", "unknown-option", "missing-option"],
)
def test_build_domain_resolution_rejects_unusable_answers(pause_data, response, match) -> None:
    with pytest.raises(ValueError, match=match):
        build_domain_resolution(pause_data, response)


def test_apply_domain_resolution_confirm_restores_original_score() -> None:
    report = _ambiguous_profile_report("something the model drifted to", 88)
    resolution = build_domain_resolution(AMBIGUOUS_PAUSE, CONFIRM)
    apply_domain_resolution(report, resolution)
    assert report["domain_hypothesis"] == "operational performance tracking"
    assert report["domain_confidence_score"] == 41
    assert report["domain_resolution"] == resolution


def test_apply_domain_resolution_correct_keeps_model_evidence_score() -> None:
    report = _ambiguous_profile_report("school classroom assessment", 57)
    resolution = build_domain_resolution(AMBIGUOUS_PAUSE, CORRECT)
    apply_domain_resolution(report, resolution)
    assert report["domain_hypothesis"] == "school classroom assessment records"
    assert report["domain_confidence_score"] == 57
    assert report["domain_resolution"] == resolution


@pytest.mark.parametrize(
    "answer, expected_domain, expected_score",
    [
        (CONFIRM, "operational performance tracking", 41),
        (CORRECT, "school classroom assessment records", 57),
    ],
    ids=["confirm", "correct"],
)
def test_profiler_node_resume_saves_settled_domain_with_provenance(
    ambiguous_df: pd.DataFrame, answer: dict, expected_domain: str, expected_score: int
) -> None:
    """A resume sends the resolution, never re-pauses, and saves a complete profile."""
    llm_output = _ambiguous_profile_report("model drifted domain", 57)
    result, captured, create = _run_profiler_node(ambiguous_df, _resume_state(answer), llm_output)

    sent = json.loads(create.call_args.kwargs["messages"][0]["content"])
    assert sent["domain_resolution"]["domain"] == expected_domain

    saved = [payload["profile_report"] for payload in captured if "profile_report" in payload]
    assert len(saved) == 1
    report = saved[0]
    for key in DOWNSTREAM_KEYS:
        assert report.get(key) is not None, key
    assert report["domain_hypothesis"] == expected_domain
    assert report["domain_confidence_score"] == expected_score
    assert report["domain_resolution"]["domain"] == expected_domain

    assert result["profile_report"] == report
    assert result["domain_pause_data"] is None
    assert result["profiler_domain_hypothesis"] == expected_domain
    assert result["profiler_provenance_hypothesis"] == "system export"
    assert result["profiler_top_3_concerns"] and result["profiler_top_3_patterns"]


def test_profiler_node_resume_that_repauses_raises_instead_of_looping(ambiguous_df: pd.DataFrame) -> None:
    state = _resume_state(CORRECT)
    result, captured, _ = _run_profiler_node(ambiguous_df, state, AMBIGUOUS_PAUSE)

    assert isinstance(result, ValueError)
    assert "again after the user answered" in str(result)
    assert not any("profile_report" in payload for payload in captured)
    assert captured[-1]["status"] == "error"
    assert captured[-1]["error_message"].startswith("SYSTEM_ERROR: Profiler asked")
    assert state["domain_pause_data"] is None


def test_profiler_node_first_run_pause_is_unchanged(ambiguous_df: pd.DataFrame) -> None:
    state = {"analysis_id": "test-analysis-id", "stored_filename": "ambiguous_domain.csv", "context": None}
    result, captured, create = _run_profiler_node(ambiguous_df, state, AMBIGUOUS_PAUSE)

    assert "domain_resolution" not in json.loads(create.call_args.kwargs["messages"][0]["content"])
    assert result["domain_pause_data"] == AMBIGUOUS_PAUSE
    assert result["domain_confirmed"] is False
    assert not any("profile_report" in payload for payload in captured)


def test_profiler_node_without_pause_saves_no_domain_resolution(ambiguous_df: pd.DataFrame) -> None:
    """Stored-shape stability: a run that never paused carries no new key."""
    state = {"analysis_id": "test-analysis-id", "stored_filename": "ambiguous_domain.csv", "context": None}
    llm_output = _ambiguous_profile_report("education", 91)
    result, captured, _ = _run_profiler_node(ambiguous_df, state, llm_output)

    saved = [payload["profile_report"] for payload in captured if "profile_report" in payload]
    assert len(saved) == 1
    assert "domain_resolution" not in saved[0]
    assert saved[0]["domain_hypothesis"] == "education"
    assert saved[0]["domain_confidence_score"] == 91


# ---------------------------------------------------------------------------
# Group 12 — the <80 domain-confidence gate enforced in Python (Build F2)
# ---------------------------------------------------------------------------

FIRST_RUN_STATE = {"analysis_id": "test-analysis-id", "stored_filename": "ambiguous_domain.csv", "context": None}


def _first_run_state() -> dict:
    return copy.deepcopy(FIRST_RUN_STATE)


def test_apply_confidence_gate_converts_sub_80_report_to_standard_pause() -> None:
    report = _ambiguous_profile_report("operational performance tracking", 35)
    report["domain_supporting_signals"] = ["period index 1-8", "generic metric columns"]

    pause = apply_confidence_gate(report)

    assert pause == {
        "type": "domain_confirmation_required",
        "domain_hypothesis": "operational performance tracking",
        "domain_confidence_score": 35,
        "supporting_signals": ["period index 1-8", "generic metric columns"],
        "options": [
            {
                "id": "confirm",
                "label": "Yes, this is operational performance tracking. Proceed.",
                "action": "proceed_with_hypothesis",
            },
            {
                "id": "correct",
                "label": "No, the correct domain is something else.",
                "action": "request_user_specified_domain",
            },
        ],
    }
    # The synthesized pause is a valid question for F1's resume path.
    assert build_domain_resolution(pause, CONFIRM)["domain"] == "operational performance tracking"


@pytest.mark.parametrize(
    "score, pauses",
    [(80, False), (91, False), (79, True), (79.5, True), (0, True)],
    ids=["80-proceeds", "91-proceeds", "79-pauses", "79.5-pauses", "0-pauses"],
)
def test_apply_confidence_gate_threshold_boundary(score, pauses: bool) -> None:
    report = _ambiguous_profile_report("education", score)
    result = apply_confidence_gate(report)
    if pauses:
        assert result["type"] == "domain_confirmation_required"
        assert result["domain_confidence_score"] == score
    else:
        assert result is report
        assert result == _ambiguous_profile_report("education", score)
    assert DOMAIN_CONFIDENCE_THRESHOLD == 80


def test_apply_confidence_gate_passes_model_emitted_pause_through_untouched() -> None:
    pause = copy.deepcopy(AMBIGUOUS_PAUSE)
    assert apply_confidence_gate(pause) is pause
    assert pause == AMBIGUOUS_PAUSE


def test_apply_confidence_gate_missing_signals_become_empty_list() -> None:
    report = _ambiguous_profile_report("education", 35)
    del report["domain_supporting_signals"]
    assert apply_confidence_gate(report)["supporting_signals"] == []


@pytest.mark.parametrize(
    "score",
    ["missing", None, True, "35", float("nan"), float("inf")],
    ids=["missing", "none", "bool", "string", "nan", "inf"],
)
def test_apply_confidence_gate_rejects_unusable_score(score) -> None:
    report = _ambiguous_profile_report("education", 35)
    if score == "missing":
        del report["domain_confidence_score"]
    else:
        report["domain_confidence_score"] = score
    with pytest.raises(ValueError, match="no usable domain_confidence_score"):
        apply_confidence_gate(report)


@pytest.mark.parametrize("hypothesis", ["", "   ", None], ids=["empty", "blank", "none"])
def test_apply_confidence_gate_rejects_sub_80_report_with_no_hypothesis(hypothesis) -> None:
    report = _ambiguous_profile_report("education", 35)
    report["domain_hypothesis"] = hypothesis
    with pytest.raises(ValueError, match="no domain_hypothesis to confirm"):
        apply_confidence_gate(report)


def test_profiler_node_first_run_sub_80_report_pauses_without_saving_a_profile(
    ambiguous_df: pd.DataFrame,
) -> None:
    llm_output = _ambiguous_profile_report("operational performance tracking", 35)
    result, captured, _ = _run_profiler_node(ambiguous_df, _first_run_state(), llm_output)

    assert result["domain_pause_data"] == apply_confidence_gate(
        _ambiguous_profile_report("operational performance tracking", 35)
    )
    assert result["domain_confirmed"] is False
    assert result.get("profile_report") is None
    assert not any("profile_report" in payload for payload in captured)


def test_profiler_node_first_run_unusable_score_is_system_error(ambiguous_df: pd.DataFrame) -> None:
    llm_output = _ambiguous_profile_report("education", 35)
    del llm_output["domain_confidence_score"]
    result, captured, _ = _run_profiler_node(ambiguous_df, _first_run_state(), llm_output)

    assert isinstance(result, ValueError)
    assert not any("profile_report" in payload for payload in captured)
    assert captured[-1]["status"] == "error"
    assert captured[-1]["error_message"].startswith("SYSTEM_ERROR: ProfileReport has no usable")


@pytest.mark.parametrize("answer", [CONFIRM, CORRECT], ids=["confirm", "correct"])
def test_profiler_node_resume_at_35_saves_profile_and_never_regates(
    ambiguous_df: pd.DataFrame, answer: dict
) -> None:
    """Core expected behavior, not an edge case: a settled domain keeps a low score."""
    state = _resume_state(answer)
    state["answered_domain_pause"]["domain_confidence_score"] = 35
    llm_output = _ambiguous_profile_report("model drifted domain", 35)
    result, captured, _ = _run_profiler_node(ambiguous_df, state, llm_output)

    assert not isinstance(result, Exception), result
    saved = [payload["profile_report"] for payload in captured if "profile_report" in payload]
    assert len(saved) == 1
    assert saved[0]["domain_confidence_score"] == 35
    assert result["domain_pause_data"] is None
    assert result["domain_confirmed"] is True


def test_profiler_node_unknown_domain_pauses_then_confirm_settles_unknown(ambiguous_df: pd.DataFrame) -> None:
    """Option (i): 'unknown' goes through the same confirm/correct mechanism, text unchanged."""
    first, _, _ = _run_profiler_node(ambiguous_df, _first_run_state(), _ambiguous_profile_report("unknown", 35))
    pause = first["domain_pause_data"]
    assert pause["domain_hypothesis"] == "unknown"
    assert pause["domain_confidence_score"] == 35
    assert [option["id"] for option in pause["options"]] == ["confirm", "correct"]

    state = {**_first_run_state(), "domain_pause_data": None,
             "answered_domain_pause": pause, "user_pause_response": CONFIRM}
    resumed, captured, create = _run_profiler_node(ambiguous_df, state, _ambiguous_profile_report("unknown", 30))

    assert json.loads(create.call_args.kwargs["messages"][0]["content"])["domain_resolution"]["domain"] == "unknown"
    saved = [payload["profile_report"] for payload in captured if "profile_report" in payload]
    assert len(saved) == 1
    assert saved[0]["domain_hypothesis"] == "unknown"
    assert saved[0]["domain_confidence_score"] == 35
    assert saved[0]["domain_resolution"]["source"] == "user_confirmed"
    assert saved[0]["domain_resolution"]["original_confidence_score"] == 35
    assert resumed["domain_pause_data"] is None


def test_apply_domain_resolution_confirm_restores_a_decimal_pause_score() -> None:
    """Code Review (Build F2): the gate accepts 79.5, so confirm must keep 79.5, never the resume score."""
    pause = apply_confidence_gate(_ambiguous_profile_report("education", 79.5))
    report = _ambiguous_profile_report("education", 92)
    apply_domain_resolution(report, build_domain_resolution(pause, CONFIRM))
    assert report["domain_confidence_score"] == 79.5
