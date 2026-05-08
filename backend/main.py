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
        validate_file(filename=file.filename, file_size=len(content))
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
    _session: str = Depends(get_session),
) -> StatusResponse:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses")
        .select("id, status, error_message")
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
        error_message=record.get("error_message"),
    )


@app.get("/api/analysis/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    _session: str = Depends(get_session),
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


@app.post("/api/analysis/{analysis_id}/resume", response_model=StatusResponse)
async def resume_analysis(
    analysis_id: str,
    body: PauseResumeRequest,
    _session: str = Depends(get_session),
) -> StatusResponse:
    client = get_supabase_client()
    response = await asyncio.to_thread(
        lambda: client.table("analyses")
        .select("id, status, error_message")
        .eq("id", analysis_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    record = response.data[0]
    status = record["status"]
    if status not in ("domain_pause", "missing_value_pause", "outlier_pause"):
        raise HTTPException(status_code=400, detail="Analysis is not in a pause state.")
    restore_status = "profiling" if status == "domain_pause" else "cleaning"
    await asyncio.to_thread(
        lambda: client.table("analyses")
        .update({
            "user_pause_response": body.response,
            "status": restore_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", analysis_id)
        .execute()
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
    _session: str = Depends(get_session),
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
