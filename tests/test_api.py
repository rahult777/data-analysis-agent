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
from unittest.mock import AsyncMock, MagicMock, patch

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
    assert "unsupported" in detail or "file type" in detail


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


# ---------------------------------------------------------------------------
# Group 2 — Session validation
# ---------------------------------------------------------------------------


def test_missing_session_header() -> None:
    """GET /status without session-id header returns 403."""
    mock_client = make_supabase_mock(
        {
            "id": "some-id",
            "session_id": "correct-session",
            "status": "profiling",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get("/api/analysis/some-id/status")
    assert response.status_code == 403


def test_wrong_session_id() -> None:
    """GET /status with wrong session-id header returns 403."""
    mock_client = make_supabase_mock(
        {
            "id": "some-id",
            "session_id": "correct-session",
            "status": "profiling",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            "/api/analysis/some-id/status",
            headers={"session-id": "wrong-session"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Group 3 — Status endpoint
# ---------------------------------------------------------------------------


def test_status_complete() -> None:
    """Status complete returns 200 with status=complete and progress_pct=100.0."""
    mock_client = make_supabase_mock(
        {
            "id": "test-id",
            "session_id": "test-session",
            "status": "complete",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            "/api/analysis/test-id/status",
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
            "id": "test-id",
            "session_id": "test-session",
            "status": "profiling",
            "error_message": None,
        }
    )
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get(
            "/api/analysis/test-id/status",
            headers={"session-id": "test-session"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["progress_pct"] == 20.0
    assert body["current_agent"] == "profiler"


def test_status_not_found() -> None:
    """Empty Supabase data triggers 404 in get_session before status endpoint runs."""
    mock_client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = []
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = execute_result
    with patch("backend.main.get_supabase_client", return_value=mock_client):
        response = client.get("/api/analysis/test-id/status")
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
# Group 5 — Integration tests (skipped — require live services)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live ANTHROPIC_API_KEY, Supabase, and background tasks")
def test_full_pipeline_upload_and_run() -> None:
    pass


@pytest.mark.skip(reason="Requires live services")
def test_question_endpoint_with_live_data() -> None:
    pass
