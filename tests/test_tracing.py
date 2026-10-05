"""Tests for CLAUDE.md Rule 8 as enforced in code: LangSmith tracing is optional at boot, and when it
is off every route that starts or continues agent work refuses with 503.

The config functions are called with plain dicts or a monkeypatched os.environ; backend.config is
never reloaded. Unlike test_api.py, these tests run with tracing off (tests/conftest.py).
"""

import io
import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import httpx
import langsmith.utils
import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.config import normalize_tracing_env, tracing_enabled, validate_config
from backend.main import app
from backend.utils import langsmith_client

client = TestClient(app)

READ_ONLY = {"detail": "SYSTEM_ERROR: Analysis is not available on this server (read-only mode)."}
CORE_ENV = {
    "ANTHROPIC_API_KEY": "key",
    "ANTHROPIC_MODEL": "model",
    "SUPABASE_URL": "http://127.0.0.1:9",
    "SUPABASE_SECRET_KEY": "secret",
}
LANGSMITH_PAIR = {"LANGSMITH_API_KEY": "ls-key", "LANGSMITH_PROJECT": "project"}
AID = "11111111-2222-4333-8444-555555555555"


# ---------------------------------------------------------------------------
# The tracing decision, normalization and validation (pure functions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("true", True),
        ("True", True),
        (" true ", True),
        ("TRUE\n", True),
        ("false", False),
        ("1", False),
        ("yes", False),
        ("", False),
        ("truee", False),
    ],
)
def test_tracing_is_on_only_for_true_ignoring_case_and_surrounding_whitespace(value: str, expected: bool) -> None:
    assert tracing_enabled({"LANGCHAIN_TRACING_V2": value}) is expected


def test_tracing_is_off_when_the_switch_is_absent() -> None:
    assert tracing_enabled({}) is False


def test_langsmith_switches_do_not_decide_tracing() -> None:
    """Only LANGCHAIN_TRACING_V2 decides; langsmith's own switches cannot turn tracing on."""
    env = {"LANGSMITH_TRACING_V2": "true", "LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING": "true"}
    assert tracing_enabled(env) is False


@pytest.mark.parametrize("enabled, written", [(True, "true"), (False, "false")])
def test_normalize_leaves_one_switch_with_an_exact_value(enabled: bool, written: str) -> None:
    env = {
        "LANGCHAIN_TRACING_V2": " True ",
        "LANGSMITH_TRACING_V2": "true",
        "LANGSMITH_TRACING": "true",
        "LANGCHAIN_TRACING": "true",
        "LANGCHAIN_HANDLER": "langchain",
        "LANGSMITH_API_KEY": "kept",
    }
    normalize_tracing_env(env, enabled)
    assert env == {"LANGCHAIN_TRACING_V2": written, "LANGSMITH_API_KEY": "kept"}


def test_validate_passes_with_tracing_off_and_no_langsmith_or_openai_variables() -> None:
    validate_config(dict(CORE_ENV), False)


@pytest.mark.parametrize("missing", ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT"])
def test_validate_requires_the_langsmith_pair_when_tracing_is_on(missing: str) -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR}
    del env[missing]
    with pytest.raises(ValueError, match=missing):
        validate_config(env, True)


def test_validate_passes_with_tracing_on_and_the_langsmith_pair() -> None:
    validate_config({**CORE_ENV, **LANGSMITH_PAIR}, True)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("missing", sorted(CORE_ENV))
def test_validate_always_requires_the_core_variables(missing: str, enabled: bool) -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR, missing: ""}
    with pytest.raises(ValueError, match=missing):
        validate_config(env, enabled)


@pytest.fixture
def fresh_langsmith_env_cache() -> Iterator[None]:
    """langsmith caches environment lookups; start and end every test with an empty cache."""
    langsmith.utils.get_env_var.cache_clear()
    yield
    langsmith.utils.get_env_var.cache_clear()


def test_stray_langsmith_switches_cannot_turn_tracing_on(
    monkeypatch: pytest.MonkeyPatch, fresh_langsmith_env_cache: None
) -> None:
    """langsmith reads LANGSMITH_TRACING_V2 before LANGCHAIN_TRACING_V2; normalization removes it."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setattr(config, "TRACING_ENABLED", False)
    assert langsmith.utils.tracing_is_enabled() is True  # the hazard, before normalization

    normalize_tracing_env(os.environ, False)
    langsmith.utils.get_env_var.cache_clear()

    assert langsmith.utils.tracing_is_enabled() is False
    assert langsmith_client.create_tracer("x") is None


# ---------------------------------------------------------------------------
# create_tracer
# ---------------------------------------------------------------------------


class RecordingTracer:
    """Stands in for LangChainTracer so no LangSmith client is built."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def test_create_tracer_returns_none_when_tracing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TRACING_ENABLED", False)
    monkeypatch.setattr(langsmith_client, "LangChainTracer", RecordingTracer)
    assert langsmith_client.create_tracer("profiler") is None


def test_create_tracer_returns_a_tagged_tracer_when_tracing_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TRACING_ENABLED", True)
    monkeypatch.setattr(langsmith_client, "LangChainTracer", RecordingTracer)
    tracer = langsmith_client.create_tracer("profiler")
    assert isinstance(tracer, RecordingTracer)
    assert tracer.kwargs["tags"] == ["profiler"]


# ---------------------------------------------------------------------------
# The agent-work routes
# ---------------------------------------------------------------------------


def post_agent_route(path: str) -> httpx.Response:
    if path == "/api/upload":
        return client.post(path, files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")})
    body = {"question": "q?"} if path.endswith("/question") else {"response": {"option_id": "confirm"}}
    return client.post(path, json=body, headers={"session-id": "s"})


AGENT_ROUTES = ["/api/upload", f"/api/analysis/{AID}/question", f"/api/analysis/{AID}/resume"]


@pytest.mark.parametrize("path", AGENT_ROUTES, ids=["upload", "question", "resume"])
def test_agent_work_route_refuses_with_503_before_any_work_when_tracing_is_off(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setattr(config, "TRACING_ENABLED", False)
    with (
        patch("backend.main.get_supabase_client") as get_client,
        patch("backend.main.validate_file") as validate,
        patch("backend.main.save_temp_file", new=AsyncMock()) as save,
        patch("backend.main.run_pipeline_task", new=AsyncMock()) as pipeline,
        patch("backend.main.run_question_task", new=AsyncMock()) as question,
    ):
        response = post_agent_route(path)
    assert response.status_code == 503
    assert response.json() == READ_ONLY
    for work in (get_client, validate, save, pipeline, question):
        work.assert_not_called()


def test_upload_reaches_validation_when_tracing_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard lets agent work through when tracing is on: the request gets to file validation."""
    monkeypatch.setattr(config, "TRACING_ENABLED", True)
    with patch("backend.main.validate_file", side_effect=ValueError("USER_ERROR: bad file")) as validate:
        response = post_agent_route("/api/upload")
    assert response.status_code == 400
    validate.assert_called_once()
