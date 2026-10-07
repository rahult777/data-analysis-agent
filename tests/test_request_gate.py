"""Tests for the browser-origin settings and the request gate.

ALLOWED_ORIGINS is parsed by a pure function, called with plain dicts; backend.config is never reloaded.
The gate is tested at the ASGI level with a receive that records every await, so "refused before the body
is read" means the gate never awaited receive and the app behind it never ran; then through the real app.
"""

import asyncio
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import config
from backend.main import app
from backend.utils import file_handler
from backend.utils.request_gate import RequestGate

AID = "11111111-1111-4111-8111-111111111111"
ALLOWED = ["http://localhost:3000", "http://127.0.0.1:3000"]
FOREIGN = "https://example.invalid"
READ_ONLY = {"detail": "SYSTEM_ERROR: Analysis is not available on this server (read-only mode)."}
CROSS_ORIGIN = {"detail": "Cross-origin request refused."}
FILE_TOO_LARGE = {"detail": "USER_ERROR: This file is too large. Maximum size is 100MB."}
REQUEST_TOO_LARGE = {"detail": "USER_ERROR: This request is too large."}
STATE_CHANGING = ["POST", "PUT", "PATCH", "DELETE"]
ANY_PATH = [
    "/api/upload",
    f"/api/analysis/{AID}/question",
    f"/api/analysis/{AID}/resume",
    "/no/such/route",
    "/api/upload/",
]

client = TestClient(app)


# ---------------------------------------------------------------------------
# ALLOWED_ORIGINS (pure function)
# ---------------------------------------------------------------------------


def test_allowed_origins_default_to_the_local_frontend_when_unset() -> None:
    assert config.allowed_origins({"LANGCHAIN_TRACING_V2": "true"}) == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


@pytest.mark.parametrize("value", ["", " ", " , ,"], ids=["empty", "blank", "only-commas"])
def test_allowed_origins_set_but_empty_allows_no_browser_origin(value: str) -> None:
    assert config.allowed_origins({"ALLOWED_ORIGINS": value}) == []


def test_allowed_origins_items_are_stripped_and_empty_items_ignored() -> None:
    value = " http://localhost:5173 ,, https://app.example.com ,http://[::1]:8080"
    assert config.allowed_origins({"ALLOWED_ORIGINS": value}) == [
        "http://localhost:5173",
        "https://app.example.com",
        "http://[::1]:8080",
    ]


@pytest.mark.parametrize(
    "item",
    [
        "*",
        "https://*.example.com",
        "null",
        "http://localhost:3000/",
        "http://localhost:3000/app",
        "http://localhost:3000?next=1",
        "http://localhost:3000#top",
        "localhost:3000",
        "ftp://example.com",
        "http://",
        "http://user@example.com",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:port",
        "http://LOCALHOST:3000",
        "http://local host:3000",
        "http://localhost:80",
        "https://example.com:443",
        "http://localhost:03000",
    ],
)
def test_allowed_origins_refuse_anything_but_an_exact_origin(item: str) -> None:
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        config.allowed_origins({"ALLOWED_ORIGINS": f"http://localhost:3000,{item}"})


@pytest.mark.parametrize(
    "item, fix",
    [
        ("http://localhost:80", "drop the default port"),
        ("https://example.com:443", "drop the default port"),
        ("http://localhost:03000", "remove the leading zero"),
    ],
    ids=["http-80", "https-443", "leading-zero"],
)
def test_allowed_origins_name_the_fix_for_a_port_a_browser_never_sends(item: str, fix: str) -> None:
    with pytest.raises(ValueError, match=fix) as excinfo:
        config.allowed_origins({"ALLOWED_ORIGINS": item})
    assert f"ALLOWED_ORIGINS item {item!r}" in str(excinfo.value)


def test_allowed_origins_keep_a_port_that_is_not_the_scheme_default() -> None:
    value = "http://localhost:3000,https://example.com:8443,http://example.com:443,https://example.com:80"
    assert config.allowed_origins({"ALLOWED_ORIGINS": value}) == value.split(",")


# ---------------------------------------------------------------------------
# The gate at the ASGI level
# ---------------------------------------------------------------------------


class Receive:
    """Hands out scripted request messages and counts every await."""

    def __init__(self, *bodies: bytes) -> None:
        self.messages = [
            {"type": "http.request", "body": body, "more_body": index < len(bodies) - 1}
            for index, body in enumerate(bodies or (b"",))
        ]
        self.awaits = 0

    async def __call__(self) -> dict:
        self.awaits += 1
        return self.messages.pop(0) if self.messages else {"type": "http.disconnect"}


class Inner:
    """The app behind the gate: records each call and, for a state-changing request, reads the whole body."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict, Any, Any]] = []
        self.body = b""

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.calls.append((scope, receive, send))
        if scope["type"] != "http":
            return
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            while True:
                message = await receive()
                self.body += message.get("body", b"")
                if not message.get("more_body"):
                    break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


class Sent:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.messages if m["type"] == "http.response.start")

    @property
    def headers(self) -> dict[str, str]:
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return {k.decode("latin-1"): v.decode("latin-1") for k, v in start["headers"]}

    @property
    def json(self) -> dict:
        return json.loads(b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"))


def http_scope(method: str, path: str, headers: dict[str, str] | None = None) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


def run_gate(scope: dict, receive: Receive) -> tuple[Inner, Sent]:
    inner, sent = Inner(), Sent()
    asyncio.run(RequestGate(inner, allowed_origins=list(ALLOWED))(scope, receive, sent))
    return inner, sent


@pytest.mark.parametrize("origin", [FOREIGN, "null", "http://localhost:3001"])
@pytest.mark.parametrize("path", ANY_PATH)
@pytest.mark.parametrize("method", STATE_CHANGING)
def test_gate_refuses_a_foreign_origin_with_403_before_reading_the_body(
    agent_work_on: None, method: str, path: str, origin: str
) -> None:
    receive = Receive(b"a,b\n1,2\n")
    inner, sent = run_gate(http_scope(method, path, {"origin": origin, "content-length": "8"}), receive)
    assert (sent.status, sent.json) == (403, CROSS_ORIGIN)
    assert "access-control-allow-origin" not in sent.headers
    assert receive.awaits == 0
    assert inner.calls == []


def test_gate_checks_the_origin_before_the_read_only_refusal() -> None:
    receive = Receive(b"{}")
    inner, sent = run_gate(http_scope("POST", "/api/upload", {"origin": FOREIGN}), receive)
    assert (sent.status, sent.json) == (403, CROSS_ORIGIN)
    assert (receive.awaits, inner.calls) == (0, [])


@pytest.mark.parametrize("headers", [{}, {"origin": "http://localhost:3000"}], ids=["no-origin", "allowed-origin"])
@pytest.mark.parametrize("path", ANY_PATH)
@pytest.mark.parametrize("method", STATE_CHANGING)
def test_gate_refuses_with_503_before_reading_the_body_when_agent_work_is_not_allowed(
    method: str, path: str, headers: dict[str, str]
) -> None:
    receive = Receive(b"x" * 10)
    inner, sent = run_gate(http_scope(method, path, {**headers, "content-length": "10"}), receive)
    assert (sent.status, sent.json) == (503, READ_ONLY)
    assert receive.awaits == 0
    assert inner.calls == []


def test_gate_refuses_with_503_when_tracing_is_on_but_agent_work_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TRACING_ENABLED", True)
    monkeypatch.setattr(config, "AGENT_WORK_ENABLED", False)
    receive = Receive(b"{}")
    inner, sent = run_gate(http_scope("POST", f"/api/analysis/{AID}/question"), receive)
    assert (sent.status, sent.json) == (503, READ_ONLY)
    assert (receive.awaits, inner.calls) == (0, [])


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_gate_passes_safe_methods_through_untouched(method: str) -> None:
    """Even from a foreign origin and with agent work off: reads are public, and CORS answers preflights."""
    scope = http_scope(method, f"/api/analysis/{AID}/status", {"origin": FOREIGN})
    receive = Receive()
    inner, sent = run_gate(scope, receive)
    assert sent.status == 200
    assert len(inner.calls) == 1
    assert inner.calls[0][0] is scope and inner.calls[0][1] is receive


def test_gate_passes_the_lifespan_scope_through_untouched() -> None:
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
    receive, inner, sent = Receive(), Inner(), Sent()
    asyncio.run(RequestGate(inner, allowed_origins=list(ALLOWED))(scope, receive, sent))
    assert inner.calls == [(scope, receive, sent)]


@pytest.mark.parametrize("headers", [{}, {"origin": "http://127.0.0.1:3000"}], ids=["no-origin", "allowed-origin"])
def test_gate_lets_allowed_agent_work_through_with_its_body(agent_work_on: None, headers: dict[str, str]) -> None:
    receive = Receive(b'{"question": ', b'"q?"}')
    inner, sent = run_gate(http_scope("POST", f"/api/analysis/{AID}/question", headers), receive)
    assert sent.status == 200
    assert inner.body == b'{"question": "q?"}'


@pytest.mark.parametrize(
    "path, max_file_size, declared, refused",
    [
        ("/api/upload", 1000, 1_049_577, FILE_TOO_LARGE),  # 1000 + 1 MiB is the cap; one byte over
        ("/api/upload", 1000, 1_049_576, None),
        (f"/api/analysis/{AID}/question", 1000, 65_537, REQUEST_TOO_LARGE),  # 64 KiB cap; one byte over
        (f"/api/analysis/{AID}/question", 1000, 65_536, None),
        ("/api/upload/", 1000, 65_537, REQUEST_TOO_LARGE),  # only the exact upload path gets the file cap
    ],
)
def test_gate_refuses_a_declared_content_length_over_the_cap_with_413_before_reading_the_body(
    agent_work_on: None,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    max_file_size: int,
    declared: int,
    refused: dict | None,
) -> None:
    monkeypatch.setattr(file_handler, "MAX_FILE_SIZE", max_file_size)
    receive = Receive(b"x")
    inner, sent = run_gate(http_scope("POST", path, {"content-length": str(declared)}), receive)
    if refused is None:
        assert sent.status == 200 and len(inner.calls) == 1
    else:
        assert (sent.status, sent.json) == (413, refused)
        assert (receive.awaits, inner.calls) == (0, [])


@pytest.mark.parametrize(
    "path, max_file_size, chunk, chunks, awaits_at_refusal, refused",
    [
        # 64 KiB cap, 16 KiB chunks: 4 chunks reach exactly 65,536 bytes; the 5th passes the cap.
        (f"/api/analysis/{AID}/question", 1000, 16 * 1024, 10, 5, REQUEST_TOO_LARGE),
        # File cap 0 + 1 MiB, 512 KiB chunks: 2 chunks reach exactly 1,048,576 bytes; the 3rd passes it.
        ("/api/upload", 0, 512 * 1024, 6, 3, FILE_TOO_LARGE),
    ],
    ids=["request", "upload"],
)
def test_gate_stops_a_streamed_body_at_the_read_that_passes_the_cap(
    agent_work_on: None,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    max_file_size: int,
    chunk: int,
    chunks: int,
    awaits_at_refusal: int,
    refused: dict,
) -> None:
    """No Content-Length (a chunked upload): the body is counted as the app reads it."""
    monkeypatch.setattr(file_handler, "MAX_FILE_SIZE", max_file_size)
    receive = Receive(*([b"x" * chunk] * chunks))
    inner, sent = Inner(), Sent()
    with pytest.raises(StarletteHTTPException) as stopped:
        asyncio.run(RequestGate(inner, allowed_origins=list(ALLOWED))(http_scope("POST", path), receive, sent))
    assert (stopped.value.status_code, {"detail": stopped.value.detail}) == (413, refused)
    assert receive.awaits == awaits_at_refusal
    assert len(inner.body) == chunk * (awaits_at_refusal - 1)


def test_gate_lets_a_streamed_body_of_exactly_the_cap_through(agent_work_on: None) -> None:
    receive = Receive(*([b"x" * (16 * 1024)] * 4))
    inner, sent = run_gate(http_scope("POST", f"/api/analysis/{AID}/question"), receive)
    assert sent.status == 200
    assert len(inner.body) == 65_536


# ---------------------------------------------------------------------------
# The gate inside the real app
# ---------------------------------------------------------------------------


def stream(data: bytes) -> Iterator[bytes]:
    """A generator body: httpx sends it without a Content-Length, so only the gate's count can stop it."""
    yield data


def test_app_answers_a_too_large_streamed_json_body_with_the_request_413(agent_work_on: None) -> None:
    supabase, task = MagicMock(), AsyncMock()
    with (
        patch("backend.main.get_supabase_client", return_value=supabase),
        patch("backend.main.run_question_task", new=task),
    ):
        response = client.post(
            f"/api/analysis/{AID}/question",
            content=stream(b'{"question": "' + b"q" * 70_000 + b'"}'),
            headers={"content-type": "application/json", "session-id": "s"},
        )
    assert "content-length" not in response.request.headers
    assert (response.status_code, response.json()) == (413, REQUEST_TOO_LARGE)
    supabase.table.assert_not_called()
    task.assert_not_called()


def test_app_answers_a_too_large_streamed_upload_with_the_file_413(
    agent_work_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_handler, "MAX_FILE_SIZE", 0)
    with (
        patch("backend.main.validate_file") as validate,
        patch("backend.main.save_temp_file", new=AsyncMock()) as save,
        patch("backend.main.run_pipeline_task", new=AsyncMock()) as pipeline,
    ):
        response = client.post(
            "/api/upload",
            content=stream(b"x" * (1024 * 1024 + 1)),
            headers={"content-type": "multipart/form-data; boundary=b"},
        )
    assert (response.status_code, response.json()) == (413, FILE_TOO_LARGE)
    for work in (validate, save, pipeline):
        work.assert_not_called()


def test_app_answers_a_declared_too_large_body_before_the_route_runs(agent_work_on: None) -> None:
    with patch("backend.main.get_supabase_client") as get_client:
        response = client.post(
            f"/api/analysis/{AID}/question",
            content=b'{"question": "' + b"q" * 70_000 + b'"}',
            headers={"content-type": "application/json", "session-id": "s"},
        )
    assert (response.status_code, response.json()) == (413, REQUEST_TOO_LARGE)
    get_client.assert_not_called()


def test_app_refuses_a_foreign_origin_with_403_before_any_work(agent_work_on: None) -> None:
    with patch("backend.main.get_supabase_client") as get_client:
        response = client.post(
            f"/api/analysis/{AID}/question", json={"question": "q?"}, headers={"origin": FOREIGN, "session-id": "s"}
        )
    assert (response.status_code, response.json()) == (403, CROSS_ORIGIN)
    get_client.assert_not_called()


def test_the_gate_runs_inside_cors_with_the_configured_origins() -> None:
    assert [m.cls for m in app.user_middleware] == [CORSMiddleware, RequestGate]
    assert app.user_middleware[1].kwargs["allowed_origins"] is config.ALLOWED_ORIGINS
    assert app.user_middleware[0].kwargs["allow_origins"] is config.ALLOWED_ORIGINS


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def preflight(origin: str, method: str = "POST", request_headers: str | None = None) -> Any:
    headers = {"origin": origin, "access-control-request-method": method}
    if request_headers is not None:
        headers["access-control-request-headers"] = request_headers
    return client.options("/api/upload", headers=headers)


@pytest.mark.parametrize("origin", ALLOWED)
def test_cors_preflight_from_an_allowed_origin_allows_get_post_and_the_two_headers(origin: str) -> None:
    response = preflight(origin, request_headers="content-type, session-id")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-methods"] == "GET, POST"
    allowed = {h.strip().lower() for h in response.headers["access-control-allow-headers"].split(",")}
    assert {"content-type", "session-id"} <= allowed
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "method, request_headers",
    [("DELETE", None), ("PUT", None), ("POST", "authorization")],
    ids=["delete", "put", "header"],
)
def test_cors_preflight_refuses_other_methods_and_headers(method: str, request_headers: str | None) -> None:
    assert preflight("http://localhost:3000", method, request_headers).status_code == 400


@pytest.mark.parametrize("agent_work", [False, True], ids=["read-only", "agent-work-on"])
def test_cors_preflight_from_a_foreign_origin_is_400_never_503(
    monkeypatch: pytest.MonkeyPatch, agent_work: bool
) -> None:
    monkeypatch.setattr(config, "TRACING_ENABLED", agent_work)
    monkeypatch.setattr(config, "AGENT_WORK_ENABLED", agent_work)
    response = preflight(FOREIGN, request_headers="content-type")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_read_only_refusal_to_an_allowed_origin_carries_its_cors_header() -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
        headers={"origin": "http://localhost:3000"},
    )
    assert (response.status_code, response.json()) == (503, READ_ONLY)
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_size_refusal_to_an_allowed_origin_carries_its_cors_header(agent_work_on: None) -> None:
    response = client.post(
        f"/api/analysis/{AID}/question",
        content=stream(b'{"question": "' + b"q" * 70_000 + b'"}'),
        headers={"content-type": "application/json", "session-id": "s", "origin": "http://127.0.0.1:3000"},
    )
    assert (response.status_code, response.json()) == (413, REQUEST_TOO_LARGE)
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_cors_adds_no_headers_to_the_cross_origin_refusal(agent_work_on: None) -> None:
    response = client.post(
        f"/api/analysis/{AID}/question", json={"question": "q?"}, headers={"origin": FOREIGN, "session-id": "s"}
    )
    assert response.status_code == 403
    assert [name for name in response.headers if name.lower().startswith("access-control-")] == []


def test_cors_answers_a_public_read_from_an_allowed_origin_with_its_origin() -> None:
    with patch("backend.main.get_supabase_client") as get_client:
        get_client.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"chart_paths": ["c.png"]}
        ]
        response = client.get(f"/api/analysis/{AID}/charts", headers={"origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["vary"] == "Origin"
