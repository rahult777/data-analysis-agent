"""Tests for backend/tools/viz_tools.py chart-title handling.

Covers: the _short_name truncation helper and generate_scatter_plot's title
recipe (line break, font size, automargin, container-referenced y), including
the adversarial case of two very long column names. Charts are written to
CHARTS_DIR and removed afterwards.
"""

import json
import re

import pandas as pd
import pytest

from backend.tools import viz_tools
from backend.tools.viz_tools import _short_name, generate_scatter_plot

LONG_X = "extremely_long_measurement_column_name_for_x_axis"
LONG_Y = "equally_long_measurement_column_name_for_y_axis"


@pytest.fixture
def small_df() -> pd.DataFrame:
    return pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.1, 5.9, 8.2]})


@pytest.fixture
def written_charts() -> list:
    """Collect chart filenames created by a test and delete them afterwards."""
    created: list = []
    yield created
    for filename in created:
        path = viz_tools.CHARTS_DIR / filename
        if path.exists():
            path.unlink()


def chart_layout_title(filename: str) -> dict:
    """Return the parsed layout.title object from a written chart.

    Brace-matches every "title":{...} in the embedded plotly JSON and picks the
    main title (the only one whose text contains " vs"); the others are axis
    titles. Parsing the raw JSON also undoes plotly's \\u003c escaping of <.
    """
    html = (viz_tools.CHARTS_DIR / filename).read_text(encoding="utf-8")
    titles = []
    for match in re.finditer(r'"title":\{', html):
        start = match.end() - 1
        depth = 0
        for i in range(start, len(html)):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    titles.append(json.loads(html[start : i + 1]))
                    break
    main = [t for t in titles if " vs" in str(t.get("text", ""))]
    assert len(main) == 1, f"expected exactly one main title, found {titles}"
    return main[0]


# ---------------------------------------------------------------------------
# _short_name
# ---------------------------------------------------------------------------


def test_short_name_leaves_short_names_untouched() -> None:
    assert _short_name("sepal_length") == "sepal_length"


def test_short_name_leaves_exactly_limit_untouched() -> None:
    name = "x" * 26
    assert _short_name(name) == name
    assert len(_short_name(name)) == 26


def test_short_name_truncates_above_limit() -> None:
    name = "x" * 27
    result = _short_name(name)
    assert result != name
    assert len(result) == 26
    assert result.endswith("…")


def test_short_name_never_exceeds_limit() -> None:
    assert len(_short_name(LONG_X)) == 26


def test_short_name_respects_custom_limit() -> None:
    assert len(_short_name(LONG_X, limit=10)) == 10


# ---------------------------------------------------------------------------
# generate_scatter_plot — title recipe
# ---------------------------------------------------------------------------


def test_scatter_plot_is_written(small_df: pd.DataFrame, written_charts: list) -> None:
    filename = generate_scatter_plot(small_df, "a", "b", "testviz", 0.99)
    assert filename is not None
    written_charts.append(filename)
    assert (viz_tools.CHARTS_DIR / filename).exists()


def test_scatter_title_carries_the_recipe(
    small_df: pd.DataFrame, written_charts: list
) -> None:
    filename = generate_scatter_plot(small_df, "a", "b", "testviz", 0.99)
    assert filename is not None
    written_charts.append(filename)
    title = chart_layout_title(filename)
    assert title["text"] == "a vs<br>b (r=0.99)"
    assert title["automargin"] is True
    assert title["yref"] == "container"
    assert title["font"]["size"] == 14


def test_scatter_title_truncates_two_long_names(
    small_df: pd.DataFrame, written_charts: list
) -> None:
    """Adversarial case: both column names far exceed the 26-character limit."""
    df = small_df.rename(columns={"a": LONG_X, "b": LONG_Y})
    filename = generate_scatter_plot(df, LONG_X, LONG_Y, "testviz", -0.42)
    assert filename is not None
    written_charts.append(filename)
    title = chart_layout_title(filename)
    expected = f"{_short_name(LONG_X)} vs<br>{_short_name(LONG_Y)} (r=-0.42)"
    assert title["text"] == expected
    # the untruncated names must not reach the title
    assert LONG_X not in title["text"]
    assert LONG_Y not in title["text"]
    assert title["automargin"] is True
    assert title["yref"] == "container"
    assert title["font"]["size"] == 14


def test_scatter_plot_returns_none_on_bad_column(small_df: pd.DataFrame) -> None:
    assert generate_scatter_plot(small_df, "missing", "b", "testviz", 0.5) is None
