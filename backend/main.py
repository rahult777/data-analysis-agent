"""FastAPI application entry point.

Exposes all API endpoints, mounts static file serving for charts,
and manages application lifespan.
"""

import asyncio
import hmac
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from postgrest import APIResponse
from postgrest.exceptions import APIError

from backend import config
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
from backend.utils.agent_guard import require_agent_work_enabled
from backend.utils.file_handler import cleanup_temp_file, save_temp_file, validate_file
from backend.utils.request_gate import RequestGate
from backend.utils.supabase_client import get_supabase_client
from backend.utils.supabase_retry import supabase_call

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

# Refuses a state-changing request before its body is read (backend/utils/request_gate.py). Added before
# CORSMiddleware, so it runs inside it: preflights never reach it, and its refusals carry CORS headers.
app.add_middleware(RequestGate, allowed_origins=config.ALLOWED_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "session-id"],
)

# Directory must exist before StaticFiles initializes; lifespan also creates it.
Path("backend/outputs/charts").mkdir(parents=True, exist_ok=True)
app.mount("/charts", StaticFiles(directory="backend/outputs/charts"), name="charts")


# ---------------------------------------------------------------------------
# Session validation dependency
# ---------------------------------------------------------------------------


async def get_session(
    analysis_id: str,
    session_id: Optional[str] = Header(None, alias="session-id"),
) -> dict:
    """Return the analysis record (id, session_id, status) once the session-id header matches it.

    404 for a malformed analysis_id, before any database read (as get_public_read_access does). 403 when
    the header is missing or empty, the stored session_id is NULL, or the two differ. They are compared
    as UTF-8 bytes in constant time: Starlette decodes header values as latin-1, and hmac.compare_digest
    raises TypeError on a non-ASCII str.
    """
    if not _is_canonical_uuid(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found.")
    client = get_supabase_client()
    response = await supabase_call(
        lambda: client.table("analyses")
        .select("id, session_id, status")
        .eq("id", analysis_id)
        .execute(),
        what="session check",
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    record = response.data[0]
    stored = record.get("session_id")
    if (
        not session_id
        or stored is None
        or not hmac.compare_digest(session_id.encode("utf-8"), str(stored).encode("utf-8"))
    ):
        raise HTTPException(status_code=403, detail="Invalid or missing session-id header.")
    return record


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


async def _insert_row(table: str, row: dict, match_columns: tuple[str, ...], what: str) -> None:
    """Insert a row whose id was made in Python, at most once (Build L.2).

    The id exists before the insert, so a lost response is resolved by looking
    for the row: landed() matches every column in match_columns. A duplicate-key
    error (23505) on a re-send means an earlier attempt committed; on the first
    send it is a real error.
    """
    sends = 0

    def insert() -> None:
        nonlocal sends
        sends += 1
        try:
            get_supabase_client().table(table).insert(row).execute()
        except APIError as exc:
            if sends > 1 and exc.code == "23505":
                logger.warning("%s: duplicate key on a re-send; an earlier attempt committed", what)
                return
            raise

    def landed() -> bool:
        query = get_supabase_client().table(table).select("id")
        for column in match_columns:
            query = query.eq(column, row[column])
        return bool(query.execute().data)

    await supabase_call(insert, what=what, landed=landed)


class _PauseMovedOn(Exception):
    """Raised by /resume's re-read: the row changed since the pre-read, and not by this answer."""


# ---------------------------------------------------------------------------
# Background tasks — the pipeline and custom-question runs
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


@app.post("/api/upload", dependencies=[Depends(require_agent_work_enabled)])
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

    await _insert_row(
        "analyses",
        {
            "id": analysis_id,
            "status": "profiling",
            "original_filename": file.filename,
            "stored_filename": stored_filename,
            "file_size": len(content),
            "session_id": session_id,
        },
        ("id", "session_id"),
        "upload insert",
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
    response = await supabase_call(
        lambda: client.table("analyses")
        .select("id, status, error_message, pause_data")
        .eq("id", analysis_id)
        .execute(),
        what="status read",
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
    response = await supabase_call(
        lambda: client.table("analyses").select("*").eq("id", analysis_id).execute(),
        what="analysis read",
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


@app.post(
    "/api/analysis/{analysis_id}/question",
    response_model=QuestionResponse,
    dependencies=[Depends(require_agent_work_enabled)],
)
async def post_question(
    analysis_id: str,
    request: QuestionRequest,
    background_tasks: BackgroundTasks,
    record: dict = Depends(get_session),
) -> QuestionResponse:
    # A question reads the cleaned dataset, which exists only once the analysis is complete.
    if record.get("status") != "complete":
        raise HTTPException(
            status_code=409,
            detail="USER_ERROR: Questions can be asked only after the analysis is complete.",
        )
    question_id = str(uuid.uuid4())
    await _insert_row(
        "questions",
        {
            "id": question_id,
            "analysis_id": analysis_id,
            "question": request.question,
            "status": "pending",
        },
        ("id",),
        "question insert",
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
    response = await supabase_call(
        lambda: client.table("questions")
        .select("*")
        .eq("id", question_id)
        .eq("analysis_id", analysis_id)
        .execute(),
        what="question read",
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


@app.post(
    "/api/analysis/{analysis_id}/resume",
    response_model=StatusResponse,
    dependencies=[Depends(require_agent_work_enabled)],
)
async def resume_analysis(
    analysis_id: str,
    body: PauseResumeRequest,
    _session: dict = Depends(get_session),
) -> StatusResponse:
    client = get_supabase_client()
    response = await supabase_call(
        lambda: client.table("analyses")
        .select("id, status, pause_data, updated_at")
        .eq("id", analysis_id)
        .execute(),
        what="resume read",
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
    # A lost response is resolved by re-reading the row (Build L.2): this answer
    # stored with pause_data cleared means the update landed; the row exactly as
    # read means it did not, and the same conditional update is re-sent (its
    # condition lets it apply at most once); anything else means the pause moved on.
    moved_on = HTTPException(
        status_code=409,
        detail="The pause this response answers is no longer active. Refresh and try again.",
    )
    sends = 0

    def send_update() -> APIResponse:
        nonlocal sends
        sends += 1
        return query.execute()

    def reread() -> Optional[dict]:
        rows = (
            client.table("analyses")
            .select("status, pause_data, user_pause_response, updated_at")
            .eq("id", analysis_id)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def answer_is_stored(row: Optional[dict]) -> bool:
        return (
            row is not None
            and row.get("user_pause_response") == body.response
            and row.get("pause_data") is None
        )

    def update_landed() -> bool:
        row = reread()
        if answer_is_stored(row):
            return True
        if row is not None and row.get("status") == status and row.get("updated_at") == read_updated_at:
            return False
        raise _PauseMovedOn()

    try:
        updated = await supabase_call(send_update, what="resume update", landed=update_landed)
    except _PauseMovedOn:
        logger.warning("resume update for analysis_id=%s: the pause moved on after a lost response", analysis_id)
        raise moved_on from None
    if updated is not None and not updated.data:
        # A re-send matching no rows may follow an earlier attempt that committed
        # after the re-read; only this answer stored makes it a success.
        if sends == 1 or not answer_is_stored(await supabase_call(reread, what="resume re-read")):
            raise moved_on
        logger.warning(
            "resume update for analysis_id=%s: a re-send matched no rows, but the answer "
            "is stored; an earlier attempt committed",
            analysis_id,
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
    response = await supabase_call(
        lambda: client.table("analyses")
        .select("chart_paths")
        .eq("id", analysis_id)
        .execute(),
        what="charts read",
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    chart_paths = response.data[0].get("chart_paths") or []
    return {"chart_paths": chart_paths}
