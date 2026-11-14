"""Tests for backend/tools/viz_tools.py's interactive (plotly) charts.

Covers: the _short_name truncation helper; the title recipe of
generate_scatter_plot and generate_line_chart (column names cut at 19
characters, font size 14, plotly's default title placement, fixed margins),
including the adversarial case of very long column names; the HTML both
write (the shared plotly.min.js beside the chart instead of an inlined
bundle, the fixed div id, no download button or logo, no UUID but the
analysis id, the same bytes on every run); and how both files are written
(the bundle pinned by its sha256 and replaced when missing or damaged, an
intact one left as it is, nothing written for a plotly whose bundle is not
the pinned one, every file renamed into place from a hidden temporary name
with the permissions a plain write gives, and no partial or temporary file
left by an error). Charts are written to a per-test CHARTS_DIR under
tmp_path, never to backend/outputs/charts.
"""

import errno
import hashlib
import json
import logging
import os
import pathlib
import re
import stat
from typing import Callable, Optional

import pandas as pd
import plotly.io._html as plotly_html  # where plotly's write_html reads the bundle it writes in "directory" mode
import pytest
from plotly.offline import get_plotlyjs

from backend.tools import viz_tools
from backend.tools.viz_tools import _short_name, generate_line_chart, generate_scatter_plot

LONG_X = "extremely_long_measurement_column_name_for_x_axis"
LONG_Y = "equally_long_measurement_column_name_for_y_axis"

# A UUID-shaped analysis id, as real charts have ("testviz" is not one).
ANALYSIS_ID = "5b3f6d1e-8c2a-4e9b-a7d4-1f0e2c3b4a59"
OTHER_ID = "7a2c9e4b-1d3f-4a6b-8c5e-2f0d9b7e1a34"

MARGIN = {"t": 80, "l": 60, "r": 20, "b": 50}

SHARED_PLOTLY_TAG = '<script charset="utf-8" src="plotly.min.js"></script>'

# The patterns frontend/lib/snapshot-rules.mjs applies (UUID_SHAPED, PLOTLY_HEADER).
UUID_SHAPED = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
PLOTLY_HEADER = re.compile(r"^/\*+[\s*]*plotly\.js v\d")


@pytest.fixture(autouse=True)
def charts_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Every chart a test writes goes to tmp_path; the real chart directory is never touched."""
    monkeypatch.setattr(viz_tools, "CHARTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def small_df() -> pd.DataFrame:
    return pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.1, 5.9, 8.2]})


@pytest.fixture
def ts_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "day": pd.date_range("2024-01-01", periods=5, freq="D"),
            "value": [3.0, 1.0, 4.0, 1.0, 5.0],
        }
    )


@pytest.fixture
def written_charts() -> list:
    """Collect chart filenames created by a test and delete them afterwards."""
    created: list = []
    yield created
    for filename in created:
        path = viz_tools.CHARTS_DIR / filename
        if path.exists():
            path.unlink()


@pytest.fixture(params=["scatter", "line"])
def interactive_chart(
    request: pytest.FixtureRequest, small_df: pd.DataFrame, ts_df: pd.DataFrame
) -> Callable[[str], Optional[str]]:
    """Writes one interactive chart for an analysis id and returns its filename."""
    if request.param == "scatter":
        return lambda analysis_id: generate_scatter_plot(small_df, "a", "b", analysis_id, 0.99)
    return lambda analysis_id: generate_line_chart(ts_df, "day", "value", analysis_id)


def newplot_args(filename: str) -> tuple[str, list, dict, dict]:
    """Return the four Plotly.newPlot( arguments of a written chart: div id, data, layout, config.

    Reads the last Plotly.newPlot( call (an inlined plotly bundle contains the
    string too) and decodes its JSON arguments in order; decoding the raw JSON
    also undoes plotly's \\u003c escaping of <.
    """
    html = (viz_tools.CHARTS_DIR / filename).read_text(encoding="utf-8")
    pos = html.rindex("Plotly.newPlot(") + len("Plotly.newPlot(")
    decoder = json.JSONDecoder()
    args = []
    for _ in range(4):
        while html[pos] in ", \n\t":
            pos += 1
        value, pos = decoder.raw_decode(html, pos)
        args.append(value)
    assert html[pos:].lstrip().startswith(")"), "Plotly.newPlot( has more than four arguments"
    div_id, data, layout, config = args
    return div_id, data, layout, config


def foreign_uuids(path: pathlib.Path, own_id: Optional[str]) -> set:
    """Every UUID-shaped string in a file, lower-cased, other than own_id (read as the snapshot build reads it)."""
    text = path.read_text(encoding="latin1")
    return {match.lower() for match in UUID_SHAPED.findall(text)} - {own_id}


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
    _, _, layout, _ = newplot_args(filename)
    title = layout["title"]
    assert title["text"] == "a vs<br>b (r=0.99)"
    assert "automargin" not in title
    assert "yref" not in title
    assert title["font"]["size"] == 14
    assert layout["margin"] == MARGIN


def test_scatter_title_truncates_two_long_names(
    small_df: pd.DataFrame, written_charts: list
) -> None:
    """Adversarial case: both column names far exceed the 19-character title limit."""
    df = small_df.rename(columns={"a": LONG_X, "b": LONG_Y})
    filename = generate_scatter_plot(df, LONG_X, LONG_Y, "testviz", -0.42)
    assert filename is not None
    written_charts.append(filename)
    _, _, layout, _ = newplot_args(filename)
    title = layout["title"]
    expected = "extremely_long_mea… vs<br>equally_long_measu… (r=-0.42)"
    assert title["text"] == expected
    # the untruncated names must not reach the title
    assert LONG_X not in title["text"]
    assert LONG_Y not in title["text"]
    assert "automargin" not in title
    assert "yref" not in title
    assert title["font"]["size"] == 14
    assert layout["margin"] == MARGIN


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("abcdefghijklmnopqrs", "abcdefghijklmnopqrs"),  # 19 characters: whole
        ("abcdefghijklmnopqrst", "abcdefghijklmnopqr…"),  # 20 characters: cut to 19
    ],
)
def test_scatter_title_cuts_names_after_19_characters(
    small_df: pd.DataFrame, name: str, shown: str
) -> None:
    df = small_df.rename(columns={"a": name})
    filename = generate_scatter_plot(df, name, "b", ANALYSIS_ID, 0.5)
    assert filename is not None
    _, _, layout, _ = newplot_args(filename)
    assert layout["title"]["text"] == f"{shown} vs<br>b (r=0.50)"


def test_scatter_plot_returns_none_on_bad_column(small_df: pd.DataFrame) -> None:
    assert generate_scatter_plot(small_df, "missing", "b", "testviz", 0.5) is None


# ---------------------------------------------------------------------------
# generate_line_chart — title recipe
# ---------------------------------------------------------------------------


def test_line_chart_is_written(ts_df: pd.DataFrame) -> None:
    filename = generate_line_chart(ts_df, "day", "value", ANALYSIS_ID)
    assert filename == f"{ANALYSIS_ID}_linechart_value.html"
    assert (viz_tools.CHARTS_DIR / filename).exists()


def test_line_title_carries_the_recipe(ts_df: pd.DataFrame) -> None:
    filename = generate_line_chart(ts_df, "day", "value", ANALYSIS_ID)
    assert filename is not None
    _, _, layout, _ = newplot_args(filename)
    title = layout["title"]
    assert title["text"] == "value Over Time"
    assert "automargin" not in title
    assert "yref" not in title
    assert title["font"]["size"] == 14
    assert layout["margin"] == MARGIN


def test_line_title_truncates_a_long_name(ts_df: pd.DataFrame) -> None:
    """Adversarial case: the value column's name far exceeds the 19-character title limit."""
    df = ts_df.rename(columns={"value": LONG_Y})
    filename = generate_line_chart(df, "day", LONG_Y, ANALYSIS_ID)
    assert filename is not None
    _, _, layout, _ = newplot_args(filename)
    assert layout["title"]["text"] == "equally_long_measu… Over Time"
    assert LONG_Y not in layout["title"]["text"]


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("abcdefghijklmnopqrs", "abcdefghijklmnopqrs"),  # 19 characters: whole
        ("abcdefghijklmnopqrst", "abcdefghijklmnopqr…"),  # 20 characters: cut to 19
    ],
)
def test_line_title_cuts_names_after_19_characters(
    ts_df: pd.DataFrame, name: str, shown: str
) -> None:
    df = ts_df.rename(columns={"value": name})
    filename = generate_line_chart(df, "day", name, ANALYSIS_ID)
    assert filename is not None
    _, _, layout, _ = newplot_args(filename)
    assert layout["title"]["text"] == f"{shown} Over Time"


def test_line_chart_returns_none_on_bad_column(ts_df: pd.DataFrame) -> None:
    assert generate_line_chart(ts_df, "day", "missing", ANALYSIS_ID) is None
    assert generate_line_chart(ts_df, "missing", "value", ANALYSIS_ID) is None


# ---------------------------------------------------------------------------
# The HTML both interactive charts write
# ---------------------------------------------------------------------------


def test_chart_loads_the_shared_plotly_instead_of_inlining_it(
    interactive_chart: Callable[[str], Optional[str]]
) -> None:
    filename = interactive_chart(ANALYSIS_ID)
    assert filename is not None
    path = viz_tools.CHARTS_DIR / filename
    html = path.read_text(encoding="utf-8")
    assert SHARED_PLOTLY_TAG in html
    assert "plotly.js v" not in html
    assert path.stat().st_size < 50_000


def test_chart_writes_the_plotly_bundle_beside_it(
    interactive_chart: Callable[[str], Optional[str]]
) -> None:
    assert interactive_chart(ANALYSIS_ID) is not None
    bundle = viz_tools.CHARTS_DIR / "plotly.min.js"
    assert bundle.is_file()
    data = bundle.read_bytes()
    assert PLOTLY_HEADER.match(data.decode("latin1"))
    assert data == get_plotlyjs().encode("utf-8")


def test_chart_has_the_fixed_div_id_and_no_download_button_or_logo(
    interactive_chart: Callable[[str], Optional[str]]
) -> None:
    filename = interactive_chart(ANALYSIS_ID)
    assert filename is not None
    div_id, _, _, config = newplot_args(filename)
    assert div_id == "chart"
    assert config.get("displaylogo") is False
    assert "toImage" in config.get("modeBarButtonsToRemove", [])


def test_chart_holds_no_uuid_but_the_analysis_id(
    interactive_chart: Callable[[str], Optional[str]]
) -> None:
    filename = interactive_chart(ANALYSIS_ID)
    assert filename is not None
    assert foreign_uuids(viz_tools.CHARTS_DIR / filename, ANALYSIS_ID) == set()
    assert foreign_uuids(viz_tools.CHARTS_DIR / "plotly.min.js", None) == set()


def test_chart_bytes_are_the_same_on_every_run(
    interactive_chart: Callable[[str], Optional[str]],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same chart written twice, into two separate folders, is byte-identical."""
    written = []
    for folder in ("first", "second"):
        charts = tmp_path / folder
        charts.mkdir()
        monkeypatch.setattr(viz_tools, "CHARTS_DIR", charts)
        filename = interactive_chart(ANALYSIS_ID)
        assert filename is not None
        written.append((charts / filename).read_bytes())
    assert written[0] == written[1]


# ---------------------------------------------------------------------------
# How the bundle and the chart are written: whole or not at all
# ---------------------------------------------------------------------------


def pinned_bundle() -> bytes:
    """The installed plotly's bundle, as the charts' plotly.min.js must hold it."""
    return get_plotlyjs().encode("utf-8")


def names(folder: pathlib.Path) -> list:
    return sorted(path.name for path in folder.iterdir())


def test_a_truncated_bundle_is_replaced_by_the_whole_one(
    interactive_chart: Callable[[str], Optional[str]]
) -> None:
    """What a process killed during the bundle's first write leaves behind (M2b.2 Code Review #1)."""
    bundle = viz_tools.CHARTS_DIR / "plotly.min.js"
    bundle.write_bytes(pinned_bundle()[:1000])
    assert interactive_chart(ANALYSIS_ID) is not None
    assert bundle.read_bytes() == pinned_bundle()


def test_a_failed_bundle_step_leaves_no_chart(
    interactive_chart: Callable[[str], Optional[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2b.2 Code Review #5: plotly wrote the chart before the bundle."""

    def no_space() -> str:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(plotly_html, "get_plotlyjs", no_space)  # read by write_html's "directory" mode
    monkeypatch.setattr(viz_tools, "get_plotlyjs", no_space, raising=False)  # read by ensure_plotly_bundle
    assert interactive_chart(ANALYSIS_ID) is None
    assert names(viz_tools.CHARTS_DIR) == []


def test_a_failed_chart_write_leaves_no_partial_or_temporary_file(
    interactive_chart: Callable[[str], Optional[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write_text = pathlib.Path.write_text

    def half_then_no_space(self: pathlib.Path, data: str, *args: object, **kwargs: object) -> int:
        if self.name == "plotly.min.js":
            return real_write_text(self, data, *args, **kwargs)
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "write_text", half_then_no_space)
    assert interactive_chart(ANALYSIS_ID) is None
    assert names(viz_tools.CHARTS_DIR) == ["plotly.min.js"]
    assert (viz_tools.CHARTS_DIR / "plotly.min.js").read_bytes() == pinned_bundle()


def test_the_bundle_pin_is_the_installed_plotly_bundle() -> None:
    """Fails after a plotly upgrade until the pin, the snapshot's plotly.min.js and the third-party
    notice are regenerated together (tasks.md)."""
    assert hashlib.sha256(pinned_bundle()).hexdigest() == viz_tools.PLOTLY_BUNDLE_SHA256


def test_a_plotly_whose_bundle_is_not_the_pinned_one_writes_nothing(
    interactive_chart: Callable[[str], Optional[str]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundle = viz_tools.CHARTS_DIR / "plotly.min.js"
    bundle.write_bytes(pinned_bundle())
    before = bundle.stat()

    def upgraded() -> str:
        return "/*! plotly.js v9.9.9 */"

    monkeypatch.setattr(plotly_html, "get_plotlyjs", upgraded)
    monkeypatch.setattr(viz_tools, "get_plotlyjs", upgraded, raising=False)
    with caplog.at_level(logging.ERROR, logger="backend.tools.viz_tools"):
        assert interactive_chart(ANALYSIS_ID) is None
    after = bundle.stat()
    assert names(viz_tools.CHARTS_DIR) == ["plotly.min.js"]
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert bundle.read_bytes() == pinned_bundle()
    assert any(
        record.levelno == logging.ERROR and "PLOTLY_BUNDLE_SHA256" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize("failing", ["fsync", "replace"])
def test_a_failed_bundle_write_leaves_no_temporary_file(
    small_df: pd.DataFrame, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    def io_error(*args: object, **kwargs: object) -> None:
        raise OSError(errno.EIO, "Input/output error")

    if failing == "fsync":
        monkeypatch.setattr(os, "fsync", io_error)
    else:
        real_replace = os.replace

        def replace(
            src: "str | os.PathLike[str]", dst: "str | os.PathLike[str]", *args: object, **kwargs: object
        ) -> None:
            if pathlib.Path(dst).name == "plotly.min.js":
                io_error()
            real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(os, "replace", replace)
    assert generate_scatter_plot(small_df, "a", "b", ANALYSIS_ID, 0.5) is None
    assert names(viz_tools.CHARTS_DIR) == []


def test_files_are_renamed_into_place_from_hidden_temporary_names(
    interactive_chart: Callable[[str], Optional[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    renames: list = []
    real_replace = os.replace

    def spy(
        src: "str | os.PathLike[str]", dst: "str | os.PathLike[str]", *args: object, **kwargs: object
    ) -> None:
        renames.append((pathlib.Path(src), pathlib.Path(dst)))
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    first = interactive_chart(ANALYSIS_ID)
    second = interactive_chart(OTHER_ID)
    assert [dst.name for _, dst in renames] == ["plotly.min.js", first, second]
    for src, dst in renames:
        assert src.parent == dst.parent == viz_tools.CHARTS_DIR
        assert src.name.startswith(".") and src.name.endswith(".tmp")
    assert names(viz_tools.CHARTS_DIR) == sorted([first, second, "plotly.min.js"])


def test_an_intact_bundle_is_left_as_it_is(interactive_chart: Callable[[str], Optional[str]]) -> None:
    """Rewriting it would change the cache validators StaticFiles sends for it (decisions.md 2026-10-12)."""
    bundle = viz_tools.CHARTS_DIR / "plotly.min.js"
    bundle.write_bytes(pinned_bundle())
    before = bundle.stat()
    assert interactive_chart(ANALYSIS_ID) is not None
    after = bundle.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_size) == (before.st_ino, before.st_mtime_ns, before.st_size)


def test_chart_and_bundle_get_the_permissions_a_plain_write_gives(
    interactive_chart: Callable[[str], Optional[str]], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """0o666 less the umask, as plotly's own writes gave them before M2c.2 (tempfile.mkstemp gives 0o600)."""
    filename = interactive_chart(ANALYSIS_ID)
    assert filename is not None
    reference = tmp_path_factory.mktemp("reference") / "file"
    reference.write_text("x")
    expected = stat.S_IMODE(reference.stat().st_mode)
    for name in (filename, "plotly.min.js"):
        assert stat.S_IMODE((viz_tools.CHARTS_DIR / name).stat().st_mode) == expected
