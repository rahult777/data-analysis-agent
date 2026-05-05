"""
Chart generation for the analysis pipeline.

Generates all static (PNG via matplotlib/seaborn) and interactive (HTML via plotly)
charts required by the Analyzer agent. Every function saves to CHARTS_DIR and returns
only the filename — never the full path — so analyzer.py can store it in Supabase and
the frontend can construct /charts/{filename} URLs via the StaticFiles mount.
"""

import logging
import re

import matplotlib

matplotlib.use("Agg")  # non-interactive backend — must precede pyplot import

import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import pandas as pd
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

sns.set_style("whitegrid")

# Resolved relative to this file so it is invariant of process CWD.
CHARTS_DIR = Path(__file__).parent.parent / "outputs" / "charts"

CHART_DPI: int = 150

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


def ensure_charts_dir() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


ensure_charts_dir()


def _safe_name(name: str) -> str:
    """Sanitize a column name for use in a filename."""
    sanitized = re.sub(r"[^\w]", "_", name)
    return sanitized[:30]


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
            title=f"{value_column} Over Time",
        )
        filename = f"{analysis_id}_linechart_{_safe_name(value_column)}.html"
        fig.write_html(str(CHARTS_DIR / filename))
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
        fig = px.scatter(
            df,
            x=x_column,
            y=y_column,
            title=f"{x_column} vs {y_column} (r={correlation:.2f})",
        )
        filename = f"{analysis_id}_scatter_{_safe_name(x_column)}_{_safe_name(y_column)}.html"
        fig.write_html(str(CHARTS_DIR / filename))
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
