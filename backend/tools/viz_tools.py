"""
Chart generation for the analysis pipeline.

Generates all static (PNG via matplotlib/seaborn) and interactive (HTML via plotly)
charts required by the Analyzer agent. Every function saves to CHARTS_DIR and returns
only the filename — never the full path — so analyzer.py can store it in Supabase and
the frontend can construct /charts/{filename} URLs via the StaticFiles mount. The
interactive charts load plotly.min.js from beside them: before each one is written,
ensure_plotly_bundle() makes CHARTS_DIR's copy the bundle pinned by
PLOTLY_BUNDLE_SHA256, and both files are written under a temporary name and renamed
into place, so an error or a killed process leaves no partial chart or bundle. A power
loss or OS crash before the page cache is flushed is not covered for the chart, only for
the bundle, which is fsynced and is repaired by hash on the next chart (tasks.md, M5).
"""

import hashlib
import logging
import os
import re
import secrets

import matplotlib

matplotlib.use("Agg")  # non-interactive backend — must precede pyplot import

import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
from plotly.graph_objects import Figure
from plotly.offline import get_plotlyjs
import pandas as pd
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

sns.set_style("whitegrid")

# Resolved relative to this file so it is invariant of process CWD.
CHARTS_DIR = Path(__file__).parent.parent / "outputs" / "charts"

CHART_DPI: int = 150

# Column names in chart titles are cut to this length, so that a name and its
# suffix (" (r=-0.42)", " Over Time") fit on the 270 px chart card of a 320 px
# screen (measured in Chromium; decisions.md 2026-10-12).
TITLE_NAME_LIMIT: int = 19

PROJECT_COLORS: List[str] = [
    "#264653",
    "#2A9D8F",
    "#E9C46A",
    "#F4A261",
    "#E76F51",
    "#457B9D",
    "#A8DADC",
    "#6D6875",
]

# The plotly.js bundle the interactive charts load from beside them: the installed
# plotly's own copy (plotly 5.20.0: plotly.js 2.30.0), as plotly.offline.get_plotlyjs()
# returns it. After a plotly upgrade the suite fails until this pin, the snapshot's
# plotly.min.js and the third-party notice are regenerated together (tasks.md, M2c).
PLOTLY_BUNDLE = "plotly.min.js"
PLOTLY_BUNDLE_SHA256 = "3baddf12a4f47ac22f006078f95c38b21abd53d1511b80e600a60cf0c52bab6e"


def ensure_charts_dir() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


ensure_charts_dir()


def _create_temporary_file(kind: str) -> Tuple[int, Path]:
    """Create a new, empty file in CHARTS_DIR under a fresh temporary name; return its descriptor and path.

    The name starts with a dot and ends in .tmp, so nothing takes it for a chart, and its length does
    not depend on the chart's name. The mode 0o666 is reduced by the umask, as for a plain open(), so
    the renamed file gets the permissions a direct write gives (tempfile.mkstemp would give 0o600).
    """
    path = CHARTS_DIR / f".{kind}.{secrets.token_hex(8)}.tmp"
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666), path


def ensure_plotly_bundle() -> None:
    """Make CHARTS_DIR/plotly.min.js the pinned bundle, before an interactive chart is written.

    A missing bundle is written, and one with another hash (a truncated first write, say) is replaced,
    atomically: a temporary file in CHARTS_DIR, written, flushed to disk, then renamed over it. An intact
    bundle is left as it is. If the installed plotly's bundle is not the pinned one (plotly upgraded
    without regenerating the pin), nothing is written: the error is logged and raised.
    """
    bundle = get_plotlyjs().encode("utf-8")
    if hashlib.sha256(bundle).hexdigest() != PLOTLY_BUNDLE_SHA256:
        logger.error(
            "The installed plotly's bundle does not match PLOTLY_BUNDLE_SHA256, so no interactive chart is "
            "written. Regenerate the pin, the snapshot's plotly.min.js and the third-party notice together "
            "(tasks.md)."
        )
        raise RuntimeError("the installed plotly's bundle does not match PLOTLY_BUNDLE_SHA256")
    target = CHARTS_DIR / PLOTLY_BUNDLE
    try:
        if hashlib.sha256(target.read_bytes()).hexdigest() == PLOTLY_BUNDLE_SHA256:
            return
    except FileNotFoundError:
        pass
    fd, temporary = _create_temporary_file("plotly-bundle")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(bundle)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_interactive_chart(fig: Figure, filename: str) -> None:
    """Write an interactive chart as CHARTS_DIR/filename: the pinned bundle first, then the chart under a
    temporary name, renamed into place. An error or a killed process leaves no partial chart or bundle; an
    error also removes the temporary file, which a hard kill can leave behind (tasks.md, M5). A power loss
    or OS crash before the page cache is flushed is not covered for the chart, only for the bundle, which
    is fsynced and is repaired by hash on the next chart (tasks.md, M5)."""
    ensure_plotly_bundle()
    fd, temporary = _create_temporary_file("chart")
    try:
        os.close(fd)
        # The string names the bundle beside the chart, with the same tag "directory" wrote, but plotly
        # never writes it. The config dict is new on every call: plotly adds keys to the dict it is given.
        fig.write_html(
            str(temporary),
            include_plotlyjs=PLOTLY_BUNDLE,
            div_id="chart",
            config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"]},
        )
        os.replace(temporary, CHARTS_DIR / filename)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _safe_name(name: str) -> str:
    """Sanitize a column name for use in a filename."""
    sanitized = re.sub(r"[^\w]", "_", name)
    return sanitized[:30]


def _short_name(name: str, limit: int = 26) -> str:
    """Truncate a long column name so a chart title stays readable."""
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def generate_histogram(
    df: pd.DataFrame, column: str, analysis_id: str
) -> Optional[str]:
    """Generate a histogram for a single numeric column. Returns filename or None."""
    try:
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.histplot(data=df, x=column, ax=ax, color=PROJECT_COLORS[0])
        ax.set_title(f"Distribution of {column}")
        ax.set_xlabel(column)
        ax.set_ylabel("Frequency")
        plt.tight_layout()
        filename = f"{analysis_id}_histogram_{_safe_name(column)}.png"
        fig.savefig(CHARTS_DIR / filename, dpi=CHART_DPI)
        return filename
    except Exception as e:
        logger.warning("Failed to generate histogram for column '%s': %s", column, e)
        return None
    finally:
        plt.close("all")


def generate_boxplot(
    df: pd.DataFrame, column: str, analysis_id: str
) -> Optional[str]:
    """Generate a box plot for a single numeric column. Returns filename or None."""
    try:
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.boxplot(data=df, y=column, ax=ax, color=PROJECT_COLORS[0])
        ax.set_title(f"Box Plot — {column}")
        plt.tight_layout()
        filename = f"{analysis_id}_boxplot_{_safe_name(column)}.png"
        fig.savefig(CHARTS_DIR / filename, dpi=CHART_DPI)
        return filename
    except Exception as e:
        logger.warning("Failed to generate boxplot for column '%s': %s", column, e)
        return None
    finally:
        plt.close("all")


def generate_correlation_heatmap(
    df: pd.DataFrame, analysis_id: str
) -> Optional[str]:
    """Generate a full NxN correlation heatmap for all numeric columns. Returns filename or None."""
    try:
        numeric_df = df.select_dtypes(include="number")
        n_cols = len(numeric_df.columns)
        if n_cols < 2:
            return None
        corr = numeric_df.corr()
        width = max(8, 0.5 * n_cols + 5)
        height = max(6, 0.5 * n_cols + 3)
        fig, ax = plt.subplots(figsize=(width, height))
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", ax=ax)
        ax.set_title("Correlation Matrix")
        plt.tight_layout()
        filename = f"{analysis_id}_correlation_heatmap.png"
        fig.savefig(CHARTS_DIR / filename, dpi=CHART_DPI)
        return filename
    except Exception as e:
        logger.warning("Failed to generate correlation heatmap: %s", e)
        return None
    finally:
        plt.close("all")


def generate_bar_chart(
    df: pd.DataFrame, column: str, analysis_id: str, top_n: int = 10
) -> Optional[str]:
    """Generate a bar chart of top N value frequencies for a categorical column. Returns filename or None."""
    try:
        value_counts = df[column].value_counts().head(top_n)
        colors = [PROJECT_COLORS[i % len(PROJECT_COLORS)] for i in range(len(value_counts))]
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(value_counts.index.astype(str), value_counts.values, color=colors)
        ax.set_title(f"Top {top_n} Values — {column}")
        ax.set_xlabel(column)
        ax.set_ylabel("Count")
        if len(value_counts) > 5:
            plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        filename = f"{analysis_id}_barchart_{_safe_name(column)}.png"
        fig.savefig(CHARTS_DIR / filename, dpi=CHART_DPI)
        return filename
    except Exception as e:
        logger.warning("Failed to generate bar chart for column '%s': %s", column, e)
        return None
    finally:
        plt.close("all")


def generate_line_chart(
    df: pd.DataFrame,
    date_column: str,
    value_column: str,
    analysis_id: str,
) -> Optional[str]:
    """Generate an interactive line chart of value_column over time. Returns HTML filename or None."""
    try:
        sorted_df = df.sort_values(by=date_column)
        fig = px.line(
            sorted_df,
            x=date_column,
            y=value_column,
        )
        fig.update_layout(
            title=dict(
                text=f"{_short_name(value_column, limit=TITLE_NAME_LIMIT)} Over Time",
                font=dict(size=14),
            ),
            margin=dict(t=80, l=60, r=20, b=50),
        )
        filename = f"{analysis_id}_linechart_{_safe_name(value_column)}.html"
        _write_interactive_chart(fig, filename)
        return filename
    except Exception as e:
        logger.warning(
            "Failed to generate line chart for '%s' over '%s': %s",
            value_column,
            date_column,
            e,
        )
        return None
    finally:
        plt.close("all")


def generate_scatter_plot(
    df: pd.DataFrame,
    x_column: str,
    y_column: str,
    analysis_id: str,
    correlation: float,
) -> Optional[str]:
    """Generate an interactive scatter plot for the highest-correlation column pair. Returns HTML filename or None."""
    try:
        fig = px.scatter(df, x=x_column, y=y_column)
        fig.update_layout(
            title=dict(
                text=(
                    f"{_short_name(x_column, limit=TITLE_NAME_LIMIT)} vs<br>"
                    f"{_short_name(y_column, limit=TITLE_NAME_LIMIT)} (r={correlation:.2f})"
                ),
                font=dict(size=14),
            ),
            margin=dict(t=80, l=60, r=20, b=50),
        )
        filename = f"{analysis_id}_scatter_{_safe_name(x_column)}_{_safe_name(y_column)}.html"
        _write_interactive_chart(fig, filename)
        return filename
    except Exception as e:
        logger.warning(
            "Failed to generate scatter plot for '%s' vs '%s': %s",
            x_column,
            y_column,
            e,
        )
        return None
    finally:
        plt.close("all")


def generate_all_charts(
    df: pd.DataFrame,
    analysis_id: str,
    numeric_columns: List[str],
    categorical_columns: List[str],
    datetime_column: Optional[str],
    time_series_value_column: Optional[str],
    highest_correlation_pair: Optional[Tuple[str, str]],
    highest_correlation_value: Optional[float],
) -> List[str]:
    """
    Orchestrate generation of all charts for an analysis run.

    Called by analyzer.py. Returns a list of successfully generated filenames.
    Filenames are stored in Supabase; the frontend resolves them as /charts/{filename}.
    """
    chart_paths: List[str] = []

    try:
        for column in numeric_columns:
            hist = generate_histogram(df, column, analysis_id)
            if hist is not None:
                chart_paths.append(hist)
            box = generate_boxplot(df, column, analysis_id)
            if box is not None:
                chart_paths.append(box)

        if len(numeric_columns) >= 2:
            heatmap = generate_correlation_heatmap(df, analysis_id)
            if heatmap is not None:
                chart_paths.append(heatmap)

        for column in categorical_columns:
            bar = generate_bar_chart(df, column, analysis_id)
            if bar is not None:
                chart_paths.append(bar)

        if datetime_column is not None and time_series_value_column is not None:
            line = generate_line_chart(df, datetime_column, time_series_value_column, analysis_id)
            if line is not None:
                chart_paths.append(line)

        if (
            highest_correlation_pair is not None
            and len(highest_correlation_pair) == 2
            and highest_correlation_value is not None
        ):
            scatter = generate_scatter_plot(
                df,
                highest_correlation_pair[0],
                highest_correlation_pair[1],
                analysis_id,
                highest_correlation_value,
            )
            if scatter is not None:
                chart_paths.append(scatter)

    except Exception as e:
        logger.warning(
            "Unexpected error during chart orchestration for analysis_id=%s: %s",
            analysis_id,
            e,
        )

    logger.info(
        "Generated %d chart(s) for analysis_id=%s", len(chart_paths), analysis_id
    )
    return chart_paths
