"""Tests for backend/utils/supabase_retry.py and the shared client (Build L.2).

The helper's backoff is replaced suite-wide by the autouse `retry_sleep`
fixture (tests/conftest.py), so nothing here waits in real time.
"""

import ast
import asyncio
import logging
import pathlib
from typing import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from postgrest.exceptions import APIError
from pydantic import ValidationError
from storage3.exceptions import StorageApiError
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from backend.utils import file_handler
from backend.utils.supabase_client import get_supabase_client
from backend.utils.supabase_retry import TRANSIENT, supabase_call

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "backend"


def disconnect() -> httpx.RemoteProtocolError:
    return httpx.RemoteProtocolError("Server disconnected")


def flaky(*outcomes: object) -> tuple[Callable[[], object], dict]:
    """A sync fn that raises or returns each outcome in turn; counts its calls."""
    remaining = list(outcomes)
    calls = {"n": 0}

    def fn() -> object:
        calls["n"] += 1
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fn, calls


def run(fn: Callable[[], object], **kwargs: object) -> object:
    return asyncio.run(supabase_call(fn, what="test", **kwargs))


# ---------------------------------------------------------------------------
# the helper
# ---------------------------------------------------------------------------


def test_one_transient_failure_then_success(retry_sleep: AsyncMock, caplog: pytest.LogCaptureFixture) -> None:
    fn, calls = flaky(disconnect(), "ok")
    with caplog.at_level(logging.WARNING, logger="backend.utils.supabase_retry"):
        assert run(fn) == "ok"
    assert calls["n"] == 2
    assert [c.args[0] for c in retry_sleep.await_args_list] == [0.5]
    assert any("retrying" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("error_type", TRANSIENT)
def test_every_transient_type_is_retried(error_type: type[Exception]) -> None:
    fn, calls = flaky(error_type("drop"), "ok")
    assert run(fn) == "ok"
    assert calls["n"] == 2


def test_always_failing_raises_the_original_error_after_three_attempts(retry_sleep: AsyncMock) -> None:
    first = disconnect()
    fn, calls = flaky(first, httpx.ReadError("second"), httpx.ConnectError("third"))
    with pytest.raises(httpx.RemoteProtocolError) as raised:
        run(fn)
    assert raised.value is first
    assert calls["n"] == 3
    assert [c.args[0] for c in retry_sleep.await_args_list] == [0.5, 1.5]


def _http_status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/")
    return httpx.HTTPStatusError("500", request=request, response=httpx.Response(500, request=request))


NON_TRANSIENT = [
    pytest.param(lambda: APIError({"message": "bad uuid", "code": "22P02"}), id="postgrest-APIError"),
    pytest.param(lambda: StorageApiError("Duplicate", "Duplicate", 409), id="StorageApiError"),
    pytest.param(_http_status_error, id="HTTPStatusError"),
    pytest.param(lambda: ValidationError.from_exception_data("Row", []), id="ValidationError"),
    pytest.param(lambda: httpx.ReadTimeout("slow"), id="ReadTimeout"),
    pytest.param(lambda: httpx.WriteTimeout("slow"), id="WriteTimeout"),
    pytest.param(lambda: ValueError("x"), id="ValueError"),
]


@pytest.mark.parametrize("make_error", NON_TRANSIENT)
def test_non_transient_errors_are_raised_at_once(make_error: Callable[[], Exception], retry_sleep: AsyncMock) -> None:
    error = make_error()
    fn, calls = flaky(error, "never")
    with pytest.raises(type(error)):
        run(fn)
    assert calls["n"] == 1
    retry_sleep.assert_not_awaited()


def test_landed_true_logs_landed_and_does_not_resend(caplog: pytest.LogCaptureFixture) -> None:
    fn, calls = flaky(disconnect(), "never re-sent")
    landed_calls = {"n": 0}

    def landed() -> bool:
        landed_calls["n"] += 1
        return True

    with caplog.at_level(logging.WARNING, logger="backend.utils.supabase_retry"):
        assert run(fn, landed=landed) is None
    assert calls["n"] == 1
    assert landed_calls["n"] == 1
    assert any("landed despite the lost response" in r.getMessage() for r in caplog.records)


def test_landed_false_resends() -> None:
    fn, calls = flaky(disconnect(), "ok")
    assert run(fn, landed=lambda: False) == "ok"
    assert calls["n"] == 2


def test_landed_failing_transiently_uses_the_attempt_without_resending(retry_sleep: AsyncMock) -> None:
    """Attempt 2's landed() fails: fn is not re-sent; attempt 3 asks again, then re-sends."""
    fn, calls = flaky(disconnect(), "ok")
    landed, landed_calls = flaky(httpx.ConnectError("down"), False)
    assert run(fn, landed=landed) == "ok"
    assert calls["n"] == 2
    assert landed_calls["n"] == 2
    assert [c.args[0] for c in retry_sleep.await_args_list] == [0.5, 1.5]


def test_landed_always_failing_raises_fns_original_error() -> None:
    first = disconnect()
    fn, calls = flaky(first, "never")
    landed, _ = flaky(httpx.ConnectError("down"), httpx.ConnectError("down"))
    with pytest.raises(httpx.RemoteProtocolError) as raised:
        run(fn, landed=landed)
    assert raised.value is first
    assert calls["n"] == 1


def test_a_non_transient_error_from_landed_is_raised_at_once() -> None:
    fn, _ = flaky(disconnect(), "never")

    def landed() -> bool:
        raise LookupError("moved on")

    with pytest.raises(LookupError):
        run(fn, landed=landed)


# ---------------------------------------------------------------------------
# structural: every Supabase call goes through supabase_call
# ---------------------------------------------------------------------------

_EXEMPT = {"supabase_client.py", "supabase_retry.py"}


def _unwrapped_supabase_references(source: str) -> list[int]:
    """Line numbers of `.execute` / `.storage` references outside a supabase_call argument.

    A function passed by name to supabase_call (a fn or landed closure) counts
    as inside it.
    """
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "supabase_call"
    ]
    wrapped_args = {id(arg) for call in calls for arg in [*call.args, *(k.value for k in call.keywords)]}
    passed_names = {
        arg.id for call in calls for arg in [*call.args, *(k.value for k in call.keywords)]
        if isinstance(arg, ast.Name)
    }

    def inside(node: ast.AST) -> bool:
        while node in parents:
            if id(node) in wrapped_args:
                return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in passed_names:
                return True
            node = parents[node]
        return False

    return [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in ("execute", "storage") and not inside(node)
    ]


def test_every_supabase_call_in_the_backend_goes_through_supabase_call() -> None:
    offenders = {}
    for path in sorted(BACKEND_DIR.rglob("*.py")):
        if path.name in _EXEMPT:
            continue
        lines = _unwrapped_supabase_references(path.read_text())
        if lines:
            offenders[str(path.relative_to(BACKEND_DIR.parent))] = lines
    assert offenders == {}


@pytest.mark.parametrize(
    "source",
    [
        "async def f(c):\n    await asyncio.to_thread(lambda: c.table('a').select('*').execute())\n",
        "async def f(q):\n    await asyncio.to_thread(q.execute)\n",
        "async def f(c):\n    await asyncio.to_thread(c.storage.from_('b').upload, 'k', b'x')\n",
        "def landed():\n    return c.table('a').execute()\nasync def f():\n    await other(fn, landed=landed)\n",
    ],
    ids=["lambda", "uncalled-execute", "uncalled-storage", "closure-not-passed"],
)
def test_the_structural_check_flags_each_bypass_form(source: str) -> None:
    assert _unwrapped_supabase_references(source) != []


def test_the_structural_check_accepts_wrapped_forms() -> None:
    source = (
        "async def f(c, q):\n"
        "    await supabase_call(lambda: c.table('a').select('*').execute(), what='x')\n"
        "    await supabase_call(q.execute, what='y')\n"
        "    def landed():\n"
        "        return bool(c.storage.from_('b').exists('k'))\n"
        "    await supabase_call(lambda: 1, what='z', landed=landed)\n"
    )
    assert _unwrapped_supabase_references(source) == []


# ---------------------------------------------------------------------------
# the shared client
# ---------------------------------------------------------------------------


def test_database_and_storage_share_one_http1_client_with_the_designed_timeouts() -> None:
    client = get_supabase_client()
    session = client.postgrest.session
    assert session is client.storage.session
    # httpx exposes no public HTTP/2 flag; the pool's private attribute is pinned
    # here (httpx 0.28.1 / httpcore 1.0.9) so http2=True cannot slip back in.
    pool = session._transport._pool
    assert pool._http2 is False
    assert pool._http1 is True
    assert session.timeout == httpx.Timeout(120, connect=10, pool=10)
    assert (pool._max_connections, pool._max_keepalive_connections, pool._keepalive_expiry) == (20, 10, 5)
    assert session.follow_redirects is True


def _mock_client(seen: list[httpx.Request]) -> Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "HEAD":
            return httpx.Response(200)
        if request.url.path.startswith("/storage/") and request.method == "POST":
            return httpx.Response(200, json={"Key": "cleaned-datasets/a1.parquet"})
        if request.url.path.startswith("/storage/"):
            return httpx.Response(200, content=b"PAR1")
        return httpx.Response(200, json=[{"id": "a1"}])

    return create_client(
        "https://project.supabase.test",
        "sb_secret_test",
        options=SyncClientOptions(httpx_client=httpx.Client(transport=httpx.MockTransport(handler))),
    )


def test_the_injected_client_sends_auth_on_every_request_type(tmp_path: pathlib.Path) -> None:
    """table() select and update, and every Storage method the backend uses, through file_handler itself."""
    seen: list[httpx.Request] = []
    client = _mock_client(seen)
    parquet = tmp_path / "a1.parquet"
    parquet.write_bytes(b"PAR1")
    client.table("analyses").select("status").eq("id", "a1").execute()
    client.table("analyses").update({"status": "x"}).eq("id", "a1").execute()
    with (
        patch("backend.utils.file_handler.get_supabase_client", return_value=client),
        patch.object(file_handler, "TEMP_DIR", tmp_path),
    ):
        asyncio.run(file_handler.upload_to_storage("a1", str(parquet)))
        asyncio.run(file_handler.download_from_storage("a1"))

    kinds = [(r.method, r.url.path.split("/")[1]) for r in seen]
    assert kinds == [
        ("GET", "rest"), ("PATCH", "rest"),
        ("POST", "storage"), ("HEAD", "storage"), ("GET", "storage"),
    ]
    for request in seen:
        assert request.headers.get("apikey") == "sb_secret_test"
        assert request.headers.get("authorization") == "Bearer sb_secret_test"
    upload = seen[2]
    assert upload.headers.get("x-upsert") == "true"
