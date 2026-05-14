"""Tests for backend/agents/profiler.py.

All tests run from the project root (CWD must be the repo root) because
load_system_prompt resolves paths relative to CWD.

Note: PipelineState is NOT imported and NOT used in any test.
build_profiler_message takes (df: pd.DataFrame, context: Optional[str]) directly.

Integration tests requiring a live ANTHROPIC_API_KEY and Supabase are skipped.
"""

import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from backend.agents.profiler import (
    build_profiler_message,
    load_system_prompt,
    parse_json_response,
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
