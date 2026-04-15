"""
All Pydantic schemas for the data analysis agent system.

This file is the single source of truth for every data shape used across:
- Agent outputs (Profiler, Cleaner, Analyzer, Explainer)
- Database records (analyses table, questions table)
- API request and response bodies (all 5 endpoints)

Build order: Enums → Leaf models → Mid-tier models → API layer models.
Each class may only reference types defined above it in this file.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AnalysisStatus(str, Enum):
    PROFILING = "profiling"
    CLEANING = "cleaning"
    ANALYZING = "analyzing"
    EXPLAINING = "explaining"
    COMPLETE = "complete"
    ERROR = "error"


class QuestionStatus(str, Enum):
    PENDING = "pending"
    ANSWERING = "answering"
    COMPLETE = "complete"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Leaf models — no dependencies on other custom schemas
# ---------------------------------------------------------------------------


class ColumnProfile(BaseModel):
    """Profile of a single column produced by the Profiler agent."""

    model_config = ConfigDict(from_attributes=True)

    column_name: str
    dtype: str
    missing_count: int
    missing_pct: float = Field(ge=0.0, le=100.0)
    unique_count: int
    sample_values: list[str]
    is_numeric: bool
    is_categorical: bool
    is_datetime: bool
    outlier_count: int | None = None
    outlier_pct: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    mean: float | None = None
    std: float | None = None


class CleaningDecision(BaseModel):
    """A single cleaning action taken on a column or the whole dataset."""

    model_config = ConfigDict(from_attributes=True)

    column_name: str | None = None  # None for dataset-level decisions
    issue: str
    action: str
    reason: str


class CleanedDatasetSummary(BaseModel):
    """Before/after row and column counts after the Cleaner runs."""

    model_config = ConfigDict(from_attributes=True)

    rows_before: int
    rows_after: int
    rows_removed: int
    columns_before: int
    columns_after: int
    columns_removed: int


class DescriptiveStats(BaseModel):
    """Descriptive statistics for a single column produced by the Analyzer."""

    model_config = ConfigDict(from_attributes=True)

    column_name: str
    count: int
    mean: float | None = None
    std: float | None = None
    min_value: float | None = None
    q25: float | None = None
    median: float | None = None
    q75: float | None = None
    max_value: float | None = None
    mode: str | None = None  # stringified — works for both numeric and categorical
    skewness: float | None = None
    kurtosis: float | None = None


class CorrelationMatrix(BaseModel):
    """Full NxN Pearson correlation matrix for all numeric columns."""

    model_config = ConfigDict(from_attributes=True)

    columns: list[str]
    data: dict[str, dict[str, float | None]]  # None for non-computable pairs


class DistributionInfo(BaseModel):
    """Shape and histogram data for a single column's distribution."""

    model_config = ConfigDict(from_attributes=True)

    column_name: str
    distribution_type: str  # "normal", "skewed_left", "skewed_right", "uniform", "bimodal", "categorical"
    histogram_bins: list[float] | None = None   # bin edges for numeric columns
    histogram_counts: list[int] | None = None   # counts per bin


class ValueCounts(BaseModel):
    """Top-N frequency counts for a single column."""

    model_config = ConfigDict(from_attributes=True)

    column_name: str
    values: list[str]
    counts: list[int]
    percentages: list[float]


class TimeSeriesInfo(BaseModel):
    """Result of time series detection across the dataset."""

    model_config = ConfigDict(from_attributes=True)

    detected: bool
    datetime_column: str | None = None  # which column is the time axis
    frequency: str | None = None        # "daily", "monthly", "irregular"
    trend: str | None = None            # "upward", "downward", "flat", "seasonal"


class InsightSection(BaseModel):
    """A single named section inside the FullInsightReport."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    content: str  # markdown prose
    bullets: list[str] | None = None


# ---------------------------------------------------------------------------
# Mid-tier models — reference leaf models
# ---------------------------------------------------------------------------


class ProfileReport(BaseModel):
    """Complete output of the Profiler agent. Stored in analyses.profile_report."""

    model_config = ConfigDict(from_attributes=True)

    row_count: int
    column_count: int
    duplicate_row_count: int
    data_quality_score: float = Field(ge=0.0, le=1.0)  # mirrors analyses.data_quality_score
    columns: list[ColumnProfile]


class CleaningReport(BaseModel):
    """Complete output of the Cleaner agent. Stored in analyses.cleaning_report.

    analyses.cleaning_decisions is populated from CleaningReport.decisions directly.
    """

    model_config = ConfigDict(from_attributes=True)

    decisions: list[CleaningDecision]
    summary: CleanedDatasetSummary


class AnalysisReport(BaseModel):
    """Complete output of the Analyzer agent. Stored in analyses.analysis_report.

    chart_paths is also written to analyses.chart_paths (text[]) for fast lookup.
    """

    model_config = ConfigDict(from_attributes=True)

    descriptive_stats: list[DescriptiveStats]
    correlation: CorrelationMatrix | None = None  # None if fewer than 2 numeric columns
    distributions: list[DistributionInfo]
    value_counts: list[ValueCounts]
    time_series: TimeSeriesInfo | None = None
    chart_paths: list[str] = Field(default_factory=list)


class ExecutiveSummary(BaseModel):
    """Five business-language bullet points produced by the Explainer agent.

    Stored in analyses.executive_summary.
    """

    model_config = ConfigDict(from_attributes=True)

    bullet_points: list[str] = Field(min_length=5, max_length=5)


class FullInsightReport(BaseModel):
    """Six-section detailed insight report produced by the Explainer agent.

    Stored in analyses.insight_report.
    """

    model_config = ConfigDict(from_attributes=True)

    data_overview: InsightSection
    data_quality: InsightSection
    key_findings: InsightSection
    patterns: InsightSection
    anomalies: InsightSection
    recommended_actions: InsightSection


class ExplainerOutput(BaseModel):
    """Combined return type of the Explainer agent.

    Each field maps to its own JSONB column in Supabase and is stored separately.
    """

    model_config = ConfigDict(from_attributes=True)

    executive_summary: ExecutiveSummary
    insight_report: FullInsightReport


class QuestionRecord(BaseModel):
    """DB-layer representation of a row in the questions table."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    created_at: datetime
    question: str
    answer: str | None = None
    pandas_code: str | None = None
    status: QuestionStatus = QuestionStatus.PENDING


class QuestionAnswerResult(BaseModel):
    """Internal return type of the question-answering agent."""

    model_config = ConfigDict(from_attributes=True)

    answer: str
    pandas_code: str | None = None
    chart_path: str | None = None


# ---------------------------------------------------------------------------
# API layer models — request and response shapes for all 5 endpoints
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    """Response body for POST /api/upload."""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    filename: str
    status: AnalysisStatus
    message: str


class AnalysisResponse(BaseModel):
    """Response body for GET /api/analysis/{id}.

    All agent-output fields are Optional because the record is readable at any
    pipeline stage — fields are populated progressively as each agent completes.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: AnalysisStatus
    created_at: datetime
    row_count: int | None = None
    column_count: int | None = None
    data_quality_score: float | None = None
    profile_report: ProfileReport | None = None
    cleaning_report: CleaningReport | None = None
    cleaning_decisions: list[CleaningDecision] | None = None
    analysis_report: AnalysisReport | None = None
    insight_report: FullInsightReport | None = None
    executive_summary: ExecutiveSummary | None = None
    chart_paths: list[str] | None = None


class StatusResponse(BaseModel):
    """Response body for GET /api/analysis/{id}/status."""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    status: AnalysisStatus
    current_agent: str | None = None
    progress_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    error_message: str | None = None


class QuestionRequest(BaseModel):
    """Request body for POST /api/analysis/{id}/question."""

    model_config = ConfigDict(from_attributes=True)

    question: str


class QuestionResponse(BaseModel):
    """Response body for POST /api/analysis/{id}/question."""

    model_config = ConfigDict(from_attributes=True)

    question_id: str
    analysis_id: str
    question: str
    answer: str | None = None
    pandas_code: str | None = None
    status: QuestionStatus


class ChartsResponse(BaseModel):
    """Response body for GET /api/analysis/{id}/charts."""

    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    chart_paths: list[str]


class ErrorResponse(BaseModel):
    """Response body for all 4xx and 5xx error responses."""

    model_config = ConfigDict(from_attributes=True)

    error: str
    detail: str | None = None
