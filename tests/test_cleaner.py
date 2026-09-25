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
    build_cleaner_resolutions,
    classify_cleaning_decision,
    cleaner_node,
    detect_interactions,
    execute_cleaning_operations,
    filter_user_decided,
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
    assert result["cleaning_report"]["summary"]["rows_after"] == 20


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
DEDUPE = {
    "column_name": None,
    "issue": "15 exact duplicate rows present",
    "action": "removed all exact duplicate rows",
    "reason": "duplicates would inflate every count",
}
# Model-written decisions for user-decided revenue that keyword routing would
# misexecute: mean-fill ("means"), nothing ("Removed"/backticks), a 0 fill.
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


def _run_cleaner(df: pd.DataFrame, llm_payload: dict, answered: list | None = None) -> tuple:
    """Run cleaner_node with every external service mocked.

    Returns (result or raised exception, the frame written to parquet or None,
    Supabase update payloads, the LLM create mock).
    """
    saved: dict = {}
    captured: list[dict] = []
    reply = MagicMock()
    reply.content = [MagicMock(text=json.dumps(llm_payload))]
    state = {
        "analysis_id": "test-analysis-id",
        "stored_filename": "messy.csv",
        "profile_report": {},
        "profiler_domain_hypothesis": "retail",
        "profiler_provenance_hypothesis": "system export",
        "profiler_top_3_concerns": [],
        "answered_cleaner_pauses": answered or [],
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


@pytest.mark.parametrize(
    "action, issue, op",
    [
        ("fill median", "", "median"),
        ("a mean is meaningless; convert to string", "", "mean"),
        ("Exclude `notes` from analysis entirely", "", "unmatched"),
        ("Removed the 4 outlier values", "", "outlier_noop"),
        ("flag outliers", "", "outlier_flag"),
        ("convert to category", "", "dtype"),
    ],
)
def test_classify_cleaning_decision_names_what_the_keywords_trigger(action, issue, op) -> None:
    assert classify_cleaning_decision({"column_name": "c", "action": action, "issue": issue}) == op


def test_classify_cleaning_decision_dataset_level_is_dedupe() -> None:
    assert classify_cleaning_decision({"column_name": None, "action": "anything"}) == "dedupe"


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


def test_filter_drops_every_model_decision_on_a_user_decided_column() -> None:
    df = _messy()
    resolutions = build_cleaner_resolutions([_answered(_outlier_question(), "treat_as_valid", df)])
    # §8 requires an outlier issue to state its SD distance "from the mean", which the
    # keyword router reads as a mean fill — so the filter is by column, not by guessed op.
    sd_issue = {"column_name": "revenue", "issue": "4 values 6.8 SD from the mean", "action": "flag and include"}
    convert = {"column_name": "revenue", "issue": "stored as text", "action": "convert to float"}
    drop = {"column_name": "revenue", "issue": "outliers", "action": "drop column"}
    other = {"column_name": "units_sold", "issue": "8% missing", "action": "fill median"}
    decisions = [DEDUPE, sd_issue, convert, drop, *ADVERSARIAL_REVENUE, other]
    assert classify_cleaning_decision(sd_issue) == "mean"
    assert filter_user_decided(decisions, resolutions) == [DEDUPE, other]


def test_an_outlier_answer_on_a_column_the_user_later_excluded_is_recorded_not_run() -> None:
    """Out of the prompt's order (e.g. via the backstop): the outlier question was answered
    first, then the column was excluded. The run completes and nothing is claimed."""
    df = _messy()
    answered = [
        _answered(_outlier_question(), "flag_as_suspected_error", df),
        _answered(_mv_question(), "exclude_column", df),
        _notes_preserved(df),
    ]
    outcome, saved, _, _ = _run_cleaner(df, _report([DEDUPE]), answered)
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

    outcome, saved, _, _ = _run_cleaner(df, _report([DEDUPE, *ADVERSARIAL_REVENUE]), answered)

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
    outcome, saved, _, _ = _run_cleaner(df, _report([DEDUPE]), answered)
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

    outcome, saved, _, _ = _run_cleaner(df, _report([DEDUPE, *ADVERSARIAL_OUTLIERS]), answered)

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

    outcome, saved, _, _ = _run_cleaner(df, _report([DEDUPE]), answered)

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
    outcome, saved, captured, _ = _run_cleaner(_messy(), _report([DEDUPE]))
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
    outcome, _, captured, _ = _run_cleaner(df, _report([DEDUPE]), answered)

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
    _, _, _, create = _run_cleaner(df, _routed([DEDUPE], ("revenue", "none")), _missing_answered(df))
    message = _sent_message(create)
    assert message["outlier_review_columns"] == ["revenue"]
    assert message["column_info"]["revenue"]["outlier_count"] == 4

    answered = _missing_answered(df) + [_answered(_outlier_question(), "treat_as_valid", df)]
    _, _, _, create = _run_cleaner(df, _report([DEDUPE]), answered)
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
        df, _routed([DEDUPE], ("revenue", "financial")), _missing_answered(df)
    )
    assert saved is None
    assert [p["status"] for p in captured] == ["cleaning"]
    stored = outcome["outlier_pause_data"]
    assert (stored["column_name"], stored["outlier_count"], stored["sd_distance"]) == ("revenue", 4, 6.79)
    assert stored["financial_context_note"].startswith("Not assessed.")


def test_an_answered_or_excluded_column_is_never_paused_again_whatever_the_routing() -> None:
    df = _messy()
    answered = _missing_answered(df) + [_answered(_outlier_question(), "flag_as_suspected_error", df)]
    outcome, saved, _, _ = _run_cleaner(df, _routed([DEDUPE], ("revenue", "financial")), answered)
    assert not isinstance(outcome, Exception), outcome
    assert saved.index[saved["revenue_outlier_flag"] == 1].tolist() == OUTLIER_ROWS
    assert _system_records(outcome, "revenue") == []  # the user's decision is the record

    excluded = [_answered(_mv_question(), "exclude_column", df), _notes_preserved(df)]
    outcome, saved, _, _ = _run_cleaner(df, _routed([DEDUPE], ("revenue", "financial")), excluded)
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
    report = _report([DEDUPE])
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
    outcome, _, captured, _ = _run_cleaner(df, _report([DEDUPE, FLAG_INCLUDE_SD]), _missing_answered(df))
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
        df, _routed([DEDUPE, FLAG_INCLUDE_SD], ("revenue", "none")), _missing_answered(df)
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


def test_the_record_contradicts_a_model_decision_the_keyword_router_misran() -> None:
    """Addition 2: on a column the user did not decide, the model's 'flagged' decision runs
    a mean fill (its issue says "from the mean"); the system record says what is true."""
    df = _amount_frame()
    model = {"column_name": "amount", "issue": "2 values 3.1 SD from the mean",
             "action": "flagged as potential process events; included with annotation", "reason": "r"}
    outcome, saved, _, _ = _run_cleaner(df, _routed([model], ("amount", "none")))
    assert not isinstance(outcome, Exception), outcome
    assert model in outcome["cleaning_report"]["decisions"]  # the model's claim is still reported
    assert saved["amount"].isna().sum() == 0 and "amount_outlier_flag" not in saved.columns
    [record] = _system_records(outcome, "amount")
    assert record["reason"].startswith(
        "Computed from the cleaned data: 2 of the 2 value(s) are unchanged; they are not flagged."
    )
    assert "this record is the accurate one" in record["reason"]


def test_the_record_reports_a_flag_the_model_decision_did_add() -> None:
    df = _amount_frame()
    model = {"column_name": "amount", "issue": "2 extreme values", "action": "flag outliers", "reason": "r"}
    outcome, saved, _, _ = _run_cleaner(df, _routed([model], ("amount", "none")))
    [record] = _system_records(outcome, "amount")
    assert saved.index[saved["amount_outlier_flag"] == 1].tolist() == [8, 13]
    assert record["reason"].startswith(
        "Computed from the cleaned data: 2 of the 2 value(s) are unchanged; "
        "2 of them are marked in `amount_outlier_flag`."
    )


def test_the_record_counts_an_outlier_removed_with_a_duplicate_row() -> None:
    df = _amount_frame()
    df.loc[14] = df.loc[8]  # a duplicate of an outlier row
    outcome, saved, _, _ = _run_cleaner(df, _routed([DEDUPE], ("amount", "none")))
    assert 14 not in saved.index
    [record] = _system_records(outcome, "amount")
    assert record["issue"].startswith("3 value(s) in `amount`")
    assert record["reason"].startswith(
        "Computed from the cleaned data: 2 of the 3 value(s) are unchanged; 1 were removed with "
        "their rows or changed by other cleaning decisions; they are not flagged."
    )


def test_the_record_never_raises_on_a_converted_column() -> None:
    df = _amount_frame()
    model = {"column_name": "amount", "issue": "numbers", "action": "convert to string", "reason": "r"}
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

