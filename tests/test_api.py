"""Tests for backend/main.py — FastAPI API endpoints.

All tests use FastAPI TestClient with no live server, no live Supabase, no live Anthropic.
All Supabase calls are mocked using unittest.mock.patch with backend.main.X patch paths —
main.py imports get_supabase_client into its own namespace so backend.main is the only
interceptable namespace.

All tests run from the project root (CWD must be the repo root).
"""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from unittest.mock import AsyncMock, MagicMock, call, patch

from backend.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helper — Supabase mock factory
# ---------------------------------------------------------------------------


def make_supabase_mock(record: dict) -> MagicMock:
    """Return a MagicMock simulating get_supabase_client for one specific record.

    Handles all three chains used across endpoints:
      .table().select().eq().execute() -> data=[record]
      .table().update().eq().execute() -> data=[record]
      .table().insert().execute()      -> data=[record]
    """
    mock_client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = [record]
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = execute_result
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = execute_result
    mock_client.table.return_value.insert.return_value.execute.return_value = execute_result
    return mock_client


def post_rejected_upload(filename: str, content: bytes, content_type: str) -> str:
    """POST a file that validation must reject and return the 400 detail.

    Also asserts the rejection happened before any side effect: no analyses insert,
    no temp file, no pipeline task.
    """
    mock_client = make_supabase_mock({"id": "test-id", "session_id": "test-session"})
    save_mock = AsyncMock(return_value="stored.csv")
    pipeline_mock = AsyncMock()
    with (
        patch("backend.main.get_supabase_client", return_value=mock_client),
        patch("backend.main.save_temp_file", new=save_mock),
        patch("backend.main.run_pipeline_task", new=pipeline_mock),
    ):
        response = client.post(
            "/api/upload",
            files={"file": (filename, io.BytesIO(content), content_type)},
        )
    assert response.status_code == 400
    mock_client.table.return_value.insert.assert_not_called()
    save_mock.assert_not_called()
    pipeline_mock.assert_not_called()
    detail = response.json()["detail"]
    assert detail.startswith("USER_ERROR:")
    return detail


# ---------------------------------------------------------------------------
# Group 1 — File upload validation
# ---------------------------------------------------------------------------


def test_upload_wrong_file_type() -> None:
    """POST with .txt file returns 400 — validate_file rejects non-CSV/Excel."""
    response = client.post(
        "/api/upload",
        files={"file": ("report.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "user_error" in detail
    assert "csv or excel file" in detail


def test_upload_file_too_large() -> None:
    """Patched validate_file raises ValueError simulating 100MB limit breach."""
    with patch(
        "backend.main.validate_file",
        side_effect=ValueError("File size exceeds the 100MB limit."),
    ):
        response = client.post(
            "/api/upload",
            files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")},
        )
    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "size" in detail or "100mb" in detail


def test_upload_valid_csv() -> None:
    """Valid CSV upload returns 200 with analysis_id and session_id."""
    mock_client = make_supabase_mock({"id": "test-id", "session_id": "test-session"})
    with (
        patch("backend.main.get_supabase_client", return_value=mock_client),
        patch("backend.main.save_temp_file", new=AsyncMock(return_value="stored.csv")),
        patch("backend.main.run_pipeline_task", new=AsyncMock()),
    ):
        response = client.post(
            "/api/upload",
            files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")},
        )
    assert response.status_code == 200
    body = response.json()
    assert "analysis_id" in body
    assert "session_id" in body


def test_upload_empty_csv_rejected() -> None:
    """0-byte CSV sent straight to the API returns 400 USER_ERROR and creates nothing."""
    detail = post_rejected_upload("data.csv", b"", "text/csv")
    assert "empty" in detail.lower()


def test_upload_header_only_csv_rejected() -> None:
    """Header-only CSV returns 400 USER_ERROR before any record, file, or pipeline run."""
    detail = post_rejected_upload("data.csv", b"a,b\n", "text/csv")
    assert "no data rows" in detail


def test_upload_header_only_xlsx_rejected() -> None:
    """Header-only XLSX returns 400 USER_ERROR before any record, file, or pipeline run."""
    workbook = Workbook()
    workbook.active.append(["a", "b"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    detail = post_rejected_upload(
        "data.xlsx",
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert "no data rows" in detail


# ---------------------------------------------------------------------------
# Group 2 — Session validation (strict POST routes only)
# ---------------------------------------------------------------------------

AID = "11111111-1111-4111-8111-111111111111"
QID = "22222222-2222-4222-8222-222222222222"


def test_missing_session_header() -> None:
    """POST /question without session-id returns 403 before any insert or LLM task."""
    mock_client = make_supabase_mock({"id": AID, "session_id": "correct-session"})
    task_mock = AsyncMock()
    with (
        patch("backend.main.get_supabase_client", return_value=mock_client),
        patch("backend.main.run_question_task", new=task_mock),
    ):
        response = client.post(f"/api/analysis/{AID}/question", json={"question": "q?"})
    assert response.status_code == 403
    mock_client.table.return_value.insert.assert_not_called()
    task_mock.assert_not_called()


def test_wrong_session_id() -> None:
    """POST /question with a wrong session-id returns 403 before any insert or LLM task."""
    mock_client = make_supabase_mock({"id": AID, "session_id": "correct-session"})
    task_mock = AsyncMock()
    with (
        patch("backend.main.get_supabase_client", return_value=mock_client),
        patch("backend.main.run_question_task", new=task_mock),
    ):
        response = client.post(
            f"/api/analysis/{AID}/question",
            json={"question": "q?"},
            headers={"session-id": "wrong-session"},
        )
    assert response.status_code == 403
    mock_client.table.return_value.insert.assert_not_called()
    task_mock.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"session-id": "wrong-session"}])
def test_resume_rejects_bad_session_before_update(headers: dict) -> None:
    """POST /resume without a valid session-id returns 403 and never writes."""
    mock_client = make_supabase_mock(
        {"id": AID, "session_id": "correct-session", "status": "domain_pause", "error_message": None}
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.post(
            f"/api/analysis/{AID}/resume",
            json={"response": {"decision": "confirm"}},
            headers=headers,
        )
    assert response.status_code == 403
    mock_client.table.return_value.update.assert_not_called()


# ---------------------------------------------------------------------------
# Group 3 — Status endpoint
# ---------------------------------------------------------------------------


def test_status_complete() -> None:
    """Status complete returns 200 with status=complete and progress_pct=100.0."""
    mock_client = make_supabase_mock(
        {
            "id": AID,
            "session_id": "test-session",
            "status": "complete",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            f"/api/analysis/{AID}/status",
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["progress_pct"] == 100.0


def test_status_profiling() -> None:
    """Status profiling returns progress_pct=20.0, current_agent=profiler."""
    mock_client = make_supabase_mock(
        {
            "id": AID,
            "session_id": "test-session",
            "status": "profiling",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            f"/api/analysis/{AID}/status",
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["progress_pct"] == 20.0
    assert body["current_agent"] == "profiler"


@pytest.mark.parametrize(
    ("stored", "returned"),
    [
        ("SYSTEM_ERROR: Failed to read /Users/someone/backend/uploads/x.csv", "SYSTEM_ERROR"),
        ("USER_ERROR: The file has no data rows.", "USER_ERROR"),
        ("unprefixed failure text", "SYSTEM_ERROR"),
        (None, None),
    ],
)
def test_status_error_message_is_category_only(stored: str | None, returned: str | None) -> None:
    """The public status route returns only the error category, never the stored detail."""
    mock_client = make_supabase_mock(
        {"id": AID, "session_id": "s", "status": "error", "error_message": stored}
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(f"/api/analysis/{AID}/status")
    assert response.status_code == 200
    assert response.json()["error_message"] == returned
    if stored and ":" in stored:
        assert stored.split(":", 1)[1].strip() not in response.text


def test_status_not_found() -> None:
    """A well-formed but nonexistent analysis_id returns 404 from the status lookup."""
    mock_client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = []
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = execute_result
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(f"/api/analysis/{AID}/status")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Group 4 — Resume endpoint
# ---------------------------------------------------------------------------


def test_resume_not_in_pause_state() -> None:
    """Resume on status=complete returns 400 with 'not in a pause state' message."""
    mock_client = make_supabase_mock(
        {
            "id": "test-id",
            "session_id": "test-session",
            "status": "complete",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.post(
            "/api/analysis/test-id/resume",
            json={"response": {"decision": "confirm"}},
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 400
    assert "not in a pause state" in response.json()["detail"].lower()


def test_resume_valid_domain_pause() -> None:
    """Resume on status=domain_pause returns 200 with status=profiling."""
    mock_client = make_supabase_mock(
        {
            "id": "test-id",
            "session_id": "test-session",
            "status": "domain_pause",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.post(
            "/api/analysis/test-id/resume",
            json={"response": {"decision": "confirm"}},
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "profiling"


# ---------------------------------------------------------------------------
# Group 5 — Get question endpoint
# ---------------------------------------------------------------------------


def make_question_mock(data: list[dict]) -> MagicMock:
    """Chainable mock for get_question's two .eq() calls on the questions table."""
    mock_response = MagicMock()
    mock_response.data = data
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table  # chainable across BOTH .eq() calls
    mock_table.execute.return_value = mock_response
    mock_client = MagicMock()
    mock_client.table.return_value = mock_table
    return mock_client


def test_get_question_success() -> None:
    """GET question returns 200 with fields correctly mapped (id -> question_id)."""
    mock_client = make_question_mock(
        [
            {
                "id": QID,
                "analysis_id": AID,
                "question": "test?",
                "status": "complete",
                "answer": "42",
                "pandas_code": "df.shape",
            }
        ]
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            f"/api/analysis/{AID}/question/{QID}",
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["question_id"] == QID
    assert body["answer"] == "42"


def test_get_question_not_found() -> None:
    """A well-formed but nonexistent question returns 404 from the scoped lookup."""
    mock_client = make_question_mock([])
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            f"/api/analysis/{AID}/question/{QID}",
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 404


def test_get_question_mismatched_pair_scoped_404() -> None:
    """A question_id paired with a different analysis_id returns 404: the query
    filters on BOTH ids, so a mismatched pair can never return another analysis's row."""
    other_aid = "33333333-3333-4333-8333-333333333333"
    mock_client = make_question_mock([])
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(f"/api/analysis/{other_aid}/question/{QID}")
    assert response.status_code == 404
    eq_calls = mock_client.table.return_value.eq.call_args_list
    assert call("id", QID) in eq_calls
    assert call("analysis_id", other_aid) in eq_calls


# ---------------------------------------------------------------------------
# Group 5b — Public read access (read-only GET routes)
# ---------------------------------------------------------------------------

FULL_RECORD = {
    "id": AID,
    "session_id": "correct-session",
    "original_filename": "iris.csv",
    "stored_filename": "stored-abc.csv",
    "status": "complete",
    "error_message": None,
    "created_at": "2026-09-21T00:00:00+00:00",
    "row_count": 15,
    "column_count": 5,
    "data_quality_score": 0.9,
    "chart_paths": ["charts/x.png"],
}

PUBLIC_GET_PATHS = [
    f"/api/analysis/{AID}/status",
    f"/api/analysis/{AID}",
    f"/api/analysis/{AID}/charts",
]

HEADER_CASES = [{}, {"session-id": "wrong-session"}]


@pytest.mark.parametrize("headers", HEADER_CASES, ids=["no-header", "wrong-header"])
@pytest.mark.parametrize("path", PUBLIC_GET_PATHS)
def test_public_get_succeeds_without_valid_session(path: str, headers: dict) -> None:
    """Relaxed GET routes return 200 with no session-id or a wrong one."""
    mock_client = make_supabase_mock(FULL_RECORD)
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(path, headers=headers)
    assert response.status_code == 200


@pytest.mark.parametrize("headers", HEADER_CASES, ids=["no-header", "wrong-header"])
def test_public_get_question_succeeds_without_valid_session(headers: dict) -> None:
    mock_client = make_question_mock(
        [{"id": QID, "analysis_id": AID, "question": "q?", "status": "complete", "answer": "a", "pandas_code": "df"}]
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(f"/api/analysis/{AID}/question/{QID}", headers=headers)
    assert response.status_code == 200
    assert response.json()["answer"] == "a"


def test_public_get_analysis_returns_data_but_never_session_id() -> None:
    """The public analysis read carries the report data but never session_id or stored_filename."""
    mock_client = make_supabase_mock(FULL_RECORD)
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(f"/api/analysis/{AID}")
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "iris.csv"
    assert body["row_count"] == 15
    assert "session_id" not in body
    assert "stored_filename" not in body
    assert "correct-session" not in response.text


@pytest.mark.parametrize("path", [f"/api/analysis/{AID}", f"/api/analysis/{AID}/charts"])
def test_public_get_nonexistent_uuid_404(path: str) -> None:
    """A well-formed but nonexistent analysis_id still returns a real 404."""
    mock_client = make_supabase_mock({})
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(path)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/analysis/not-a-uuid/status",
        "/api/analysis/not-a-uuid",
        "/api/analysis/not-a-uuid/charts",
        f"/api/analysis/not-a-uuid/question/{QID}",
        f"/api/analysis/{AID}/question/not-a-uuid",
        # uuid.UUID() accepts these, but Postgres rejects the urn form (22P02).
        f"/api/analysis/urn:uuid:{AID}/status",
        f"/api/analysis/{{{AID}}}/status",
        f"/api/analysis/{AID}/question/urn:uuid:{QID}",
    ],
)
def test_public_get_malformed_id_404_before_db(path: str) -> None:
    """A malformed analysis_id or question_id returns 404 without touching the database."""
    with patch("backend.main.get_supabase_client") as get_client:
        response = client.get(path)
    assert response.status_code == 404
    get_client.assert_not_called()


def _route_dependency_calls(path: str, method: str) -> list:
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return [dep.call for dep in route.dependant.dependencies]
    raise AssertionError(f"route not found: {method} {path}")


def test_route_auth_boundary_structural() -> None:
    """Strict POST routes use get_session; the four read-only GETs use
    get_public_read_access and never get_session."""
    from backend.main import get_public_read_access, get_session

    for path in ("/api/analysis/{analysis_id}/question", "/api/analysis/{analysis_id}/resume"):
        calls = _route_dependency_calls(path, "POST")
        assert get_session in calls
        assert get_public_read_access not in calls
    for path in (
        "/api/analysis/{analysis_id}",
        "/api/analysis/{analysis_id}/status",
        "/api/analysis/{analysis_id}/charts",
        "/api/analysis/{analysis_id}/question/{question_id}",
    ):
        calls = _route_dependency_calls(path, "GET")
        assert get_public_read_access in calls
        assert get_session not in calls


# ---------------------------------------------------------------------------
# Group 6 — Integration tests (skipped — require live services)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY, Supabase, and background tasks")
def test_full_pipeline_upload_and_run() -> None:
    pass


@pytest.mark.skip(reason="Requires live services")
def test_question_endpoint_with_live_data() -> None:
    pass
