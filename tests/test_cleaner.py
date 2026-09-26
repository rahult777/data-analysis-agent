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
import datetime
import io
import json
import pathlib
from unittest.mock import DEFAULT, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from backend.agents.cleaner import (
    _OUTLIER_DOMAIN_SENTENCE,
    _OUTLIER_LABELS,
    _outlier_facts,
    _iqr_outlier_mask,
    _outlier_review_columns,
    _same_value,
    analyze_missingness_patterns,
    apply_missingness_backstop,
    apply_outlier_backstop,
    apply_user_decisions,
    build_cleaner_message,
    _MODEL_PHASES_AFTER_USER,
    _MODEL_PHASES_BEFORE_USER,
    _distinct_value_columns,
    build_cleaner_resolutions,
    build_contract_record,
    build_model_records,
    cleaner_node,
    detect_interactions,
    filter_user_decided,
    plan_model_decisions,
    re_profile_dataframe,
    remove_duplicate_rows,
    run_model_operations,
    load_dataframe_from_uploads,
    normalize_outlier_review,
    validate_cleaner_pause,
)
from backend.agents.profiler import load_dataframe
from backend.models.schemas import AnalysisResponse, CleaningDecision, CleaningReport

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
        resolved_pauses=None,
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
        resolved_pauses=None,
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
        resolved_pauses=None,
        missingness_patterns=messy_missingness_patterns,
    )
    parsed = json.loads(result)
    col_info = parsed["column_info"]
    assert abs(col_info["revenue"]["missing_pct"] - 35.0) < 2
    assert abs(col_info["notes"]["missing_pct"] - 45.5) < 2


def test_build_cleaner_message_with_resolved_pauses(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    """Every resolved pause, and the domain resolution, appear in the message when provided."""
    resolved = [
        {"pause_type": "missing_value_pause", "column_name": "revenue", "option_id": "impute", "chosen_option": {"id": "impute"}},
        {"pause_type": "missing_value_pause", "column_name": "notes", "option_id": "exclude_column", "chosen_option": {"id": "exclude_column"}},
    ]
    resolution = {"source": "user_confirmed", "domain": "retail"}
    result = build_cleaner_message(
        df=messy_df,
        profile_report={},
        domain_hypothesis=None,
        provenance_hypothesis=None,
        top_3_concerns=None,
        resolved_pauses=resolved,
        missingness_patterns=messy_missingness_patterns,
        domain_resolution=resolution,
    )
    parsed = json.loads(result)
    assert parsed["resolved_pauses"] == resolved
    assert parsed["domain_resolution"] == resolution
    assert "user_pause_response" not in parsed


def test_build_cleaner_message_omits_resolution_keys_without_them(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    parsed = json.loads(build_cleaner_message(
        messy_df, {}, None, None, None, [], messy_missingness_patterns
    ))
    assert "resolved_pauses" not in parsed
    assert "domain_resolution" not in parsed
    assert "domain_confidence_score" not in parsed


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
        resolved_pauses=None,
        missingness_patterns=missingness_patterns,
    )
    parsed = json.loads(result)
    assert len(set(parsed["column_info"]["species"]["sample_values"])) == 3


PROFILER_STRUCTURAL = {
    "duplicate_row_count": 0,  # the Profiler's live value on messy_data.csv; 15 are real
    "semantically_categorical_columns": [{"column_name": "customer_id", "reason": "an identifier"}],
    "co_emptiness_patterns": [{"column_group": ["revenue", "units_sold"]}],
    "co_completeness_patterns": [{"column_group": ["customer_id", "product_code"]}],
    "default_value_frequencies": [{"column_name": "region", "suspect_value": "casings"}],
    "potential_merge_artifacts": [],
    "top_3_patterns": [{"what_was_noticed": "p", "why_its_interesting": "q"}],
}


def test_the_message_sends_the_profilers_id_judgment_and_the_systems_own_structure(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    """S6: semantically_categorical_columns (the Profiler's judgment, Step 5), Python's
    duplicate count, and the Cleaner's own full-data analyses; never the Profiler's
    whole-table pattern claims, and never its false duplicate count."""
    interactions = detect_interactions(messy_df, {})
    parsed = json.loads(build_cleaner_message(
        messy_df, PROFILER_STRUCTURAL, None, None, None, None, messy_missingness_patterns,
        interactions=interactions,
    ))
    assert parsed["semantically_categorical_columns"] == PROFILER_STRUCTURAL["semantically_categorical_columns"]
    assert parsed["duplicate_row_count"] == 15
    assert parsed["missingness_patterns"] == messy_missingness_patterns
    assert parsed["interactions_detected"] == json.loads(json.dumps(interactions))
    assert parsed["profile_summary"] == {"top_3_patterns": PROFILER_STRUCTURAL["top_3_patterns"]}
    sent = json.dumps(parsed)
    for field in ("co_emptiness_patterns", "co_completeness_patterns", "default_value_frequencies",
                  "potential_merge_artifacts", "structural_observations"):
        assert field not in sent


def test_the_message_sends_every_value_of_each_low_cardinality_text_column(
    messy_df: pd.DataFrame, messy_missingness_patterns: dict
) -> None:
    parsed = json.loads(build_cleaner_message(
        messy_df, {}, None, None, None, None, messy_missingness_patterns
    ))
    assert parsed["distinct_values"]["region"] == {
        "North": 45, "East": 36, "north": 33, "West": 33, "south": 25, "SOUTH": 24,
    }
    assert set(parsed["distinct_values"]) == {"region", "sales_rep", "return_flag", "notes"}
    assert parsed["semantically_categorical_columns"] == []


def test_a_text_column_with_more_than_30_distinct_values_is_not_sent_in_full() -> None:
    df = pd.DataFrame({"many": [f"v{i}" for i in range(31)], "few": ["a", "b"] * 15 + ["a"]})
    assert set(_distinct_value_columns(df)) == {"few"}
    assert _distinct_value_columns(df.iloc[:30])["many"]["v0"] == 1


# ---------------------------------------------------------------------------
# Group 4 — the Cleaner's operations, run by Python (Build G)
# ---------------------------------------------------------------------------


def _run_ops(df: pd.DataFrame, decisions: list) -> tuple[pd.DataFrame, list, list, dict, list]:
    """Run Cleaner decisions exactly as cleaner_node does when no pause was answered.

    Returns (frame, plan items, records, outliers flagged, discrepancies).
    """
    frame, _, _ = remove_duplicate_rows(df)
    kept, _ = filter_user_decided(decisions, [])
    items = plan_model_decisions(kept, df)
    shown = _distinct_value_columns(df)
    frame = run_model_operations(frame, items, _MODEL_PHASES_BEFORE_USER, df, shown)
    frame = run_model_operations(frame, items, _MODEL_PHASES_AFTER_USER, df, shown)
    records, flagged, discrepancies = build_model_records(items, frame)
    return frame, items, records, flagged, discrepancies


def _op(column, operation, params=None, **text) -> dict:
    return {"column_name": column, "operation": operation, "params": params or {},
            "issue": text.get("issue", "i"), "action": text.get("action", "a"), "reason": text.get("reason", "r")}


def test_fill_missing_median_fills_every_gap() -> None:
    df = pd.DataFrame({"value": [1.0, 2.0, np.nan, 4.0, 5.0]})
    frame, _, [record], _, _ = _run_ops(df, [_op("value", "fill_missing", {"method": "median"})])
    assert frame["value"].isna().sum() == 0 and frame.loc[2, "value"] == 3.0
    assert record["action"] == "Cleaner decision: filled the 1 missing values in `value` with the median (3)"


def test_a_model_request_to_drop_a_column_is_not_executed() -> None:
    """Removing a column is the user's choice (Step 9); the old router ran it."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})
    frame, _, [record], _, _ = _run_ops(df, [_op("b", "drop_column")])
    assert list(frame.columns) == ["a", "b", "c"]
    assert record["action"].startswith("Not executed: 'drop_column' is not an operation the Cleaner can run")


def test_the_system_removes_exact_duplicates_and_records_its_own_count() -> None:
    df = pd.DataFrame({"x": [1, 2, 1, 2, 3], "y": [10, 20, 10, 20, 30]})
    frame, record, entry = remove_duplicate_rows(df)
    assert frame.index.tolist() == [0, 1, 4]
    assert record["column_name"] is None
    assert record["action"] == "System step: removed the 2 exact duplicate rows, keeping the first occurrence of each"
    assert entry["facts"] == {"duplicate_rows": 2, "rows_before": 5, "rows_after": 3}
    _, none_record, _ = remove_duplicate_rows(df.drop_duplicates())
    assert none_record["action"] == "System step: checked for exact duplicate rows and found none; nothing removed"


def test_no_decisions_change_nothing() -> None:
    df = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
    frame, items, records, flagged, discrepancies = _run_ops(df, [])
    pd.testing.assert_frame_equal(frame, df)
    assert (items, records, flagged, discrepancies) == ([], [], {}, [])


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
        resolved_pauses=None,
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


def test_flag_outliers_on_a_bool_column_is_not_executed() -> None:
    """A bool column has no IQR outliers, like any non-numeric column; the record says so."""
    df = _bool_df(20)
    frame, _, [record], flagged, _ = _run_ops(df, [_op("flag", "flag_outliers")])

    assert "flag_outlier_flag" not in frame.columns
    assert flagged == {}
    assert record["action"] == "Not executed: `flag` is not numeric, so it has no IQR outliers. Nothing was changed."


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
    # _bool_df leaves `amount` 35% missing; since Build F3 that correctly
    # triggers the missing-value backstop, so fill two gaps (25%) to keep
    # this test about the bool column reaching the save.
    df = _bool_df(20)
    df.loc[[0, 3], "amount"] = 1.0

    with (
        patch("backend.agents.cleaner.client") as mock_client,
        patch("backend.agents.cleaner.get_supabase_client") as mock_get_supabase_client,
        patch("backend.agents.cleaner.create_tracer"),
        patch("backend.agents.cleaner.load_dataframe_from_uploads", return_value=df),
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
    # Since Build G the system always removes exact duplicates (4 in this frame);
    # before, they were removed only when the model wrote a dataset-level decision.
    assert int(df.duplicated().sum()) == 4
    assert result["cleaning_report"]["summary"]["rows_after"] == 16


# ---------------------------------------------------------------------------
# Group 8 — non-string header labels in load_dataframe_from_uploads
# ---------------------------------------------------------------------------

UPLOADS_DIR = pathlib.Path("backend") / "uploads"

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


def test_load_dataframe_from_uploads_stringifies_uniform_date_headers(staged_upload) -> None:
    """All-date header cells load as a DatetimeIndex; str() must match parquet's form."""
    name = staged_upload(
        "test_cleaner_dates.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    df = asyncio.run(load_dataframe_from_uploads(name))

    assert list(df.columns) == DATE_HEADER_NAMES
    assert all(isinstance(column, str) for column in df.columns)


def test_load_dataframe_from_uploads_stringifies_integer_headers(staged_upload) -> None:
    """The Cleaner loads the original upload independently, so it needs the same fix."""
    name = staged_upload(
        "test_cleaner_ints.xlsx", lambda path: _stage_xlsx(path, [2021, 2022, 2023])
    )
    df = asyncio.run(load_dataframe_from_uploads(name))

    assert list(df.columns) == ["2021", "2022", "2023"]


def test_load_dataframe_from_uploads_stringifies_mixed_headers(staged_upload) -> None:
    """A label row of `region | 2024-01-01 | 2024-02-01` — the reported failing shape."""
    name = staged_upload(
        "test_cleaner_mixed.xlsx",
        lambda path: _stage_xlsx(path, pd.Index(["region", *DATE_HEADERS], dtype=object)),
    )
    df = asyncio.run(load_dataframe_from_uploads(name))

    assert list(df.columns) == ["region", *DATE_HEADER_NAMES]


def test_load_dataframe_from_uploads_leaves_csv_headers_unchanged(staged_upload) -> None:
    """CSV headers are always parsed as strings — the CSV path must be a no-op."""
    name = staged_upload(
        "test_cleaner_headers.csv",
        lambda path: path.write_text("2021,region\n1.0,north\n2.0,south\n"),
    )
    df = asyncio.run(load_dataframe_from_uploads(name))

    assert list(df.columns) == ["2021", "region"]


def test_load_dataframe_from_uploads_preserves_row_values_and_dtypes(staged_upload) -> None:
    """Only the labels are normalized — the data itself is untouched."""
    name = staged_upload(
        "test_cleaner_values.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    df = asyncio.run(load_dataframe_from_uploads(name))

    assert len(df) == 6
    assert df[DATE_HEADER_NAMES[0]].tolist() == [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
    assert all(str(dtype) == "float64" for dtype in df.dtypes)


def test_build_cleaner_message_succeeds_on_date_header_upload(staged_upload) -> None:
    """The regression: json.dumps raised TypeError on datetime dict keys."""
    name = staged_upload(
        "test_cleaner_message.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    df = asyncio.run(load_dataframe_from_uploads(name))

    parsed = json.loads(
        build_cleaner_message(df, {}, None, None, None, None, analyze_missingness_patterns(df))
    )

    assert list(parsed["column_info"].keys()) == DATE_HEADER_NAMES


def test_load_dataframe_from_uploads_still_rejects_unsupported_extension(staged_upload) -> None:
    """The restructured control flow must still raise, not fall through to a stringify."""
    name = staged_upload(
        "test_cleaner_unsupported.txt", lambda path: path.write_text("region\nnorth\n")
    )

    with pytest.raises(ValueError, match="Unsupported file extension"):
        asyncio.run(load_dataframe_from_uploads(name))


# ---------------------------------------------------------------------------
# Group 9 — Profiler/Cleaner/parquet column-name agreement
# ---------------------------------------------------------------------------


def test_both_loaders_agree_with_parquet_on_date_header_names(staged_upload, tmp_path) -> None:
    """The three agents must name the same column identically.

    The Profiler and the Cleaner each load the upload themselves; the Analyzer
    reads the Cleaner's parquet. str() is what pyarrow applies to a non-string
    label, so map(str) — not astype(str), which drops the time component of a
    DatetimeIndex — is what keeps all three in agreement.
    """
    name = staged_upload(
        "test_shared_dates.xlsx", lambda path: _stage_xlsx(path, DATE_HEADERS)
    )
    profiler_df = asyncio.run(load_dataframe(name))
    cleaner_df = asyncio.run(load_dataframe_from_uploads(name))

    parquet_path = tmp_path / "cleaned.parquet"
    cleaner_df.to_parquet(parquet_path, index=False)
    analyzer_df = pd.read_parquet(parquet_path)

    assert list(profiler_df.columns) == list(cleaner_df.columns)
    assert list(analyzer_df.columns) == list(cleaner_df.columns)
    assert list(analyzer_df.columns) == DATE_HEADER_NAMES


# ---------------------------------------------------------------------------
# Group 10 — user pause answers: checked, accumulated, executed by option id
# (Build F3)
# ---------------------------------------------------------------------------

# messy_data.csv: revenue 70/200 missing with IQR outliers at these labels
# (500k-750k); rows 50-64 are exact duplicates of earlier rows.
OUTLIER_ROWS = [5, 25, 75, 150]
FIN_NOTE = (
    "in financial data, extreme values are often legitimate large transactions. "
    "A $750,000 order against a $42,790 mean may be a wholesale order or a misplaced digit."
)
# The old Step 4 decision, which the model no longer writes (the system removes
# duplicates itself). Prose with no operation: never executed, never shown.
LEGACY_DEDUPE = {
    "column_name": None,
    "issue": "0 exact duplicate rows present",
    "action": "no duplicate rows present; no action taken",
    "reason": "the Profiler confirmed zero exact duplicate rows",
}
# Prose-only decisions on user-decided revenue that the pre-Build G keyword
# router misexecuted: mean-fill ("means"), nothing ("Removed"/backticks), a 0
# fill. They name no operation, and the filter drops them.
ADVERSARIAL_REVENUE = [
    {"column_name": "revenue", "issue": "missingness means the sale was never recorded",
     "action": "Exclude rows where revenue is missing", "reason": "r"},
    {"column_name": "revenue", "issue": "70 missing", "action": "Removed the 70 rows where revenue is missing", "reason": "r"},
    {"column_name": "revenue", "issue": "70 missing", "action": "Exclude `revenue` from analysis entirely", "reason": "r"},
    {"column_name": "revenue", "issue": "70 missing", "action": "fill with 0", "reason": "r"},
]
ADVERSARIAL_OUTLIERS = [
    {"column_name": "revenue", "issue": "4 outlier values", "action": "Removed the 4 outlier values pending review", "reason": "r"},
    {"column_name": "revenue", "issue": "outliers", "action": "flag outliers", "reason": "r"},
]


def _messy() -> pd.DataFrame:
    return pd.read_csv(FIXTURES_DIR / "messy_data.csv")


def _mv_question(column: str = "revenue", method_id: str = "median", **overrides) -> dict:
    question = {
        "type": "missing_value_decision_required",
        "column_name": column,
        "missing_pct": 1.0,
        "missing_count": 1,
        "total_rows": 1,
        "what_this_column_represents": f"the {column} column",
        "provenance_interpretation": "in a system export, a null revenue most often means no sale was recorded.",
        "domain_context": "revenue drives every margin comparison in retail data.",
        "options": [
            {"id": "impute", "label": "Impute", "method": method_id, "method_id": method_id,
             "assumption": "missingness is non-informative"},
            {"id": "exclude_column", "label": "Exclude the column", "consequence": "loses the column"},
            {"id": "exclude_rows", "label": "Exclude the rows", "consequence": "loses the rows"},
        ],
    }
    question.update(overrides)
    return question


def _outlier_question(column: str = "revenue", domain: str = "financial", **overrides) -> dict:
    ids = {
        "financial": ["treat_as_valid", "flag_as_suspected_error"],
        "medical": ["include_with_annotation", "exclude_pending_clinical_review"],
    }[domain]
    note_field = {"financial": "financial_context_note", "medical": "clinical_significance_note"}[domain]
    question = {
        "type": "outlier_decision_required",
        "domain_context": domain,
        "column_name": column,
        "outlier_value": 750000,
        "outlier_count": 99,
        "sd_distance": 6.8,
        "column_mean": 42790.7,
        "column_std": 104094.2,
        note_field: FIN_NOTE,
        "options": [{"id": i, "label": i, "consequence": "c"} for i in ids],
    }
    question.update(overrides)
    return question


def _answered(question: dict, option_id: str, df: pd.DataFrame) -> dict:
    """An answered pause exactly as cleaner_pause_wait_node records it: the stored
    (validated) question and the user's answer."""
    pause_type = (
        "missing_value_pause"
        if question["type"] == "missing_value_decision_required"
        else "outlier_pause"
    )
    return {
        "pause_type": pause_type,
        "column_name": question["column_name"],
        "question": validate_cleaner_pause(question, df, []),
        "response": {"pause_type": pause_type, "option_id": option_id, "column_name": question["column_name"]},
    }


def _notes_preserved(df: pd.DataFrame) -> dict:
    return _answered(_mv_question("notes", "mode"), "preserve_missingness", df)


def _report(decisions: list) -> dict:
    return {
        "decisions": decisions,
        "profiler_concerns_addressed": [],
        "summary": {},
        "re_profile_verification": {"passed": True, "discrepancies": []},
    }


def _run_cleaner(
    df: pd.DataFrame,
    llm_payload: dict,
    answered: list | None = None,
    stop_reason: str = "end_turn",
    **state_overrides,
) -> tuple:
    """Run cleaner_node with every external service mocked.

    Returns (result or raised exception, the frame written to parquet or None,
    Supabase update payloads, the LLM create mock).
    """
    saved: dict = {}
    captured: list[dict] = []
    reply = MagicMock()
    reply.content = [MagicMock(text=json.dumps(llm_payload))]
    reply.stop_reason = stop_reason
    state = {
        "analysis_id": "test-analysis-id",
        "stored_filename": "messy.csv",
        "profile_report": {},
        "profiler_domain_hypothesis": "retail",
        "profiler_provenance_hypothesis": "system export",
        "profiler_top_3_concerns": [],
        "answered_cleaner_pauses": answered or [],
        **state_overrides,
    }

    def capture_parquet(frame: pd.DataFrame, *args, **kwargs) -> None:
        saved["df"] = frame.copy()

    with (
        patch("backend.agents.cleaner.client") as mock_client,
        patch("backend.agents.cleaner.get_supabase_client") as mock_get_supabase_client,
        patch("backend.agents.cleaner.create_tracer"),
        patch("backend.agents.cleaner.load_dataframe_from_uploads", return_value=df.copy()),
        patch("backend.agents.cleaner.upload_to_storage"),
        patch("backend.agents.cleaner.cleanup_temp_file"),
        patch.object(pd.DataFrame, "to_parquet", autospec=True, side_effect=capture_parquet),
    ):
        mock_client.messages.create.return_value = reply
        mock_update = mock_get_supabase_client.return_value.table.return_value.update
        mock_update.side_effect = lambda payload: (captured.append(copy.deepcopy(payload)), DEFAULT)[1]
        try:
            outcome = asyncio.run(cleaner_node(state))
        except Exception as exc:
            outcome = exc
    return outcome, saved.get("df"), captured, mock_client.messages.create


def _user_decisions(outcome: dict, column: str) -> list:
    return [
        d for d in outcome["cleaning_report"]["decisions"]
        if d["column_name"] == column and d["action"].startswith("User decision")
    ]


def test_validate_missing_pause_overwrites_counts_and_appends_the_preserve_option() -> None:
    stored = validate_cleaner_pause(_mv_question(), _messy(), [])
    assert (stored["missing_count"], stored["missing_pct"], stored["total_rows"]) == (70, 35.0, 200)
    assert [o["id"] for o in stored["options"]] == [
        "impute", "exclude_column", "exclude_rows", "preserve_missingness",
    ]
    preserve = stored["options"][3]
    assert "its 70 missing values stay missing" in preserve["label"]
    assert "only its 130 recorded values" in preserve["consequence"]
    # The option promises only what the pipeline does (no Analyzer investigation).
    assert "investigat" not in json.dumps(preserve).lower()


def _without_method_id() -> dict:
    question = _mv_question()
    del question["options"][0]["method_id"]
    return question


@pytest.mark.parametrize(
    "make_question, message",
    [
        (lambda: _mv_question(options=list(reversed(_mv_question()["options"]))), "in that order"),
        (lambda: _mv_question(options=_mv_question()["options"] + [{"id": "preserve_missingness"}]), "in that order"),
        (_without_method_id, "method_id"),
        (lambda: _mv_question(method_id="forward-fill"), "method_id"),
        (lambda: _mv_question("notes", "median"), "not numeric"),
        (lambda: _mv_question(provenance_interpretation="  "), "provenance_interpretation"),
        (lambda: _mv_question("no_such_column"), "not in the dataset"),
    ],
)
def test_validate_rejects_a_missing_value_pause_python_could_not_honor(make_question, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_cleaner_pause(make_question(), _messy(), [])


@pytest.mark.parametrize(
    "make_question, message",
    [
        (lambda: _outlier_question(domain_context="retail"), "domain_context"),
        (lambda: _outlier_question(options=list(reversed(_outlier_question()["options"]))), "in that order"),
        (lambda: _outlier_question(financial_context_note=""), "financial_context_note"),
        (lambda: _outlier_question("units_sold"), "no values outside"),
        (lambda: _outlier_question("notes"), "no values outside"),
    ],
)
def test_validate_rejects_an_outlier_pause_python_could_not_honor(make_question, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_cleaner_pause(make_question(), _messy(), [])


def test_validate_outlier_pause_overwrites_the_count_with_pythons() -> None:
    assert validate_cleaner_pause(_outlier_question(), _messy(), [])["outlier_count"] == 4


def test_validate_drops_impute_and_exclude_rows_when_a_column_has_no_recorded_values() -> None:
    """Nothing to impute from, and excluding the missing rows would delete every row."""
    df = pd.DataFrame({"empty": [np.nan] * 6, "other": range(6)})
    stored = validate_cleaner_pause(_mv_question("empty", "mode"), df, [])
    assert [o["id"] for o in stored["options"]] == ["exclude_column", "preserve_missingness"]


def test_validate_rerenders_count_bearing_labels_with_pythons_counts() -> None:
    """The model's labels carry its own counts; the stored question must not contradict itself."""
    wrong = _mv_question()
    wrong["options"][0]["label"] = "Impute the 3 missing values with median"
    wrong["options"][2]["label"] = "Exclude the 3 rows"
    stored = validate_cleaner_pause(wrong, _messy(), [])
    assert stored["options"][0]["label"] == "Impute the 70 missing values with median"
    assert stored["options"][2]["label"] == "Exclude the 70 rows where `revenue` is missing"

    outlier = _outlier_question()
    outlier["options"][1]["label"] = "Flag the 3 outlier value(s)"
    stored = validate_cleaner_pause(outlier, _messy(), [])
    assert stored["options"][0]["label"].startswith("Treat the 4 outlier value(s) as valid data")
    assert stored["options"][1]["label"].startswith("Flag the 4 outlier value(s) as suspected data entry error")


def test_repeat_pause_on_an_answered_key_raises_but_new_keys_pass() -> None:
    df = _messy()
    answered = [_answered(_mv_question(), "impute", df)]
    with pytest.raises(ValueError, match="asked again"):
        validate_cleaner_pause(_mv_question(), df, answered)
    # A different column, and a different pause type on the same column, are new questions.
    validate_cleaner_pause(_mv_question("notes", "mode"), df, answered)
    validate_cleaner_pause(_outlier_question(), df, answered)


def test_pause_on_a_column_the_user_excluded_raises() -> None:
    df = _messy()
    answered = [_answered(_mv_question(), "exclude_column", df)]
    with pytest.raises(ValueError, match="already excluded"):
        validate_cleaner_pause(_outlier_question(), df, answered)


def test_backstop_turns_a_report_that_skipped_a_mandatory_pause_into_that_pause() -> None:
    df = _messy()
    pause = apply_missingness_backstop(_report([]), df, [], "retail", "system export")
    assert pause["type"] == "missing_value_decision_required"
    assert pause["column_name"] == "revenue"
    assert pause["options"][0]["method_id"] == "median"
    assert pause["options"][0]["method"] == f"median ({df['revenue'].median():.6g})"
    assert "Not assessed" in pause["provenance_interpretation"]
    assert "'system export'" in pause["provenance_interpretation"]
    assert "'retail'" in pause["domain_context"]
    stored = validate_cleaner_pause(pause, df, [])
    assert [o["id"] for o in stored["options"]][-1] == "preserve_missingness"


def test_backstop_moves_on_to_the_next_unanswered_column() -> None:
    df = _messy()
    answered = [_answered(_mv_question(), "impute", df)]
    pause = apply_missingness_backstop(_report([]), df, answered, "retail", "system export")
    assert pause["column_name"] == "notes"
    assert pause["options"][0]["method_id"] == "mode"
    validate_cleaner_pause(pause, df, answered)


def test_backstop_passes_a_report_once_every_column_over_30_is_answered() -> None:
    df = _messy()
    answered = [
        _answered(_mv_question(), "impute", df),
        _answered(_mv_question("notes", "mode"), "preserve_missingness", df),
    ]
    report = _report([])
    assert apply_missingness_backstop(report, df, answered, "retail", "system export") is report


def test_backstop_passes_a_model_pause_untouched() -> None:
    pause = _outlier_question()
    assert apply_missingness_backstop(pause, _messy(), [], "retail", "system export") is pause


@pytest.mark.parametrize(
    "question",
    [None, {"options": []}, {"options": [{"id": "impute"}, {"id": "exclude_rows"}]}],
)
def test_an_answer_the_question_did_not_offer_raises(question) -> None:
    """Reachable only through /resume's escape hatch: fail loudly, never skip."""
    entry = {
        "pause_type": "missing_value_pause",
        "column_name": "revenue",
        "question": question,
        "response": {"option_id": "keep_as_is"},
    }
    with pytest.raises(ValueError, match="did not offer"):
        build_cleaner_resolutions([entry])


def test_cleaner_node_rejects_an_unusable_answer_before_calling_the_model() -> None:
    entry = {
        "pause_type": "missing_value_pause",
        "column_name": "revenue",
        "question": {"options": []},
        "response": {"option_id": "impute"},
    }
    outcome, saved, captured, create = _run_cleaner(_messy(), _report([]), [entry])
    assert isinstance(outcome, ValueError)
    create.assert_not_called()
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning", "error"]


def test_filter_on_a_column_whose_outliers_the_user_decided() -> None:
    """The operation field decides, never the wording: a Step 8 issue saying "from the
    mean" is no longer a mean fill. Where the user answered only the outlier pause, a
    note and a fill of the column's gaps survive; a flag (the user's choice writes it), a
    conversion and prose without an operation are dropped; other columns always pass."""
    df = _messy()
    resolutions = build_cleaner_resolutions([_answered(_outlier_question(), "treat_as_valid", df)])
    note = _op("revenue", "note", issue="4 values 6.8 SD from the mean")
    flag = _op("revenue", "flag_outliers")
    fill = _op("revenue", "fill_missing", {"method": "mean"})
    convert = _op("revenue", "convert_type", {"to": "string"})
    other = _op("units_sold", "fill_missing", {"method": "median"})
    decisions = [note, flag, fill, convert, *ADVERSARIAL_REVENUE, other]
    kept, dropped = filter_user_decided(decisions, resolutions)
    assert kept == [note, fill, other]
    assert dropped == [flag, convert, *ADVERSARIAL_REVENUE]


def test_filter_keeps_a_flag_where_the_user_decided_only_the_missing_values() -> None:
    df = _messy()
    resolutions = build_cleaner_resolutions([_answered(_mv_question(), "impute", df)])
    flag, note = _op("revenue", "flag_outliers"), _op("revenue", "note")
    fill, leave = _op("revenue", "fill_missing", {"method": "mode"}), _op("revenue", "leave_missing")
    standardize = _op("revenue", "standardize_values", {"mapping": {"a": "b"}})
    kept, dropped = filter_user_decided([flag, note, fill, leave, standardize], resolutions)
    assert kept == [flag, note]
    assert dropped == [fill, leave, standardize]


def test_filter_drops_everything_on_a_column_the_user_excluded() -> None:
    df = _messy()
    resolutions = build_cleaner_resolutions([_answered(_mv_question(), "exclude_column", df)])
    kept, dropped = filter_user_decided([_op("revenue", "note"), _op("revenue", "flag_outliers")], resolutions)
    assert kept == [] and len(dropped) == 2


def test_an_outlier_answer_on_a_column_the_user_later_excluded_is_recorded_not_run() -> None:
    """Out of the prompt's order (e.g. via the backstop): the outlier question was answered
    first, then the column was excluded. The run completes and nothing is claimed."""
    df = _messy()
    answered = [
        _answered(_outlier_question(), "flag_as_suspected_error", df),
        _answered(_mv_question(), "exclude_column", df),
        _notes_preserved(df),
    ]
    outcome, saved, _, _ = _run_cleaner(df, _report([]), answered)
    assert not isinstance(outcome, Exception), outcome
    assert "revenue" not in saved.columns and "revenue_outlier_flag" not in saved.columns
    assert not [d for d in outcome["cleaning_report"]["decisions"] if "outlier pause" in d["action"]]
    [superseded] = [r for r in outcome["cleaner_user_decisions_incorporated"] if r["pause_type"] == "outlier_pause"]
    assert superseded["resolution_summary"].startswith("Not applied: the user excluded `revenue`")
    # The saved outlier summary reports the exclusion, not the superseded answer.
    assert outcome["cleaning_report"]["outlier_review_summary"] == [
        {"column_name": "revenue", "routing": None, "resolution": "excluded_by_user"},
    ]


@pytest.mark.parametrize(
    "option_id, method_id",
    [
        ("impute", "median"),
        ("impute", "mean"),
        ("exclude_column", "median"),
        ("exclude_rows", "median"),
        ("preserve_missingness", "median"),
    ],
)
def test_each_missing_value_choice_executes_exactly_as_chosen(option_id, method_id) -> None:
    """Whatever the model writes about revenue, the user's choice is what runs."""
    df = _messy()
    deduped = df.drop_duplicates()
    # notes is the dataset's other column over 30%; answered so the run can complete.
    answered = [_answered(_mv_question(method_id=method_id), option_id, df), _notes_preserved(df)]

    outcome, saved, _, _ = _run_cleaner(df, _report([*ADVERSARIAL_REVENUE]), answered)

    assert not isinstance(outcome, Exception), outcome
    was_missing = deduped.index[deduped["revenue"].isna()]
    if option_id == "impute":
        expected = deduped["revenue"].median() if method_id == "median" else deduped["revenue"].mean()
        assert saved["revenue"].isna().sum() == 0
        assert (saved.loc[was_missing, "revenue"] == expected).all()
        assert saved["revenue"].drop(index=was_missing).equals(deduped["revenue"].drop(index=was_missing))
        assert len(saved) == 185
    elif option_id == "exclude_column":
        assert "revenue" not in saved.columns
        assert outcome["cleaner_excluded_columns"] == ["revenue"]
        assert len(saved) == 185
    elif option_id == "exclude_rows":
        assert saved.index.tolist() == deduped.index[deduped["revenue"].notna()].tolist()
        assert len(saved) == 185 - 70
    else:
        assert saved["revenue"].equals(deduped["revenue"])
        assert len(saved) == 185

    [decision] = _user_decisions(outcome, "revenue")
    assert decision["action"].startswith("User decision (missing-value pause):")
    assert decision["reason"].startswith("Chosen by the user at the missing-value pause, not decided by the Cleaner.")
    assert outcome["cleaner_user_decisions_incorporated"][:1] == [{
        "pause_type": "missing_value_pause",
        "column_name": "revenue",
        "option_chosen": option_id,
        "resolution_summary": decision["action"],
    }]
    # No model-written revenue decision survives next to the user's. The one other
    # revenue entry is the system's outlier record (revenue has 4 IQR outliers and
    # this report routes none), written after execution (Group 11).
    revenue = [d for d in outcome["cleaning_report"]["decisions"] if d["column_name"] == "revenue"]
    if option_id == "exclude_column":
        assert revenue == [decision]
    else:
        assert revenue[0] == decision and len(revenue) == 2
        assert revenue[1]["action"].startswith("Not reviewed:")
        assert revenue[1]["reason"].startswith("Computed from the cleaned data:")


def test_mode_imputation_on_a_text_column_uses_the_deduplicated_mode() -> None:
    df = _messy()
    deduped = df.drop_duplicates()
    answered = [_answered(_mv_question(), "impute", df), _answered(_mv_question("notes", "mode"), "impute", df)]
    outcome, saved, _, _ = _run_cleaner(df, _report([]), answered)
    assert saved["notes"].isna().sum() == 0
    assert (saved.loc[deduped.index[deduped["notes"].isna()], "notes"] == deduped["notes"].mode().iloc[0]).all()


@pytest.mark.parametrize(
    "domain, option_id, removed",
    [
        ("financial", "treat_as_valid", False),
        ("financial", "flag_as_suspected_error", True),
        ("medical", "include_with_annotation", False),
        ("medical", "exclude_pending_clinical_review", True),
    ],
)
def test_each_outlier_choice_executes_exactly_as_chosen(domain, option_id, removed) -> None:
    df = _messy()
    deduped = df.drop_duplicates()
    # Both columns over 30% keep their missing values, so only the outlier choice changes revenue.
    answered = [
        _answered(_mv_question(), "preserve_missingness", df),
        _notes_preserved(df),
        _answered(_outlier_question(domain=domain), option_id, df),
    ]

    outcome, saved, _, _ = _run_cleaner(df, _report([*ADVERSARIAL_OUTLIERS]), answered)

    assert not isinstance(outcome, Exception), outcome
    assert len(saved) == 185
    assert saved.index[saved["revenue_outlier_flag"] == 1].tolist() == OUTLIER_ROWS
    if removed:
        assert saved.loc[OUTLIER_ROWS, "revenue"].isna().all()
        assert saved["revenue"].isna().sum() == 70 + 4
    else:
        assert saved.loc[OUTLIER_ROWS, "revenue"].tolist() == deduped.loc[OUTLIER_ROWS, "revenue"].tolist()
        assert saved["revenue"].isna().sum() == 70
    assert saved["revenue"].drop(index=OUTLIER_ROWS).equals(deduped["revenue"].drop(index=OUTLIER_ROWS))
    assert outcome["cleaner_outliers_handled"] == {"revenue": 4}

    # Rule 10: the decision carries the domain reasoning the user saw, attributed to the user.
    [decision] = [d for d in _user_decisions(outcome, "revenue") if "outlier pause" in d["action"]]
    assert decision["action"].startswith(f"User decision ({domain} outlier pause):")
    assert decision["reason"].startswith(f"Chosen by the user at the {domain} outlier pause, not decided by the Cleaner.")
    assert FIN_NOTE in decision["reason"]


def test_outlier_masks_stay_aligned_by_label_after_rows_are_removed() -> None:
    """Rows are removed twice before the outlier choice is applied — duplicates by the
    model's own decision, then the user's exclude-rows choice — so a positional mask
    would empty the wrong rows. The exact labelled rows must be marked and emptied."""
    df = pd.DataFrame({
        "amount": [10.0, 11.0, 11.0, 11.0, 12.0, 13.0, 14.0, 15.0, 1000.0, 16.0, 17.0, np.nan, 18.0, 2000.0],
        "grp": ["a", "b", "b", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"],
        "gap": [1.0, np.nan, np.nan, np.nan, 1.0, np.nan, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, np.nan, 1.0],
    })
    answered = [
        _answered(_mv_question("gap"), "exclude_rows", df),
        _answered(_outlier_question("amount"), "flag_as_suspected_error", df),
    ]

    outcome, saved, _, _ = _run_cleaner(df, _report([]), answered)

    assert not isinstance(outcome, Exception), outcome
    assert saved.index.tolist() == [0, 4, 6, 7, 8, 9, 10, 11, 13]
    assert saved.index[saved["amount_outlier_flag"] == 1].tolist() == [8, 13]
    assert saved.index[saved["amount"].isna()].tolist() == [8, 11, 13]
    kept = [0, 4, 6, 7, 9, 10]
    assert saved.loc[kept, "amount"].tolist() == df.loc[kept, "amount"].tolist()


def test_cleaner_node_repeat_pause_errors_without_saving() -> None:
    df = _messy()
    outcome, saved, captured, _ = _run_cleaner(df, _mv_question(), [_answered(_mv_question(), "impute", df)])
    assert isinstance(outcome, ValueError)
    assert "asked again" in str(outcome)
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning", "error"]


def test_cleaner_node_returns_the_checked_question_for_a_new_pause() -> None:
    df = _messy()
    outcome, saved, captured, _ = _run_cleaner(
        df, _mv_question("notes", "mode"), [_answered(_mv_question(), "impute", df)]
    )
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning"]
    stored = outcome["missing_value_pause_data"]
    assert stored["column_name"] == "notes"
    assert (stored["missing_count"], stored["total_rows"]) == (91, 200)
    assert stored["options"][-1]["id"] == "preserve_missingness"


def test_cleaner_node_backstop_pauses_instead_of_saving_a_report_that_skipped_a_column() -> None:
    outcome, saved, captured, _ = _run_cleaner(_messy(), _report([]))
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning"]
    assert outcome["missing_value_pause_data"]["column_name"] == "revenue"
    assert [o["id"] for o in outcome["missing_value_pause_data"]["options"]] == [
        "impute", "exclude_column", "exclude_rows", "preserve_missingness",
    ]


def test_cleaning_report_with_user_decisions_validates_against_the_strict_schemas() -> None:
    """VP8: the report and decisions go through CleaningReport / CleaningDecision /
    AnalysisResponse intact, attribution included."""
    df = _messy()
    answered = [
        _answered(_mv_question(), "impute", df),
        _answered(_mv_question("notes", "mode"), "preserve_missingness", df),
        _answered(_outlier_question(), "flag_as_suspected_error", df),
    ]
    outcome, _, captured, _ = _run_cleaner(df, _report([]), answered)

    report = outcome["cleaning_report"]
    CleaningReport.model_validate(report)
    for decision in report["decisions"]:
        CleaningDecision.model_validate(decision)
    api = AnalysisResponse(
        id="test-analysis-id",
        filename="messy_data.csv",
        status="complete",
        created_at=datetime.datetime.now(datetime.timezone.utc),
        cleaning_report=report,
        cleaning_decisions=captured[-1]["cleaning_decisions"],
    ).model_dump(mode="json")
    assert api["cleaning_decisions"] == report["decisions"]
    assert api["cleaning_report"]["decisions"] == report["decisions"]
    user_actions = [d["action"] for d in api["cleaning_decisions"] if d["action"].startswith("User decision")]
    assert len(user_actions) == 3
    assert [r["option_chosen"] for r in outcome["cleaner_user_decisions_incorporated"]] == [
        "impute", "preserve_missingness", "flag_as_suspected_error",
    ]
    assert report["user_decisions_incorporated"] == outcome["cleaner_user_decisions_incorporated"]


# ---------------------------------------------------------------------------
# Group 11 — outlier routing: outlier_review, its backstop, the outlier records
# (errors.md 2026-09-25 "No Python backstop for the Cleaner's outlier pauses")
# ---------------------------------------------------------------------------

REVENUE_MEAN = 42790.66941066989
REVENUE_STD = 104094.20063998573
# A Step 8-compliant flag-and-include decision: its issue states the SD distance
# "from the mean", so the keyword router runs a mean fill, not a flag.
FLAG_INCLUDE_SD = {
    "column_name": "revenue",
    "issue": "4 values from 500,000 to 750,000, about 6.8 SD from the mean",
    "action": "flagged as potential wholesale orders; included in analysis with annotation",
    "reason": "retail outliers outside financial-magnitude territory",
}


def _missing_answered(df: pd.DataFrame, revenue_option: str = "impute") -> list:
    """Both columns over 30% answered, so the missing-value backstop lets a report through."""
    return [_answered(_mv_question(), revenue_option, df), _notes_preserved(df)]


def _routed(decisions: list, *routes) -> dict:
    report = _report(decisions)
    report["outlier_review"] = [{"column_name": c, "domain_context": d} for c, d in routes]
    return report


def _system_records(outcome: dict, column: str) -> list:
    return [
        d for d in outcome["cleaning_report"]["decisions"]
        if d["column_name"] == column and d["reason"].startswith("Computed from the cleaned data:")
    ]


def _sent_message(create) -> dict:
    return json.loads(create.call_args.kwargs["messages"][0]["content"])


def test_messy_data_requires_routing_for_revenue_only() -> None:
    """Addition 1: the full required set on the raw upload, not just the column we expect."""
    df = _messy()
    required = _outlier_review_columns(df, [])
    assert list(required) == ["revenue"]
    assert required["revenue"].sum() == 4
    assert df.index[required["revenue"]].tolist() == OUTLIER_ROWS
    # Once revenue's outlier pause is answered, or revenue excluded, nothing is required.
    assert _outlier_review_columns(df, [_answered(_outlier_question(), "treat_as_valid", df)]) == {}
    assert _outlier_review_columns(df, [_answered(_mv_question(), "exclude_column", df)]) == {}


def test_the_message_lists_the_required_columns_from_the_same_mask() -> None:
    df = _messy()
    _, _, _, create = _run_cleaner(df, _routed([], ("revenue", "none")), _missing_answered(df))
    message = _sent_message(create)
    assert message["outlier_review_columns"] == ["revenue"]
    assert message["column_info"]["revenue"]["outlier_count"] == 4

    answered = _missing_answered(df) + [_answered(_outlier_question(), "treat_as_valid", df)]
    _, _, _, create = _run_cleaner(df, _report([]), answered)
    assert _sent_message(create)["outlier_review_columns"] == []


def test_columns_after_the_50th_are_never_required() -> None:
    wide = pd.DataFrame({f"c{i}": [1.0] * 10 for i in range(50)})
    wide["late"] = [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0, 900.0]
    assert _outlier_review_columns(wide, []) == {}


@pytest.mark.parametrize("domain", ["financial", "medical"])
def test_backstop_turns_a_report_routing_a_column_to_a_pause_into_that_pause(domain) -> None:
    df = _messy()
    required = _outlier_review_columns(df, [])
    routing, unrouted = normalize_outlier_review(_routed([], ("revenue", domain)), required)
    assert (routing, unrouted) == ({"revenue": domain}, {})

    pause = apply_outlier_backstop(_routed([], ("revenue", domain)), df, required, routing)

    assert pause["type"] == "outlier_decision_required"
    assert (pause["domain_context"], pause["column_name"]) == (domain, "revenue")
    assert [o["id"] for o in pause["options"]] == {
        "financial": ["treat_as_valid", "flag_as_suspected_error"],
        "medical": ["include_with_annotation", "exclude_pending_clinical_review"],
    }[domain]
    assert (pause["outlier_count"], pause["outlier_value"], pause["sd_distance"]) == (4, 750000.0, 6.79)
    assert pause["column_mean"] == pytest.approx(REVENUE_MEAN)
    assert pause["column_std"] == pytest.approx(REVENUE_STD)
    note = pause["financial_context_note" if domain == "financial" else "clinical_significance_note"]
    assert note.startswith("Not assessed. The Cleaner routed `revenue` as " + domain)
    assert "4 value(s) lie outside the IQR bounds" in note and "from 500000 to 750000" in note
    # Consequences promise only what apply_user_decisions runs.
    assert "set to missing in `revenue`" in pause["options"][1]["consequence"]
    assert "rows are kept and marked in `revenue_outlier_flag`" in pause["options"][1]["consequence"]
    stored = validate_cleaner_pause(pause, df, [])
    assert stored["outlier_count"] == 4
    assert stored["options"][0]["label"].startswith(("Treat the 4", "Include the 4"))


@pytest.mark.parametrize(
    "report",
    [_routed([], ("revenue", "none")), _report([]), _routed([], ("revenue", "retail"))],
    ids=["routed-none", "no-outlier-review", "invalid-routing"],
)
def test_backstop_does_not_fire_without_a_medical_or_financial_routing(report) -> None:
    df = _messy()
    required = _outlier_review_columns(df, [])
    routing, _ = normalize_outlier_review(report, required)
    assert apply_outlier_backstop(report, df, required, routing) is report


def test_outlier_backstop_passes_a_model_pause_untouched() -> None:
    df = _messy()
    pause = _outlier_question()
    required = _outlier_review_columns(df, [])
    assert apply_outlier_backstop(pause, df, required, {"revenue": "financial"}) is pause


def test_cleaner_node_backstop_pauses_on_a_column_the_report_routed_financial() -> None:
    df = _messy()
    outcome, saved, captured, _ = _run_cleaner(
        df, _routed([], ("revenue", "financial")), _missing_answered(df)
    )
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning"]
    stored = outcome["outlier_pause_data"]
    assert (stored["column_name"], stored["outlier_count"], stored["sd_distance"]) == ("revenue", 4, 6.79)
    assert stored["financial_context_note"].startswith("Not assessed.")


def test_an_answered_or_excluded_column_is_never_paused_again_whatever_the_routing() -> None:
    df = _messy()
    answered = _missing_answered(df) + [_answered(_outlier_question(), "flag_as_suspected_error", df)]
    outcome, saved, _, _ = _run_cleaner(df, _routed([], ("revenue", "financial")), answered)
    assert not isinstance(outcome, Exception), outcome
    assert saved.index[saved["revenue_outlier_flag"] == 1].tolist() == OUTLIER_ROWS
    assert _system_records(outcome, "revenue") == []  # the user's decision is the record

    excluded = [_answered(_mv_question(), "exclude_column", df), _notes_preserved(df)]
    outcome, saved, _, _ = _run_cleaner(df, _routed([], ("revenue", "financial")), excluded)
    assert not isinstance(outcome, Exception), outcome
    assert "revenue" not in saved.columns
    assert outcome["cleaning_report"]["outlier_review_summary"] == [
        {"column_name": "revenue", "routing": None, "resolution": "excluded_by_user"},
    ]


@pytest.mark.parametrize(
    "review, expected_routing, reason_part",
    [
        (None, {}, "no outlier_review"),
        ("not a list", {}, "no outlier_review"),
        ([], {}, "no entry for this column"),
        ([{"column_name": "no_such_column", "domain_context": "financial"}], {}, "no entry for this column"),
        ([{"column_name": "units_sold", "domain_context": "financial"}], {}, "no entry for this column"),
        (["revenue", {"domain_context": "financial"}], {}, "no entry for this column"),
        ([{"column_name": "revenue", "domain_context": "retail"}], {}, "'retail'"),
        ([{"column_name": "revenue", "domain_context": ["financial"]}], {}, "['financial']"),
        ([{"column_name": "revenue", "domain_context": "none"}] * 2, {"revenue": "none"}, None),
        (
            [{"column_name": "revenue", "domain_context": "none"},
             {"column_name": "revenue", "domain_context": "financial"}],
            {},
            "conflicting",
        ),
    ],
    ids=[
        "field-missing", "field-not-a-list", "empty-list", "column-not-in-data",
        "column-without-outliers", "malformed-entries", "invalid-context", "unhashable-context",
        "duplicate-same", "duplicate-conflicting",
    ],
)
def test_normalize_outlier_review_resolves_every_malformed_case_without_raising(
    review, expected_routing, reason_part
) -> None:
    df = _messy()
    report = _report([])
    if review is not None:
        report["outlier_review"] = review
    routing, unrouted = normalize_outlier_review(report, _outlier_review_columns(df, []))
    assert routing == expected_routing
    if reason_part is None:
        assert unrouted == {}
    else:
        assert list(unrouted) == ["revenue"] and reason_part in unrouted["revenue"]


def test_an_entry_for_a_column_that_needs_no_routing_is_ignored_with_a_warning(caplog) -> None:
    df = _messy()
    report = _routed([], ("units_sold", "financial"), ("revenue", "none"))
    with caplog.at_level("WARNING", logger="backend.agents.cleaner"):
        routing, unrouted = normalize_outlier_review(report, _outlier_review_columns(df, []))
    assert (routing, unrouted) == ({"revenue": "none"}, {})
    assert "'column_name': 'units_sold'" in caplog.text


def test_an_entry_for_an_excluded_column_is_ignored() -> None:
    df = _messy()
    required = _outlier_review_columns(df, [_answered(_mv_question(), "exclude_column", df)])
    assert normalize_outlier_review(_routed([], ("revenue", "financial")), required) == ({}, {})


@pytest.mark.parametrize(
    "review",
    [None, [{"column_name": "revenue", "domain_context": "retail"}],
     [{"column_name": "revenue", "domain_context": "none"}, {"column_name": "revenue", "domain_context": "financial"}]],
    ids=["missing", "invalid", "conflicting"],
)
def test_an_unrouted_column_completes_the_run_with_an_unreviewed_record(review) -> None:
    """DECISION 2: never raises; the report says plainly the outliers were not reviewed."""
    df = _messy()
    report = _report([])
    if review is not None:
        report["outlier_review"] = review
    outcome, saved, _, _ = _run_cleaner(df, report, _missing_answered(df))
    assert not isinstance(outcome, Exception), outcome
    [record] = _system_records(outcome, "revenue")
    assert record["issue"].startswith("4 value(s) in `revenue` lie outside the IQR bounds")
    assert "the most extreme, 750000, is 6.79 SD from the column mean of 42790.7" in record["issue"]
    assert record["action"] == (
        "Not reviewed: the Cleaner's report gave no valid outlier routing for `revenue`, "
        "so no question was asked about these values."
    )
    assert record["reason"].startswith(
        "Computed from the cleaned data: 4 of the 4 value(s) are unchanged; they are not flagged."
    )
    assert "Treat these values as unreviewed" in record["reason"]
    assert saved.loc[OUTLIER_ROWS, "revenue"].tolist() == [500000.0, 750000.0, 620000.0, 580000.0]
    assert outcome["cleaning_report"]["outlier_review_summary"] == [
        {"column_name": "revenue", "routing": None, "resolution": "unreviewed"},
    ]


def test_the_unreviewed_record_survives_the_filter_and_the_strict_schemas() -> None:
    df = _messy()
    # revenue is user-decided, so the filter drops every model decision on it.
    outcome, _, captured, _ = _run_cleaner(df, _report([FLAG_INCLUDE_SD]), _missing_answered(df))
    report = outcome["cleaning_report"]
    [record] = _system_records(outcome, "revenue")
    assert FLAG_INCLUDE_SD not in report["decisions"]
    assert record in captured[-1]["cleaning_decisions"]
    CleaningReport.model_validate(report)
    CleaningDecision.model_validate(record)
    api = AnalysisResponse(
        id="test-analysis-id",
        filename="messy_data.csv",
        status="complete",
        created_at=datetime.datetime.now(datetime.timezone.utc),
        cleaning_report=report,
        cleaning_decisions=captured[-1]["cleaning_decisions"],
    ).model_dump(mode="json")
    assert record in api["cleaning_decisions"]


def test_n1_user_decided_missing_values_and_a_model_outlier_decision_on_the_same_column() -> None:
    """The model's own outlier decision on user-decided revenue is dropped (it would have
    run a mean fill), and the system record states the outliers' routing and true state."""
    df = _messy()
    deduped = df.drop_duplicates()
    outcome, saved, _, _ = _run_cleaner(
        df, _routed([FLAG_INCLUDE_SD], ("revenue", "none")), _missing_answered(df)
    )
    assert not isinstance(outcome, Exception), outcome
    decisions = outcome["cleaning_report"]["decisions"]
    assert FLAG_INCLUDE_SD not in decisions
    [user] = _user_decisions(outcome, "revenue")
    [record] = _system_records(outcome, "revenue")
    assert [d for d in decisions if d["column_name"] == "revenue"] == [user, record]
    assert record["action"] == (
        "Outlier review: the Cleaner routed these values 'none' (no user decision needed), "
        "so no question was asked."
    )
    assert record["reason"].startswith(
        "Computed from the cleaned data: 4 of the 4 value(s) are unchanged; they are not flagged."
    )
    assert "not a check" in record["reason"]
    # The user's median ran, not the model text's mean; outliers kept, no flag column.
    assert (saved.loc[deduped.index[deduped["revenue"].isna()], "revenue"] == deduped["revenue"].median()).all()
    assert saved.loc[OUTLIER_ROWS, "revenue"].tolist() == deduped.loc[OUTLIER_ROWS, "revenue"].tolist()
    assert "revenue_outlier_flag" not in saved.columns
    assert outcome["cleaning_report"]["outlier_review_summary"] == [
        {"column_name": "revenue", "routing": "none", "resolution": "routed_none"},
    ]


def _amount_frame() -> pd.DataFrame:
    """No column over 30% missing; `amount` has two IQR outliers (rows 8 and 13) and one gap."""
    return pd.DataFrame({
        "amount": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 1000.0, 18.0, 19.0, np.nan, 20.0, 2000.0],
        "grp": list("abcdefghijklmn"),
    })


def test_a_prose_flag_decision_runs_nothing_and_cannot_contradict_the_record() -> None:
    """F3b addition 2, after Build G: the Step 8 prose that the keyword router ran as a
    mean fill (its issue says "from the mean") names no operation, so nothing runs; its
    claim is not reported as an action, and the system record agrees with the data."""
    df = _amount_frame()
    model = {"column_name": "amount", "issue": "2 values 3.1 SD from the mean",
             "action": "flagged as potential process events; included with annotation", "reason": "r"}
    outcome, saved, _, _ = _run_cleaner(df, _routed([model], ("amount", "none")))
    assert not isinstance(outcome, Exception), outcome
    decisions = outcome["cleaning_report"]["decisions"]
    assert model not in decisions
    assert not any(d["action"].startswith("flagged") for d in decisions)
    assert saved["amount"].isna().sum() == 1 and "amount_outlier_flag" not in saved.columns
    [not_run] = [d for d in decisions if d["column_name"] == "amount" and d["action"].startswith("Not executed")]
    assert not_run["action"] == "Not executed: the decision names no operation. Nothing was changed."
    assert decisions[0]["action"].startswith("Contract check: 1 of the Cleaner's 1 decisions had no valid operation")
    [record] = _system_records(outcome, "amount")
    assert record["reason"].startswith(
        "Computed from the cleaned data: 2 of the 2 value(s) are unchanged; they are not flagged."
    )


def test_the_record_reports_a_flag_the_model_decision_did_add() -> None:
    df = _amount_frame()
    model = _op("amount", "flag_outliers", issue="2 extreme values")
    outcome, saved, _, _ = _run_cleaner(df, _routed([model], ("amount", "none")))
    [record] = _system_records(outcome, "amount")
    assert saved.index[saved["amount_outlier_flag"] == 1].tolist() == [8, 13]
    assert record["reason"].startswith(
        "Computed from the cleaned data: 2 of the 2 value(s) are unchanged; "
        "2 of them are marked in `amount_outlier_flag`."
    )
    [flag] = [d for d in outcome["cleaning_report"]["decisions"] if d["action"].startswith("Cleaner decision")]
    assert flag["action"] == (
        "Cleaner decision: marked the 2 row(s) holding these values in `amount_outlier_flag` "
        "(1 = outside the IQR bounds); the values themselves are unchanged and stay in every statistic"
    )
    assert outcome["cleaner_outliers_handled"] == {"amount": 2}


def test_the_record_counts_an_outlier_removed_with_a_duplicate_row() -> None:
    df = _amount_frame()
    df.loc[14] = df.loc[8]  # a duplicate of an outlier row
    outcome, saved, _, _ = _run_cleaner(df, _routed([], ("amount", "none")))
    assert 14 not in saved.index
    [record] = _system_records(outcome, "amount")
    assert record["issue"].startswith("3 value(s) in `amount`")
    assert record["reason"].startswith(
        "Computed from the cleaned data: 2 of the 3 value(s) are unchanged; 1 were removed with "
        "their rows or changed by other cleaning decisions; they are not flagged."
    )


def test_the_record_never_raises_on_a_converted_column() -> None:
    df = _amount_frame()
    model = _op("amount", "convert_type", {"to": "string"})
    outcome, _, _, _ = _run_cleaner(df, _routed([model], ("amount", "none")))
    assert not isinstance(outcome, Exception), outcome
    [record] = _system_records(outcome, "amount")
    assert record["reason"].startswith("Computed from the cleaned data: 0 of the 2 value(s) are unchanged; 2 were")
    assert _same_value(pd.NA, 1.0) is False
    assert _same_value(pd.Categorical([1.0])[0], 1.0) is True


@pytest.mark.parametrize(
    "model_value, stored_value, sd",
    [(123.0, 750000.0, 6.79), ("750000", 750000.0, 6.79), (500000, 500000.0, 4.39)],
    ids=["not-an-outlier", "not-a-number", "a-flagged-value"],
)
def test_validate_overwrites_a_model_outlier_pauses_numbers_with_pythons(model_value, stored_value, sd) -> None:
    """DECISION 3: the same honesty rule as the count. A representative the model chose is
    kept only when it is one of the flagged values (its note text describes it); its SD
    distance, and the mean and std, are always Python's."""
    wrong = _outlier_question(outlier_value=model_value, sd_distance=99.0, column_mean=1.0, column_std=2.0)
    stored = validate_cleaner_pause(wrong, _messy(), [])
    assert (stored["outlier_count"], stored["outlier_value"], stored["sd_distance"]) == (4, stored_value, sd)
    assert stored["column_mean"] == pytest.approx(REVENUE_MEAN)
    assert stored["column_std"] == pytest.approx(REVENUE_STD)
    assert stored["financial_context_note"] == FIN_NOTE  # the model's text is kept as written


def test_an_infinite_value_never_crashes_or_writes_nan() -> None:
    """Code Review: read_csv parses "inf"; the stats must stay finite (JSON-safe) and never raise."""
    only_inf = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, np.inf])
    facts = _outlier_facts(only_inf, _iqr_outlier_mask(only_inf))
    assert (facts["count"], facts["value"], facts["sd_distance"]) == (1, None, None)
    assert facts["mean"] == pytest.approx(3.5)
    with_finite = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0, np.inf])
    facts = _outlier_facts(with_finite, _iqr_outlier_mask(with_finite))
    assert (facts["count"], facts["value"]) == (2, 100.0)
    assert np.isfinite([facts["mean"], facts["std"], facts["sd_distance"]]).all()

    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, np.inf], "g": list("abcdefg")})
    outcome, _, captured, _ = _run_cleaner(df, _routed([], ("x", "none")))
    assert not isinstance(outcome, Exception), outcome
    [record] = _system_records(outcome, "x")
    assert record["issue"] == "1 value(s) in `x` lie outside the IQR bounds (-2 to 10)"
    json.dumps(captured[-1], allow_nan=False)  # the Supabase payload holds no NaN or inf


def test_python_written_pause_text_matches_the_prompt() -> None:
    """Rule 7 drift guard: the §8.2/§8.3 sentences and labels Python re-renders are the prompt's own."""
    prompt = (pathlib.Path("backend") / "prompts" / "cleaner_system.md").read_text()
    for sentence in _OUTLIER_DOMAIN_SENTENCE.values():
        assert sentence[0].lower() + sentence[1:] in prompt
    for label in _OUTLIER_LABELS.values():
        assert label.replace("{n}", "<outlier_count>") in prompt



# ---------------------------------------------------------------------------
# Group 12 — the Cleaner's own decisions run by named operation (Build G)
# (errors.md 2026-09-25 "The Cleaner's own (model-authored) decisions are still
# executed by keyword matching")
# ---------------------------------------------------------------------------

MESSY_DEDUPED_ROWS = 185


def _records_for(outcome: dict, column: str) -> list:
    return [d for d in outcome["cleaning_report"]["decisions"] if d["column_name"] == column]


def _item(items: list, column: str) -> dict:
    [item] = [i for i in items if i["column_name"] == column]
    return item


@pytest.mark.parametrize(
    "to, values, expected_dtype, expected",
    [
        ("string", [1, 2, 3], "object", ["1", "2", "3"]),
        ("numeric", ["1.5", "2", None], "float64", [1.5, 2.0, None]),
        ("integer", [1.0, 2.0, None], "Int64", [1, 2, None]),
        ("datetime", ["2024-01-01", "2024-02-01", None], "datetime64[ns]",
         [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01"), None]),
    ],
)
def test_convert_type_converts_every_recorded_value(to, values, expected_dtype, expected) -> None:
    df = pd.DataFrame({"c": values, "k": ["a", "b", "c"]})
    frame, items, [record], _, discrepancies = _run_ops(df, [_op("c", "convert_type", {"to": to})])
    assert str(frame["c"].dtype) == expected_dtype
    assert [None if pd.isna(v) else v for v in frame["c"].tolist()] == expected
    assert record["action"].startswith(f"Cleaner decision: converted `c` from {df['c'].dtype} to {expected_dtype} ({to})")
    assert discrepancies == []


def test_standardize_values_maps_every_variant_and_counts_each() -> None:
    df = _messy()
    mapping = {"north": "North", "SOUTH": "South", "south": "South"}
    frame, _, [record], _, _ = _run_ops(df, [_op("region", "standardize_values", {"mapping": mapping})])
    assert frame["region"].value_counts().to_dict() == {"North": 72, "South": 45, "East": 34, "West": 30}
    assert frame["region"].isna().sum() == 4
    assert record["action"] == (
        "Cleaner decision: replaced 77 value(s) in `region`: 'north' → 'North' (32); "
        "'SOUTH' → 'South' (23); 'south' → 'South' (22); 6 distinct values became 4"
    )


@pytest.mark.parametrize(
    "params, filled",
    [
        ({"method": "median"}, 3.0),
        ({"method": "mean"}, 3.5),
        ({"method": "mode"}, 2.0),
        ({"method": "constant", "value": 0}, 0.0),
    ],
)
def test_fill_missing_fills_with_the_value_python_computes(params, filled) -> None:
    df = pd.DataFrame({"x": [2.0, 2.0, 4.0, 6.0, np.nan], "k": list("abcde")})  # no duplicate rows
    frame, _, [record], _, _ = _run_ops(df, [_op("x", "fill_missing", params)])
    assert frame.loc[4, "x"] == filled and frame["x"].isna().sum() == 0
    assert record["issue"] == "1 missing values in `x` (20.0% of 5 rows)"


def test_fill_missing_with_a_text_constant_on_a_text_column() -> None:
    df = pd.DataFrame({"t": ["a", None, "b"]})
    frame, _, [record], _, _ = _run_ops(df, [_op("t", "fill_missing", {"method": "constant", "value": "unknown"})])
    assert frame["t"].tolist() == ["a", "unknown", "b"]
    assert record["action"] == "Cleaner decision: filled the 1 missing values in `t` with the value 'unknown'"


def test_leave_missing_changes_nothing_and_says_so() -> None:
    df = _messy()
    frame, _, [record], _, _ = _run_ops(df, [_op("return_flag", "leave_missing")])
    assert frame["return_flag"].isna().sum() == 15
    assert record["action"] == (
        "Cleaner decision: left the 15 missing values in `return_flag` unchanged (nothing imputed, no rows removed)"
    )


def test_flag_outliers_marks_the_raw_upload_mask() -> None:
    df = _messy()
    frame, _, [record], flagged, _ = _run_ops(df, [_op("revenue", "flag_outliers")])
    assert frame.index[frame["revenue_outlier_flag"] == 1].tolist() == OUTLIER_ROWS
    pd.testing.assert_series_equal(frame["revenue"], df.drop_duplicates()["revenue"])  # values unchanged
    assert flagged == {"revenue": 4}
    assert record["issue"].startswith("4 value(s) in `revenue` lie outside the IQR bounds")


def test_a_note_changes_nothing_and_is_labelled_as_the_cleaners() -> None:
    df = _messy()
    decisions = [
        _op("discount_pct", "note", issue="0 appears often", action="flagged for user verification"),
        _op(None, "note", {"columns": ["return_flag", "notes"]}, issue="missing together in 15 records"),
    ]
    frame, _, records, _, _ = _run_ops(df, decisions)
    pd.testing.assert_frame_equal(frame, df.drop_duplicates())
    assert [r["action"] for r in records] == [
        "No data changed: a note by the Cleaner, not an operation",
        "No data changed: a note by the Cleaner about `return_flag`, `notes`, not an operation",
    ]
    assert records[1]["issue"] == "The Cleaner's observation: missing together in 15 records"
    assert records[1]["column_name"] is None


@pytest.mark.parametrize(
    "decision, detail, printed",
    [
        ({"column_name": "units_sold", "action": "filled with median", "issue": "i", "reason": "r"},
         "the decision names no operation", True),
        (_op("units_sold", ""), "the decision names no operation", True),
        (_op("units_sold", "impute_median"), "'impute_median' is not one of the Cleaner's operations", True),
        (_op("revenue", "drop_rows"), "'drop_rows' is not an operation the Cleaner can run: removing rows", True),
        (_op("revenue", "drop_column"), "'drop_column' is not an operation the Cleaner can run: removing a column", True),
        (_op("revenue", "remove_outliers"), "'remove_outliers' is not an operation the Cleaner can run: removing or excluding outlier", True),
        (_op(None, "remove_duplicates"), "'remove_duplicates' is not an operation the Cleaner can run: the system removes", False),
        ({**_op("units_sold", "fill_missing"), "params": ["median"]}, "its params are not an object", True),
        (_op("units_sold", "fill_missing", {"method": "average"}), "params.method must be one of", True),
        (_op("units_sold", "fill_missing", {"method": "constant"}), "a constant fill needs params.value", True),
        (_op("units_sold", "fill_missing", {"method": "constant", "value": float("nan")}), "a constant fill needs params.value", True),
        (_op("units_sold", "fill_missing", {"method": "constant", "value": True}), "a constant fill needs params.value", True),
        (_op("region", "convert_type", {"to": "category"}), "params.to must be one of", True),
        (_op("region", "standardize_values", {"mapping": {}}), "params.mapping must be a non-empty object", True),
        (_op("region", "standardize_values", {"mapping": {"north": ""}}), "every params.mapping key and replacement", True),
        (_op("region", "note", {"columns": ["nope"]}), "params.columns must list columns", True),
        (_op("true", "fill_missing", {"method": "mode"}), "there is no column 'true' in the data", True),
        (_op(None, "fill_missing", {"method": "median"}), "a decision with no column can only be a note", False),
        (_op(None, "note", {"columns": ["region"]}), "a decision with no column can only be a note", False),
        (LEGACY_DEDUPE, "the decision names no operation", False),
        ("not an object", "the decision is not an object", False),
    ],
)
def test_every_invalid_decision_is_recorded_not_executed_and_never_raises(decision, detail, printed) -> None:
    df = _messy()
    frame, [item], records, _, _ = _run_ops(df, [decision])
    pd.testing.assert_frame_equal(frame, df.drop_duplicates())
    assert item["status"] == "not_executed" and item["contract"] is True
    assert item["detail"].startswith(detail)
    assert len(records) == (1 if printed else 0)
    if printed:
        assert records[0]["action"].startswith("Not executed: ")
        assert records[0]["action"].endswith("Nothing was changed.")
    contract = build_contract_record([item], True)
    assert contract["action"].startswith("Contract check: 1 of the Cleaner's 1 decisions had no valid operation")


@pytest.mark.parametrize(
    "decisions, column, detail",
    [
        ([_op("sales_rep", "fill_missing", {"method": "mean"})], "sales_rep",
         "mean imputation needs a numeric column; `sales_rep` is object"),
        ([_op("sales_rep", "fill_missing", {"method": "median"})], "sales_rep",
         "median imputation needs a numeric column"),
        ([_op("units_sold", "fill_missing", {"method": "constant", "value": "unknown"})], "units_sold",
         "`units_sold` is numeric (float64), so the fill value must be a number; 'unknown' is text"),
        ([_op("region", "fill_missing", {"method": "constant", "value": 0})], "region",
         "`region` is text, so the fill value must be text; 0 is a number"),
        ([_op("customer_id", "fill_missing", {"method": "median"})], "customer_id", "`customer_id` has no missing values"),
        ([_op("customer_id", "leave_missing")], "customer_id", "`customer_id` has no missing values, so there were none"),
        ([_op("discount_pct", "convert_type", {"to": "integer"})], "discount_pct", "18"),
        ([_op("region", "convert_type", {"to": "numeric"})], "region",
         "181 recorded value(s) in `region` are not numbers"),
        ([_op("region", "convert_type", {"to": "datetime"})], "region",
         "181 recorded value(s) in `region` are not dates"),
        ([_op("units_sold", "convert_type", {"to": "datetime"})], "units_sold", "only text is converted to dates"),
        ([_op("region", "convert_type", {"to": "string"})], "region", "`region` is already stored as text"),
        ([_op("units_sold", "convert_type", {"to": "numeric"})], "units_sold", "`units_sold` is already numeric"),
        ([_op("product_code", "standardize_values", {"mapping": {"PRD-0001": "P1"}})], "product_code",
         "the Cleaner was not shown every value of `product_code`"),
        ([_op("region", "standardize_values", {"mapping": {"NORTH": "North", "north": "North"}})], "region",
         "1 of the values to replace are not in `region` ('NORTH'), so nothing was replaced"),
        ([_op("region", "standardize_values", {"mapping": {"North": "North"}})], "region",
         "none of the mapped values of `region` would change"),
        ([_op("region", "flag_outliers")], "region", "`region` is not numeric, so it has no IQR outliers"),
        ([_op("units_sold", "flag_outliers")], "units_sold", "`units_sold` has no values outside the IQR bounds"),
        ([_op("revenue", "convert_type", {"to": "string"}), _op("revenue", "flag_outliers")], "revenue",
         "`revenue` is no longer numeric (it is now object)"),
    ],
)
def test_an_operation_impossible_for_the_column_is_not_executed_and_changes_nothing(decisions, column, detail) -> None:
    df = _messy()
    frame, items, records, _, _ = _run_ops(df, decisions)
    refused = [i for i in items if i["status"] == "not_executed"]
    assert len(refused) == 1 and refused[0]["contract"] is False
    assert detail in refused[0]["detail"]
    record = records[refused[0]["index"]]
    assert record["action"] == f"Not executed: {refused[0]['detail']}. Nothing was changed."
    assert record["issue"].startswith("The Cleaner requested ")
    if len(decisions) == 1:
        pd.testing.assert_frame_equal(frame, df.drop_duplicates())


def test_the_two_router_crashes_are_now_recorded_refusals() -> None:
    """The keyword router raised TypeError here, after the user had answered pauses."""
    df = pd.DataFrame({"n": [1.0, 2.0, np.nan, 4.0], "k": list("abcd")})
    frame, items, records, _, _ = _run_ops(df, [
        _op("n", "convert_type", {"to": "integer"}),
        _op("n", "fill_missing", {"method": "constant", "value": "unknown"}),
    ])
    assert str(frame["n"].dtype) == "Int64" and frame["n"].isna().sum() == 1
    assert records[1]["action"].startswith(
        "Not executed: `n` is numeric (Int64), so the fill value must be a number; 'unknown' is text"
    )
    # A fractional median cannot fill a whole-number column either.
    df2 = pd.DataFrame({"n": [1.0, 2.0, np.nan], "k": list("abc")})
    frame2, _, records2, _, _ = _run_ops(df2, [
        _op("n", "convert_type", {"to": "integer"}),
        _op("n", "fill_missing", {"method": "median"}),
    ])
    assert frame2["n"].isna().sum() == 1
    assert "the median of `n` is 1.5, not a whole number" in records2[1]["action"]
    # Category conversion (the other crash's first half) is not an operation at all.
    [item] = _run_ops(_messy(), [_op("region", "convert_type", {"to": "category"})])[1]
    assert item["contract"] is True


def test_an_unexpected_failure_leaves_the_frame_unchanged_and_is_recorded() -> None:
    df = pd.DataFrame({"x": [1.0, np.nan, 3.0]})
    with patch("backend.agents.cleaner._fill_missing", side_effect=RuntimeError("boom")):
        frame, [item], [record], _, _ = _run_ops(df, [_op("x", "fill_missing", {"method": "median"})])
    pd.testing.assert_frame_equal(frame, df)
    assert item["status"] == "not_executed"
    assert record["action"] == "Not executed: it failed unexpectedly (RuntimeError: boom). Nothing was changed."


def test_a_failed_postcondition_is_reported_as_a_discrepancy() -> None:
    df = pd.DataFrame({"x": [1.0, np.nan, 3.0]})
    with patch("backend.agents.cleaner._fill_missing", side_effect=lambda frame, column, value: frame.copy()):
        _, _, [record], _, discrepancies = _run_ops(df, [_op("x", "fill_missing", {"method": "median"})])
    assert record["action"].startswith(
        "Cleaner decision (verification failed: `x` has 1 missing value(s) and dtype float64 (was float64) after the fill): "
    )
    assert discrepancies == [
        "Decision 1 (fill_missing with the median): `x` has 1 missing value(s) and dtype float64 (was float64) after the fill"
    ]
    assert re_profile_dataframe(df, discrepancies)["discrepancies"] == discrepancies


@pytest.mark.parametrize(
    "decisions",
    [
        [_op("units_sold", "fill_missing", {"method": "median"}), _op("units_sold", "leave_missing")],
        [_op("units_sold", "fill_missing", {"method": "median"}), _op("units_sold", "fill_missing", {"method": "mean"})],
        [_op("customer_id", "convert_type", {"to": "string"}), _op("customer_id", "convert_type", {"to": "numeric"})],
        [_op("region", "standardize_values", {"mapping": {"north": "North"}}),
         _op("region", "standardize_values", {"mapping": {"south": "South"}})],
    ],
)
def test_contradicting_decisions_on_one_column_are_all_refused(decisions) -> None:
    df = _messy()
    frame, items, records, _, _ = _run_ops(df, decisions)
    pd.testing.assert_frame_equal(frame, df.drop_duplicates())
    assert [i["status"] for i in items] == ["not_executed", "not_executed"]
    assert all("contradict each other" in r["action"] for r in records)


def test_an_exact_repeat_runs_once() -> None:
    df = _messy()
    fill = _op("units_sold", "fill_missing", {"method": "median"})
    frame, items, records, _, _ = _run_ops(df, [fill, dict(fill)])
    assert frame["units_sold"].isna().sum() == 0
    assert [i["status"] for i in items] == ["executed", "not_executed"]
    assert records[1]["action"] == "Not executed: it repeats decision 1 on `units_sold`. Nothing was changed."


@pytest.mark.parametrize(
    "prose",
    [
        {"issue": "missingness means the sale was never recorded", "action": "Exclude rows where it is missing"},
        {"issue": "4 values 6.8 SD from the mean", "action": "flagged as potential process events"},
        {"issue": "0 exact duplicate rows present", "action": "no duplicate rows present; no action taken"},
        {"issue": "a mean is meaningless", "action": "Exclude `units_sold` from analysis entirely; drop column"},
        {"issue": "x", "action": "Removed the 4 outlier values pending review; set to 'unknown'"},
    ],
)
def test_the_wording_of_a_decision_never_changes_what_runs(prose) -> None:
    """The live keyword-routing failures (F3 C3, F3b C4, the Step 8 probe) as wording
    around a named operation: only the operation runs, whatever the text says."""
    df = _messy()
    frame, _, [record], _, _ = _run_ops(df, [_op("units_sold", "fill_missing", {"method": "median"}, **prose)])
    expected = df.drop_duplicates().copy()
    expected["units_sold"] = expected["units_sold"].fillna(expected["units_sold"].median())
    pd.testing.assert_frame_equal(frame, expected)
    assert record["action"] == "Cleaner decision: filled the 15 missing values in `units_sold` with the median (270.5)"
    # The same wording on a note runs nothing at all.
    frame, _, _, _, _ = _run_ops(df, [_op("units_sold", "note", **prose)])
    pd.testing.assert_frame_equal(frame, df.drop_duplicates())


def test_order_standardize_before_fill_and_convert_before_fill() -> None:
    """Phases run in a fixed order whatever order the decisions are listed in."""
    df = pd.DataFrame({"t": ["b", "B", "B", None, "a"], "n": ["1", "2", None, "4", "5"]})
    frame, _, records, _, _ = _run_ops(df, [
        _op("t", "fill_missing", {"method": "mode"}),
        _op("n", "fill_missing", {"method": "median"}),
        _op("n", "convert_type", {"to": "numeric"}),
        _op("t", "standardize_values", {"mapping": {"B": "b"}}),
    ])
    assert frame["t"].tolist() == ["b", "b", "b", "b", "a"]  # the mode after standardizing is 'b'
    assert frame["n"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert all(r["action"].startswith("Cleaner decision:") for r in records)


def _live_contradiction_report() -> dict:
    """F3b C4's three contradictions, now with operations (region, return_flag), plus its
    Step 4 prose (no operation) and prose-only decisions on user-decided columns."""
    return _routed(
        [
            LEGACY_DEDUPE,
            _op("customer_id", "convert_type", {"to": "string"}),
            _op("region", "standardize_values", {"mapping": {"north": "North", "SOUTH": "South", "south": "South"}},
                action="normalised all region values to title case"),
            _op("return_flag", "leave_missing",
                action="no imputation applied; filled with mode ('N') for the remaining records"),
            _op("region", "fill_missing", {"method": "mode"}),
            _op("sales_rep", "fill_missing", {"method": "mode"}),
            {"column_name": "notes", "issue": "45.5% missing", "action": "91 missing values preserved per user decision", "reason": "r"},
            *ADVERSARIAL_REVENUE,
        ],
        ("revenue", "none"),
    )


def test_the_live_c3_c4_contradictions_cannot_recur() -> None:
    df = _messy()
    outcome, saved, captured, _ = _run_cleaner(df, _live_contradiction_report(), _missing_answered(df))
    assert not isinstance(outcome, Exception), outcome
    decisions = outcome["cleaning_report"]["decisions"]
    # Duplicates: the system's count, removed and stated; the false claim is nowhere.
    assert len(saved) == MESSY_DEDUPED_ROWS
    assert decisions[1]["action"] == "System step: removed the 15 exact duplicate rows, keeping the first occurrence of each"
    assert not any("0 exact duplicate" in d["issue"] or "no duplicate rows present" in d["action"] for d in decisions)
    # Region: the mapping ran, and the mode fill used the standardized values.
    assert saved["region"].value_counts().to_dict() == {"North": 76, "South": 45, "East": 34, "West": 30}
    assert [r["action"].split(":")[0] for r in _records_for(outcome, "region")] == ["Cleaner decision"] * 2
    # return_flag: the operation said leave, so all 15 stay missing, whatever the prose said.
    assert saved["return_flag"].isna().sum() == 15
    [flag_record] = _records_for(outcome, "return_flag")
    assert flag_record["action"].startswith("Cleaner decision: left the 15 missing values in `return_flag` unchanged")
    # The model's own action text is never printed as what happened; only its reasoning is kept.
    assert not any("filled with mode" in text for text in flag_record.values() if isinstance(text, str))
    assert flag_record["reason"] == "The Cleaner's reasoning: r"
    # Every Cleaner action was stated by the system; the contract record counts the prose.
    # 11 in the report: 5 dropped on user-decided columns still count toward the total.
    assert decisions[0]["action"].startswith("Contract check: 1 of the Cleaner's 11 decisions had no valid operation")
    for d in decisions:
        assert d["action"].split(":")[0] in (
            "Contract check", "System step", "Cleaner decision", "Not executed",
            "User decision (missing-value pause)", "Outlier review",
        ) or d["action"].startswith("No data changed")
    summary = outcome["cleaning_report"]["operations_summary"]
    assert summary == {
        "cleaner_decisions": 11, "executed": 5, "noted": 0, "not_executed": 1,
        "no_valid_operation": 1, "dropped_on_user_decided_columns": 5,
    }


def test_a_report_whose_decisions_all_lack_an_operation_completes_truthfully_with_a_contract_record() -> None:
    """VP3: the run finishes, nothing is guessed, and the first record says so."""
    df = _messy()
    prose = [
        {"column_name": "units_sold", "issue": "8% missing", "action": "filled 16 missing values with median", "reason": "r"},
        {"column_name": "region", "issue": "casing", "action": "normalised to title case", "reason": "r"},
        {"column_name": "sales_rep", "issue": "3% missing", "action": "filled with mode", "reason": "r"},
        LEGACY_DEDUPE,
    ]
    outcome, saved, _, _ = _run_cleaner(df, _routed(prose, ("revenue", "none")), _missing_answered(df))
    assert not isinstance(outcome, Exception), outcome
    decisions = outcome["cleaning_report"]["decisions"]
    assert decisions[0] == {
        "column_name": None,
        "issue": "4 of the 4 decisions in the Cleaner's report did not name a valid operation",
        "action": (
            "Contract check: 4 of the Cleaner's 4 decisions had no valid operation and were not executed; "
            "the data was not changed by them. 1 of them named no column and is not shown"
        ),
        "reason": (
            "Recorded by the system, not written by the Cleaner. Every change the Cleaner makes must name one "
            "of its operations, which the system checks and runs; a decision without one is never guessed "
            "from its wording. Reasons: the decision names no operation (4)."
        ),
    }
    deduped = df.drop_duplicates()
    for column in ("units_sold", "region", "sales_rep"):
        assert saved[column].isna().sum() == deduped[column].isna().sum()
    assert outcome["cleaning_report"]["operations_summary"]["no_valid_operation"] == 4


def test_a_report_without_a_decisions_list_gets_the_contract_record() -> None:
    df = _messy()
    report = _routed([], ("revenue", "none"))
    del report["decisions"]
    outcome, saved, _, _ = _run_cleaner(df, report, _missing_answered(df))
    assert outcome["cleaning_report"]["decisions"][0]["action"].startswith(
        "Contract check: the Cleaner's report had no valid decisions list"
    )
    assert len(saved) == MESSY_DEDUPED_ROWS


def test_a_flag_survives_on_a_column_whose_missing_values_the_user_decided() -> None:
    """S5 narrowing, at node level: the user's median runs, the Cleaner's flag marks the
    raw-mask rows, and the F3b record agrees; the Cleaner's fill on the column is dropped."""
    df = _messy()
    deduped = df.drop_duplicates()
    report = _routed(
        [_op("revenue", "flag_outliers"), _op("revenue", "fill_missing", {"method": "mean"})],
        ("revenue", "none"),
    )
    outcome, saved, _, _ = _run_cleaner(df, report, _missing_answered(df))
    assert not isinstance(outcome, Exception), outcome
    assert saved.index[saved["revenue_outlier_flag"] == 1].tolist() == OUTLIER_ROWS
    assert (saved.loc[deduped.index[deduped["revenue"].isna()], "revenue"] == deduped["revenue"].median()).all()
    [record] = _system_records(outcome, "revenue")
    assert "4 of them are marked in `revenue_outlier_flag`" in record["reason"]
    revenue_actions = [d["action"] for d in _records_for(outcome, "revenue")]
    assert revenue_actions[0].startswith("Cleaner decision: marked the 4 row(s)")
    assert revenue_actions[1].startswith("User decision (missing-value pause): imputed")
    assert outcome["cleaner_outliers_handled"] == {"revenue": 4}
    assert outcome["cleaning_report"]["operations_summary"]["dropped_on_user_decided_columns"] == 1


def test_the_report_passes_the_strict_schemas_and_is_plain_json() -> None:
    df = _messy()
    answered = [*_missing_answered(df), _answered(_outlier_question(), "flag_as_suspected_error", df)]
    outcome, _, captured, _ = _run_cleaner(df, _live_contradiction_report(), answered)
    report = outcome["cleaning_report"]
    json.dumps(report)  # no numpy or other non-JSON value anywhere, operations included
    CleaningReport.model_validate(report)
    for decision in report["decisions"]:
        assert set(decision) == {"column_name", "issue", "action", "reason"}
        CleaningDecision.model_validate(decision)
    api = AnalysisResponse(
        id="test-analysis-id",
        filename="messy_data.csv",
        status="complete",
        created_at=datetime.datetime.now(datetime.timezone.utc),
        cleaning_report=report,
        cleaning_decisions=captured[-1]["cleaning_decisions"],
    ).model_dump(mode="json")
    assert api["cleaning_decisions"] == report["decisions"]
    sources = [op["source"] for op in report["operations"]]
    assert sources[0] == "system" and "cleaner" in sources and sources.count("user") == 3
    assert report["re_profile_verification"]["discrepancies"] == []


def test_the_cleaner_call_allows_16000_tokens_and_a_truncated_response_fails_clearly() -> None:
    df = _messy()
    outcome, saved, captured, create = _run_cleaner(
        df, _routed([], ("revenue", "none")), _missing_answered(df), stop_reason="max_tokens"
    )
    assert create.call_args.kwargs["max_tokens"] == 16000
    assert isinstance(outcome, ValueError)
    assert "truncated: reached the max_tokens ceiling (16000)" in str(outcome)
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning", "error"]


def test_profiler_concerns_addressed_is_not_assessed_rather_than_a_false_false() -> None:
    df = _messy()
    concerns = [{"issue": "revenue 35% missing", "affected_columns": ["revenue"], "why_it_matters": "bias"}]
    outcome, _, _, create = _run_cleaner(
        df, _routed([], ("revenue", "none")), _missing_answered(df),
        profiler_top_3_concerns=concerns, profile_report=PROFILER_STRUCTURAL,
    )
    assert outcome["cleaning_report"]["profiler_concerns_addressed"] == [
        {"concern": concerns[0], "addressed": "not assessed"}
    ]
    sent = _sent_message(create)
    assert sent["duplicate_row_count"] == 15
    assert sent["semantically_categorical_columns"] == PROFILER_STRUCTURAL["semantically_categorical_columns"]
    assert "region" in sent["distinct_values"] and sent["interactions_detected"]


def test_the_prompt_lists_exactly_the_operations_python_runs() -> None:
    """Rule 7 drift guard: the operation names, conversion targets and fill methods in
    cleaner_system.md are the ones plan_model_decisions accepts."""
    from backend.agents.cleaner import _CONVERT_TARGETS, _FILL_METHODS, _MODEL_OPERATIONS
    prompt = (pathlib.Path("backend") / "prompts" / "cleaner_system.md").read_text()
    for name in _MODEL_OPERATIONS:
        assert f"| `{name}` |" in prompt
    assert '"to": "string" \\| "numeric" \\| "integer" \\| "datetime"' in prompt
    assert list(_CONVERT_TARGETS) == ["string", "numeric", "integer", "datetime"]
    assert '{"method": "median" \\| "mean" \\| "mode"}' in prompt and '"method": "constant"' in prompt
    assert list(_FILL_METHODS) == ["median", "mean", "mode", "constant"]


def test_flags_run_after_the_users_row_exclusions_so_the_record_counts_what_remains() -> None:
    """A user's exclude_rows removes an outlier row; the Cleaner's flag, run after it,
    marks and reports only the outlier row that is still there."""
    df = _amount_frame()
    df["gap"] = [np.nan, np.nan, np.nan, 4.0, np.nan, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, np.nan]
    answered = [_answered(_mv_question("gap", "median"), "exclude_rows", df)]
    outcome, saved, _, _ = _run_cleaner(df, _routed([_op("amount", "flag_outliers")], ("amount", "none")), answered)
    assert not isinstance(outcome, Exception), outcome
    assert 13 not in saved.index
    assert saved.index[saved["amount_outlier_flag"] == 1].tolist() == [8]
    [flag] = [d for d in _records_for(outcome, "amount") if d["action"].startswith("Cleaner decision")]
    assert flag["action"].startswith("Cleaner decision: marked the 1 row(s) holding these values")
    assert outcome["cleaner_outliers_handled"] == {"amount": 1}


def test_leave_missing_is_rechecked_on_the_final_frame() -> None:
    """Nothing in the pipeline fills a column the Cleaner left, but if anything ever did,
    the record would say so rather than repeat the planned count."""
    df = _messy()
    items = plan_model_decisions([_op("return_flag", "leave_missing")], df)
    frame = run_model_operations(df.drop_duplicates().copy(), items, _MODEL_PHASES_BEFORE_USER, df, _distinct_value_columns(df))
    frame["return_flag"] = frame["return_flag"].fillna("N")
    [record], _, discrepancies = build_model_records(items, frame)
    assert record["action"].startswith(
        "Cleaner decision (verification failed: 15 of the 15 values left missing in `return_flag` "
        "were filled afterwards): left"
    )
    assert discrepancies == [
        "Decision 1 (leave_missing): 15 of the 15 values left missing in `return_flag` were filled afterwards"
    ]


def test_a_failed_check_reaches_the_saved_re_profile_verification() -> None:
    df = _amount_frame()
    with patch("backend.agents.cleaner._fill_missing", side_effect=lambda frame, column, value: frame.copy()):
        outcome, _, captured, _ = _run_cleaner(
            df, _routed([_op("amount", "fill_missing", {"method": "median"})], ("amount", "none"))
        )
    expected = [
        "Decision 1 (fill_missing with the median): `amount` has 1 missing value(s) and dtype float64 "
        "(was float64) after the fill"
    ]
    assert outcome["cleaning_report"]["re_profile_verification"]["discrepancies"] == expected
    assert captured[-1]["cleaning_report"]["re_profile_verification"]["discrepancies"] == expected


def test_records_number_decisions_by_their_position_in_the_cleaners_report() -> None:
    """A dropped decision on a user-decided column still counts, so "decisions 2, 3" in a
    record are the report's second and third decisions."""
    df = _messy()
    report = _routed(
        [
            _op("revenue", "fill_missing", {"method": "mean"}),  # dropped: the user decided revenue
            _op("units_sold", "fill_missing", {"method": "median"}),
            _op("units_sold", "fill_missing", {"method": "mean"}),
        ],
        ("revenue", "none"),
    )
    outcome, _, _, _ = _run_cleaner(df, report, _missing_answered(df))
    units = _records_for(outcome, "units_sold")
    assert [r["action"].split(" on ")[0] for r in units] == ["Not executed: decisions 2, 3"] * 2
    logged = [o.get("decision") for o in outcome["cleaning_report"]["operations"] if o["source"] == "cleaner"]
    assert logged == [2, 3, None]  # the dropped decision is logged without a number


def test_leave_missing_on_rows_the_user_later_excluded_is_not_a_failure() -> None:
    """Code Review finding 2: `b` is missing only where `a` is; the Cleaner leaves `b`,
    the user excludes the rows where `a` is missing. Nothing failed; the record says so."""
    df = pd.DataFrame({
        "a": [np.nan] * 4 + [float(i) for i in range(6)],
        "b": [np.nan] * 3 + [float(i * 10) for i in range(7)],  # 30%: no pause of its own
        "k": list("abcdefghij"),
    })
    answered = [_answered(_mv_question("a", "median"), "exclude_rows", df)]
    outcome, saved, _, _ = _run_cleaner(df, _report([_op("b", "leave_missing")]), answered)
    assert not isinstance(outcome, Exception), outcome
    assert len(saved) == 6 and saved["b"].isna().sum() == 0
    [record] = _records_for(outcome, "b")
    assert record["action"] == (
        "Cleaner decision: left the 3 missing values in `b` unchanged (nothing imputed, no rows removed); "
        "3 of those rows were later removed by the user's row exclusion"
    )
    assert outcome["cleaning_report"]["re_profile_verification"]["discrepancies"] == []


def test_a_mode_fill_that_narrows_an_object_true_false_column_is_not_a_failure() -> None:
    """Code Review finding 3: True/False with blanks loads as object; pandas narrows it to
    bool once filled. That is not a failed check; a numeric column turning non-numeric is."""
    df = pd.read_csv(io.StringIO("k,x\n" + "\n".join(f"{i},{v}" for i, v in enumerate(["True", "False", "True", "", "True"]))))
    assert df["x"].dtype == object
    with pytest.warns(FutureWarning):  # pandas' own deprecation of fillna downcasting
        frame, _, [record], _, discrepancies = _run_ops(df, [_op("x", "fill_missing", {"method": "mode"})])
    assert frame["x"].isna().sum() == 0
    assert record["action"].startswith("Cleaner decision: filled the 1 missing values in `x` with the mode")
    assert discrepancies == []


@pytest.mark.parametrize(
    "values, dtype, expected",
    [
        (["a", None, "b"], None, True),
        ([None, None], "object", True),
        ([True, None, False], None, False),  # Python bools with gaps load as object, not text
        (["a", 1, None], None, False),
        (["a", None], "string", True),
        ([1, 2], None, False),
    ],
)
def test_is_text_column_means_every_recorded_value_is_text(values, dtype, expected) -> None:
    from backend.agents.cleaner import _is_text_column
    assert _is_text_column(pd.Series(values, dtype=dtype)) is expected


@pytest.mark.parametrize(
    "series",
    [
        pd.Series(pd.to_datetime(["2024-01-01", None, "2024-02-01"])),
        pd.Series([1, None, 3], dtype="Int64"),
    ],
    ids=["datetime", "Int64"],
)
def test_convert_to_string_really_converts_dates_and_nullable_integers(series) -> None:
    """Second Code Review, finding 1: `where` kept datetime64/Int64, so the conversion
    did nothing while being reported as run."""
    df = pd.DataFrame({"c": series, "k": list("abc")})
    frame, _, [record], _, discrepancies = _run_ops(df, [_op("c", "convert_type", {"to": "string"})])
    assert frame["c"].dtype == object and frame["c"].isna().tolist() == [False, True, False]
    assert all(isinstance(v, str) for v in frame["c"].dropna())
    assert record["action"].startswith(f"Cleaner decision: converted `c` from {series.dtype} to object (string)")
    assert discrepancies == []


def test_the_contract_record_counts_every_decision_in_the_report() -> None:
    """Second Code Review, finding 2: dropped decisions still count toward the total."""
    df = _messy()
    report = _routed(
        [_op("revenue", "fill_missing", {"method": "mean"}), _op("revenue", "leave_missing"),
         {"column_name": "units_sold", "issue": "i", "action": "filled with median", "reason": "r"}],
        ("revenue", "none"),
    )
    outcome, _, _, _ = _run_cleaner(df, report, _missing_answered(df))
    assert outcome["cleaning_report"]["decisions"][0]["issue"] == (
        "1 of the 3 decisions in the Cleaner's report did not name a valid operation"
    )


# ---------------------------------------------------------------------------
# Group 13 — fills on a column whose outliers only the user answered (Build G,
# approved after Code Review finding 5)
# ---------------------------------------------------------------------------


def test_executor_order_runs_the_cleaners_fills_before_the_users_outlier_choices() -> None:
    """The ordering the change relies on, checked on the executor itself (no filter):
    the fill touches only the originally missing value, with the outliers still present
    (as they were when the user was asked), and the values the user then excludes as
    outliers stay missing."""
    df = _amount_frame()  # amount: one gap (row 11), outliers at rows 8 and 13
    resolutions = build_cleaner_resolutions([_answered(_outlier_question("amount"), "flag_as_suspected_error", df)])
    masks = {"amount": _iqr_outlier_mask(df["amount"])}
    items = plan_model_decisions([_op("amount", "fill_missing", {"method": "median"})], df)
    shown = _distinct_value_columns(df)
    frame, _, _ = remove_duplicate_rows(df)
    # As cleaner_node passes them: the values the user excluded as outliers.
    frame = run_model_operations(frame, items, _MODEL_PHASES_BEFORE_USER, df, shown, masks)
    # Filled before the user's choice runs, with a median computed without the
    # excluded values (15; with them it would be 16).
    assert frame.loc[11, "amount"] == 15.0 and frame["amount"].isna().sum() == 0
    frame, *_ = apply_user_decisions(frame, resolutions, masks)
    frame = run_model_operations(frame, items, _MODEL_PHASES_AFTER_USER, df, shown, masks)
    assert frame.index[frame["amount"].isna()].tolist() == [8, 13]
    assert frame.loc[11, "amount"] == 15.0
    assert frame.index[frame["amount_outlier_flag"] == 1].tolist() == [8, 13]
    assert "fill" in _MODEL_PHASES_BEFORE_USER and "fill" not in _MODEL_PHASES_AFTER_USER


def _outlier_only(df: pd.DataFrame) -> list:
    return [_answered(_outlier_question("amount"), "flag_as_suspected_error", df)]


def test_a_fill_runs_and_is_recorded_where_the_user_answered_only_the_outlier_pause() -> None:
    df = _amount_frame()
    outcome, saved, _, _ = _run_cleaner(
        df, _report([_op("amount", "fill_missing", {"method": "median"})]), _outlier_only(df)
    )
    assert not isinstance(outcome, Exception), outcome
    assert saved.loc[11, "amount"] == 15.0
    actions = [d["action"] for d in _records_for(outcome, "amount")]
    assert actions[0] == (
        "Cleaner decision: filled the 1 missing values in `amount` with the median (15), "
        "computed without the 2 value(s) the user excluded as outliers"
    )
    assert actions[1].startswith("User decision (financial outlier pause): removed the 2 outlier value(s)")
    summary = outcome["cleaning_report"]["operations_summary"]
    assert (summary["executed"], summary["dropped_on_user_decided_columns"]) == (1, 0)


def test_the_values_the_user_excluded_as_outliers_stay_missing_after_the_fill() -> None:
    df = _amount_frame()
    outcome, saved, _, _ = _run_cleaner(
        df, _report([_op("amount", "fill_missing", {"method": "median"})]), _outlier_only(df)
    )
    assert saved.index[saved["amount"].isna()].tolist() == [8, 13]
    assert saved.index[saved["amount_outlier_flag"] == 1].tolist() == [8, 13]
    assert outcome["cleaning_report"]["re_profile_verification"]["discrepancies"] == []


def test_leave_missing_runs_where_the_user_answered_only_the_outlier_pause() -> None:
    """The user's exclusion adds missing values later; the re-check is by row, so the
    record is not a false failure."""
    df = _amount_frame()
    outcome, saved, _, _ = _run_cleaner(df, _report([_op("amount", "leave_missing")]), _outlier_only(df))
    [record] = [d for d in _records_for(outcome, "amount") if d["action"].startswith("Cleaner decision")]
    assert record["action"] == (
        "Cleaner decision: left the 1 missing values in `amount` unchanged (nothing imputed, no rows removed)"
    )
    assert saved["amount"].isna().sum() == 3
    assert outcome["cleaning_report"]["re_profile_verification"]["discrepancies"] == []


@pytest.mark.parametrize("with_outlier_answer", [False, True], ids=["missing-only", "missing-and-outlier"])
@pytest.mark.parametrize("operation, params", [("fill_missing", {"method": "median"}), ("leave_missing", {})])
def test_no_change_where_the_user_answered_the_missing_value_pause(operation, params, with_outlier_answer) -> None:
    """The user's missing-value choice decides the gaps: the Cleaner's fill or
    leave_missing on that column is still dropped."""
    df = _amount_frame()
    answered = [_answered(_mv_question("amount", "median"), "preserve_missingness", df)]
    if with_outlier_answer:
        answered += _outlier_only(df)
    outcome, saved, _, _ = _run_cleaner(df, _report([_op("amount", operation, params)]), answered)
    assert not isinstance(outcome, Exception), outcome
    assert pd.isna(saved.loc[11, "amount"])
    assert not [d for d in _records_for(outcome, "amount") if d["action"].startswith("Cleaner decision")]
    assert outcome["cleaning_report"]["operations_summary"]["dropped_on_user_decided_columns"] == 1



def test_a_mean_fill_never_uses_the_outliers_the_user_excluded_as_errors() -> None:
    """Scoped Code Review finding: the fill runs before the user's choice, so without this
    rule a mean fill would write ~243 (built from the 1,000 and 2,000 the user rejected)
    into a column whose real values run 10-20."""
    df = _amount_frame()
    outcome, saved, _, _ = _run_cleaner(
        df, _report([_op("amount", "fill_missing", {"method": "mean"})]), _outlier_only(df)
    )
    assert saved.loc[11, "amount"] == 15.0
    assert saved.index[saved["amount"].isna()].tolist() == [8, 13]
    [fill] = [d for d in _records_for(outcome, "amount") if d["action"].startswith("Cleaner decision")]
    assert fill["action"].endswith("with the mean (15), computed without the 2 value(s) the user excluded as outliers")


@pytest.mark.parametrize("option_id", ["treat_as_valid"])
def test_outliers_the_user_kept_as_valid_count_in_the_fill(option_id) -> None:
    df = _amount_frame()
    answered = [_answered(_outlier_question("amount"), option_id, df)]
    outcome, saved, _, _ = _run_cleaner(df, _report([_op("amount", "fill_missing", {"method": "mean"})]), answered)
    expected = df["amount"].mean()  # 3165 / 13, the outliers included: the user ruled them valid
    assert saved.loc[11, "amount"] == pytest.approx(expected)
    assert saved.loc[[8, 13], "amount"].tolist() == [1000.0, 2000.0]
    [fill] = [d for d in _records_for(outcome, "amount") if d["action"].startswith("Cleaner decision")]
    assert "excluded as outliers" not in fill["action"]
