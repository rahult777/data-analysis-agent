"""FastAPI application entry point.

Exposes all API endpoints, mounts static file serving for charts,
and manages application lifespan.
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.agents.explainer import answer_question
from backend.agents.orchestrator import build_initial_state, run_pipeline
from backend.models.schemas import (
    AnalysisResponse,
    AnalysisStatus,
    PauseResumeRequest,
    QuestionRequest,
    QuestionResponse,
    QuestionStatus,
    StatusResponse,
    UploadResponse,
)
from backend.utils.file_handler import cleanup_temp_file, save_temp_file, validate_file
from backend.utils.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

_PROGRESS_MAP: dict[str, float] = {
    "profiling": 20.0,
    "domain_pause": 20.0,
    "cleaning": 40.0,
    "cleaned": 45.0,
    "missing_value_pause": 40.0,
    "outlier_pause": 40.0,
    "analyzing": 60.0,
    "explaining": 80.0,
    "complete": 100.0,
    "error": 0.0,
}

_AGENT_MAP: dict[str, Optional[str]] = {
    "profiling": "profiler",
    "domain_pause": "profiler",
    "cleaning": "cleaner",
    "cleaned": "cleaner",
    "missing_value_pause": "cleaner",
    "outlier_pause": "cleaner",
    "analyzing": "analyzer",
    "explaining": "explainer",
    "complete": None,
    "error": None,
}

_PAUSE_STATUSES: tuple[str, ...] = ("domain_pause", "missing_value_pause", "outlier_pause")

_MAX_CORRECTED_DOMAIN_LENGTH = 200


def _error_category(error_message: Optional[str]) -> Optional[str]:
    """Reduce a stored error_message to its category for the public status route.

    Agents store raw exception text after the prefix (f"SYSTEM_ERROR: {exc}"),
    which can include server paths or database details. The frontend only needs
    the category, so the detail never leaves the server.
    """
    if error_message is None:
        return None
    return "USER_ERROR" if error_message.startswith("USER_ERROR") else "SYSTEM_ERROR"


def _check_corrected_domain(response: dict) -> None:
    """A 'correct' domain answer must carry a non-blank corrected_domain.

    The correction enters the Profiler's LLM prompt and the publicly readable
    profile_report, so it is also bounded here, at the boundary.
    """
    if response.get("option_id") != "correct":
        return
    corrected_domain = response.get("corrected_domain")
    if not isinstance(corrected_domain, str) or not corrected_domain.strip():
        raise HTTPException(
            status_code=400,
            detail="response.corrected_domain is required when option_id is 'correct'.",
        )
    if len(corrected_domain.strip()) > _MAX_CORRECTED_DOMAIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=(
                "response.corrected_domain must be at most "
                f"{_MAX_CORRECTED_DOMAIN_LENGTH} characters."
            ),
        )


def _validate_pause_response(status: str, pause_data: Optional[dict], response: dict) -> None:
    """Check a resume response against the pause question it answers.

    Option ids and column_name are checked against the stored pause_data, not
    hardcoded, because the question is raw LLM output. When there is no stored
    question with usable option ids to check against, option_id is not checked
    — rejecting every answer would strand the analysis, because the pause-wait
    node polls with no timeout. column_name is still checked whenever a usable
    one is stored: it is what rejects an answer from a stale tab, written for a
    pause that is no longer the active one.
    """
    if response.get("pause_type") != status:
        raise HTTPException(
            status_code=400,
            detail=f"response.pause_type must be '{status}' for the active pause.",
        )
    options = pause_data.get("options") if isinstance(pause_data, dict) else None
    option_ids = [
        option["id"]
        for option in (options if isinstance(options, list) else [])
        if isinstance(option, dict) and isinstance(option.get("id"), str) and option["id"].strip()
    ]
    if not option_ids:
        stored_column = pause_data.get("column_name") if isinstance(pause_data, dict) else None
        if (
            status != "domain_pause"
            and isinstance(stored_column, str)
            and stored_column.strip()
            and response.get("column_name") != stored_column
        ):
            raise HTTPException(
                status_code=400,
                detail=f"response.column_name must be '{stored_column}'.",
            )
        # A correction can always be re-submitted valid, so checking it here
        # cannot strand the analysis.
        if status == "domain_pause":
            _check_corrected_domain(response)
        logger.warning(
            "Resume for a %s with no stored option ids to validate against; "
            "option_id was not validated.",
            status,
        )
        return
    if response.get("option_id") not in option_ids:
        raise HTTPException(
            status_code=400,
            detail=f"response.option_id must be one of {option_ids}.",
        )
    if status == "domain_pause":
        _check_corrected_domain(response)
    elif response.get("column_name") != pause_data.get("column_name"):
        raise HTTPException(
            status_code=400,
            detail=f"response.column_name must be '{pause_data.get('column_name')}'.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path("backend/outputs/charts").mkdir(parents=True, exist_ok=True)
    logger.info("Application startup complete.")
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to frontend URL before production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory must exist before StaticFiles initializes; lifespan also creates it.
Path("backend/outputs/charts").mkdir(parents=True, exist_ok=True)
app.mount("/charts", StaticFiles(directory="backend/outputs/charts"), name="charts")


# ---------------------------------------------------------------------------
# Session validation dependency
# ---------------------------------------------------------------------------


async def get_session(
    analysis_id: str,
    session_id: str = Header(None, alias="session-id"),
) -> str:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses")
        .select("id, session_id")
        .eq("id", analysis_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    record = response.data[0]
    if session_id != record["session_id"]:
        raise HTTPException(status_code=403, detail="Invalid or missing session-id header.")
    return session_id


# ---------------------------------------------------------------------------
# Public-read dependency — read-only GET routes only
# ---------------------------------------------------------------------------


def _is_canonical_uuid(value: str) -> bool:
    """True only for the canonical hyphenated form. uuid.UUID() alone also
    accepts prefixes such as "urn:uuid:" that Postgres rejects with 22P02."""
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


async def get_public_read_access(analysis_id: str) -> str:
    """Allow read-only access to an analysis by its id alone.

    analysis_id is a random UUID4 and is itself the capability for reads, so
    no session-id header is required or checked. Every route that writes
    state or can trigger an LLM call must keep using get_session. A malformed
    id returns 404 instead of letting Postgres raise 22P02 (a 500).
    """
    if not _is_canonical_uuid(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return analysis_id


# ---------------------------------------------------------------------------
# Background task stubs — agents wired in when backend/agents/ is built
# ---------------------------------------------------------------------------


async def run_pipeline_task(
    analysis_id: str,
    stored_filename: str,
    context: str,
    user_type: str,
) -> None:
    logger.info("Pipeline task triggered for analysis_id=%s", analysis_id)
    initial_state = await build_initial_state(analysis_id, stored_filename, context, user_type)
    await run_pipeline(initial_state)


async def run_question_task(
    question_id: str,
    analysis_id: str,
    question: str,
) -> None:
    await answer_question(analysis_id, question_id, question)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    context: Optional[str] = Form(None),
    user_type: Optional[str] = Form(None),
) -> dict:
    content = await file.read()
    try:
        await asyncio.to_thread(validate_file, file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    stored_filename = await save_temp_file(content, file.filename)
    analysis_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    client = get_supabase_client()
    await asyncio.to_thread(
        lambda: client.table("analyses")
        .insert(
            {
                "id": analysis_id,
                "status": "profiling",
                "original_filename": file.filename,
                "stored_filename": stored_filename,
                "file_size": len(content),
                "session_id": session_id,
            }
        )
        .execute()
    )

    background_tasks.add_task(
        run_pipeline_task, analysis_id, stored_filename, context, user_type
    )

    return {
        "analysis_id": analysis_id,
        "filename": file.filename,
        "status": "profiling",
        "session_id": session_id,
        "message": "Analysis started. Use analysis_id to poll for results.",
    }


@app.get("/api/analysis/{analysis_id}/status", response_model=StatusResponse)
async def get_status(
    analysis_id: str,
    _access: str = Depends(get_public_read_access),
) -> StatusResponse:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses")
        .select("id, status, error_message, pause_data")
        .eq("id", analysis_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    record = response.data[0]
    status = record["status"]
    return StatusResponse(
        analysis_id=analysis_id,
        status=AnalysisStatus(status),
        current_agent=_AGENT_MAP.get(status),
        progress_pct=_PROGRESS_MAP.get(status, 0.0),
        error_message=_error_category(record.get("error_message")),
        pause_data=record.get("pause_data") if status in _PAUSE_STATUSES else None,
    )


@app.get("/api/analysis/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    _access: str = Depends(get_public_read_access),
) -> AnalysisResponse:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses").select("*").eq("id", analysis_id).execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    record = response.data[0]
    return AnalysisResponse(
        id=record["id"],
        filename=record["original_filename"],
        status=AnalysisStatus(record["status"]),
        created_at=record["created_at"],
        row_count=record.get("row_count"),
        column_count=record.get("column_count"),
        data_quality_score=record.get("data_quality_score"),
        profile_report=record.get("profile_report"),
        cleaning_report=record.get("cleaning_report"),
        cleaning_decisions=record.get("cleaning_decisions"),
        analysis_report=record.get("analysis_report"),
        insight_report=record.get("insight_report"),
        executive_summary=record.get("executive_summary"),
        chart_paths=record.get("chart_paths"),
    )


@app.post("/api/analysis/{analysis_id}/question", response_model=QuestionResponse)
async def post_question(
    analysis_id: str,
    request: QuestionRequest,
    background_tasks: BackgroundTasks,
    _session: str = Depends(get_session),
) -> QuestionResponse:
    question_id = str(uuid.uuid4())
    client = get_supabase_client()
    await asyncio.to_thread(
        lambda: client.table("questions")
        .insert(
            {
                "id": question_id,
                "analysis_id": analysis_id,
                "question": request.question,
                "status": "pending",
            }
        )
        .execute()
    )

    background_tasks.add_task(run_question_task, question_id, analysis_id, request.question)

    return QuestionResponse(
        question_id=question_id,
        analysis_id=analysis_id,
        question=request.question,
        status=QuestionStatus.PENDING,
        answer=None,
        pandas_code=None,
    )


@app.get(
    "/api/analysis/{analysis_id}/question/{question_id}",
    response_model=QuestionResponse,
)
async def get_question(
    analysis_id: str,
    question_id: str,
    _access: str = Depends(get_public_read_access),
) -> QuestionResponse:
    if not _is_canonical_uuid(question_id):
        raise HTTPException(status_code=404, detail="Question not found")
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("questions")
        .select("*")
        .eq("id", question_id)
        .eq("analysis_id", analysis_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Question not found")
    record = response.data[0]
    return QuestionResponse(
        question_id=record["id"],
        analysis_id=record["analysis_id"],
        question=record["question"],
        status=QuestionStatus(record["status"]),
        answer=record.get("answer"),
        pandas_code=record.get("pandas_code"),
    )


@app.post("/api/analysis/{analysis_id}/resume", response_model=StatusResponse)
async def resume_analysis(
    analysis_id: str,
    body: PauseResumeRequest,
    _session: str = Depends(get_session),
) -> StatusResponse:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses")
        .select("id, status, pause_data, updated_at")
        .eq("id", analysis_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    record = response.data[0]
    status = record["status"]
    if status not in _PAUSE_STATUSES:
        raise HTTPException(status_code=400, detail="Analysis is not in a pause state.")
    _validate_pause_response(status, record.get("pause_data"), body.response)
    restore_status = "profiling" if status == "domain_pause" else "cleaning"
    # pause_data is cleared in the same update that leaves the pause status.
    # The write is conditional on the pause read above: its status AND its
    # updated_at, which the pause-wait node stamps when it writes each pause.
    # Status alone is not enough — a Cleaner re-pause on another column repeats
    # missing_value_pause. This covers only the pause changing between this
    # request's read and its write (updates no rows → 409). An answer from a
    # stale tab, written for an earlier pause, is caught instead by the
    # column_name check in _validate_pause_response — but only when a usable
    # column_name is stored and the active pause is on a different column. A
    # stale answer to a re-pause on the same column, or to a pause with no
    # stored pause_data, is accepted.
    read_updated_at = record.get("updated_at")
    query = (
        client.table("analyses")
        .update({
            "user_pause_response": body.response,
            "pause_data": None,
            "status": restore_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", analysis_id)
        .eq("status", status)
    )
    query = (
        query.eq("updated_at", read_updated_at)
        if read_updated_at is not None
        else query.is_("updated_at", "null")
    )
    updated = await asyncio.to_thread(query.execute)
    if not updated.data:
        raise HTTPException(
            status_code=409,
            detail="The pause this response answers is no longer active. Refresh and try again.",
        )
    # Pipeline continues automatically — the polling loop in pause wait nodes
    # detects user_pause_response and resumes execution.
    return StatusResponse(
        analysis_id=analysis_id,
        status=AnalysisStatus(restore_status),
        current_agent=_AGENT_MAP.get(restore_status),
        progress_pct=_PROGRESS_MAP.get(restore_status, 0.0),
        error_message=None,
    )


@app.get("/api/analysis/{analysis_id}/charts")
async def get_charts(
    analysis_id: str,
    _access: str = Depends(get_public_read_access),
) -> dict:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses")
        .select("chart_paths")
        .eq("id", analysis_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    chart_paths = response.data[0].get("chart_paths") or []
    return {"chart_paths": chart_paths}
