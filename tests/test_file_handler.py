"""Tests for backend/utils/file_handler.py — validate_file.

Every input is built in memory (XLSX via openpyxl) or read from tests/fixtures/.
No network, no Supabase, no Anthropic calls.

All tests run from the project root (CWD must be the repo root) because importing
file_handler creates its temp directory relative to CWD.
"""

import io
import logging
import pathlib
from unittest.mock import MagicMock

import pandas as pd
import pytest
from openpyxl import Workbook

from backend.utils import file_handler
from backend.utils.file_handler import validate_file

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
VALID_CSV = (FIXTURES_DIR / "iris.csv").read_bytes()

# First eight bytes of every OLE2 compound document; pandas routes these to xlrd.
OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def make_xlsx(rows: list[list[object]]) -> bytes:
    """Return an in-memory .xlsx whose first sheet holds rows; [] leaves a blank row."""
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rejection_message(filename: str, content: bytes) -> str:
    """Call validate_file expecting a rejection and return its message."""
    with pytest.raises(ValueError) as exc_info:
        validate_file(filename, content)
    return str(exc_info.value)


# ---------------------------------------------------------------------------
# Group 1 — Empty and header-only files are rejected
# ---------------------------------------------------------------------------


def test_rejects_zero_byte_csv() -> None:
    """A 0-byte CSV (a direct API call skips the frontend's size check) is rejected as empty."""
    message = rejection_message("data.csv", b"")
    assert message.startswith("USER_ERROR:")
    assert "empty" in message.lower()


def test_rejects_whitespace_only_csv() -> None:
    """Blank lines only: pandas raises EmptyDataError, which counts as no data."""
    content = b"\n\n   \n"
    with pytest.raises(pd.errors.EmptyDataError):
        pd.read_csv(io.BytesIO(content), nrows=1)  # this input takes the EmptyDataError path

    message = rejection_message("data.csv", content)
    assert message.startswith("USER_ERROR:")
    assert "no data rows" in message


def test_rejects_header_only_csv() -> None:
    """Valid headers with zero data rows are rejected before any record or LLM call."""
    message = rejection_message("data.csv", b"sepal_length,sepal_width,species\n")
    assert message.startswith("USER_ERROR:")
    assert "no data rows" in message


def test_rejects_header_only_xlsx() -> None:
    """Same as the CSV case, through the read_excel branch."""
    content = make_xlsx([["sepal_length", "sepal_width", "species"]])
    message = rejection_message("data.xlsx", content)
    assert message.startswith("USER_ERROR:")
    assert "no data rows" in message


def test_rejects_empty_xlsx_workbook() -> None:
    """A workbook with no cells at all (0 rows, 0 columns) is rejected."""
    message = rejection_message("data.xlsx", make_xlsx([]))
    assert message.startswith("USER_ERROR:")
    assert "no data rows" in message


# ---------------------------------------------------------------------------
# Group 2 — Files with data rows pass
# ---------------------------------------------------------------------------


def test_accepts_valid_csv() -> None:
    """The iris fixture has data rows and passes."""
    validate_file("iris.csv", VALID_CSV)


def test_accepts_valid_xlsx() -> None:
    """A header plus one data row passes through the read_excel branch."""
    validate_file("data.xlsx", make_xlsx([["region", "sales"], ["east", 10]]))


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([["region", "sales"], [], ["east", 10]], id="header-blank-data"),
        pytest.param(
            [["Sales Report 2024"], [], ["region", "sales"], ["east", 10]],
            id="title-blank-table",
        ),
    ],
)
def test_accepts_xlsx_with_blank_second_row(rows: list[list[object]]) -> None:
    """A blank second row must not hide the data below it.

    pandas' nrows=1 read covers only the first two sheet rows and drops trailing blank
    ones, so it comes back empty for these layouts although the Profiler's full read
    finds data rows.
    """
    content = make_xlsx(rows)
    assert pd.read_excel(io.BytesIO(content), nrows=1).empty  # the peek alone would reject

    validate_file("report.xlsx", content)


# ---------------------------------------------------------------------------
# Group 3 — Files the peek cannot read pass through unchanged (fail-open)
# ---------------------------------------------------------------------------


def test_undecodable_csv_passes_through(caplog: pytest.LogCaptureFixture) -> None:
    """A non-UTF-8 CSV is not rejected here; the pipeline handles it exactly as today."""
    content = "city,temperature\nMontréal,21\n".encode("latin-1")
    with pytest.raises(UnicodeDecodeError):
        pd.read_csv(io.BytesIO(content), nrows=1)  # the peek itself cannot read it

    with caplog.at_level(logging.WARNING, logger="backend.utils.file_handler"):
        validate_file("latin1.csv", content)

    assert "latin1.csv" in caplog.text


def test_unreadable_xls_passes_through(caplog: pytest.LogCaptureFixture) -> None:
    """An .xls the peek cannot open is not rejected here; the pipeline handles it as today.

    Today pandas raises ImportError because xlrd is not installed. That is not a
    ValueError, so it would surface as a 500 if it escaped validate_file.
    """
    content = OLE2_SIGNATURE + b"\x00" * 1000
    # Exception, not ImportError: once xlrd is installed this becomes a parse error.
    with pytest.raises(Exception):
        pd.read_excel(io.BytesIO(content), nrows=1)

    with caplog.at_level(logging.WARNING, logger="backend.utils.file_handler"):
        validate_file("legacy.xls", content)

    assert "legacy.xls" in caplog.text


# ---------------------------------------------------------------------------
# Group 4 — Existing type and size checks are unchanged
# ---------------------------------------------------------------------------


def test_rejects_unsupported_extension() -> None:
    """Keeps the documented message (docs/infrastructure.md, pipeline Step 2)."""
    assert rejection_message("report.txt", b"hello world") == (
        "USER_ERROR: Unsupported file type. Please upload a CSV or Excel file."
    )


def test_rejects_oversized_file_without_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Size is checked before the data-row peek, so an oversized file is never parsed."""
    peek = MagicMock(return_value=False)
    monkeypatch.setattr(file_handler, "_has_no_data_rows", peek)
    monkeypatch.setattr(file_handler, "MAX_FILE_SIZE", len(VALID_CSV) - 1)

    assert rejection_message("iris.csv", VALID_CSV) == (
        "USER_ERROR: File too large. Maximum supported file size is 100MB."
    )
    peek.assert_not_called()


def test_accepts_file_at_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The limit is inclusive: a file of exactly MAX_FILE_SIZE bytes passes."""
    monkeypatch.setattr(file_handler, "MAX_FILE_SIZE", len(VALID_CSV))
    validate_file("iris.csv", VALID_CSV)
