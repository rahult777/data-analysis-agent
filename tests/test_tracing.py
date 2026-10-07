"""Tests for CLAUDE.md Rule 8 as enforced in code: LangSmith tracing is optional at boot, agent work is
opt-in (AGENT_WORK_ENABLED), and unless both are on, every request that would start or continue agent
work is refused with 503: the server is read-only also when AGENT_WORK_ENABLED is off.

The config functions are called with plain dicts or a monkeypatched os.environ; backend.config is
never reloaded (the boot tests import it in a fresh process). Unlike test_api.py, these tests run with
tracing and agent work off (tests/conftest.py).
"""

import asyncio
import io
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import langsmith.utils
import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler

from backend import config
from backend.agents.explainer import answer_question
from backend.agents.orchestrator import run_pipeline
from backend.config import normalize_tracing_env, tracing_enabled, validate_config
from backend.main import app
from backend.utils import agent_guard, langsmith_client
from tests.fake_supabase import FakeSupabase

client = TestClient(app)

READ_ONLY = {"detail": "SYSTEM_ERROR: Analysis is not available on this server (read-only mode)."}
SUPABASE_PAIR = {"SUPABASE_URL": "http://127.0.0.1:9", "SUPABASE_SECRET_KEY": "secret"}
ANTHROPIC_PAIR = {"ANTHROPIC_API_KEY": "key", "ANTHROPIC_MODEL": "model"}
CORE_ENV = {**ANTHROPIC_PAIR, **SUPABASE_PAIR}
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
@pytest.mark.parametrize("missing", sorted(SUPABASE_PAIR))
def test_validate_always_requires_the_core_variables(missing: str, enabled: bool) -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR, missing: ""}
    with pytest.raises(ValueError, match=missing):
        validate_config(env, enabled)


# ---------------------------------------------------------------------------
# The agent-work switch (AGENT_WORK_ENABLED) and its boot rules
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
        ("on", False),
        ("", False),
    ],
)
def test_agent_work_is_on_only_for_true_ignoring_case_and_surrounding_whitespace(value: str, expected: bool) -> None:
    assert config.agent_work_enabled({"AGENT_WORK_ENABLED": value}) is expected


def test_agent_work_is_off_when_the_switch_is_absent_even_with_tracing_on() -> None:
    assert config.agent_work_enabled({"LANGCHAIN_TRACING_V2": "true"}) is False


@pytest.mark.parametrize("tracing_on", [False, True])
def test_validate_does_not_require_the_anthropic_pair_when_agent_work_is_off(tracing_on: bool) -> None:
    validate_config({**SUPABASE_PAIR, **LANGSMITH_PAIR}, tracing_on)
    validate_config({**SUPABASE_PAIR, **LANGSMITH_PAIR}, tracing_on, False)


@pytest.mark.parametrize("missing", sorted(ANTHROPIC_PAIR))
def test_validate_requires_the_anthropic_pair_when_agent_work_is_on(missing: str) -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR, missing: ""}
    with pytest.raises(ValueError, match=f"{missing}.*AGENT_WORK_ENABLED is 'true'"):
        validate_config(env, True, True)


def test_validate_refuses_agent_work_without_tracing() -> None:
    with pytest.raises(ValueError) as refused:
        validate_config({**CORE_ENV, **LANGSMITH_PAIR}, False, True)
    assert str(refused.value) == (
        "AGENT_WORK_ENABLED is 'true' but LANGCHAIN_TRACING_V2 is not: agent work must be traced "
        "(CLAUDE.md Rule 8). Set LANGCHAIN_TRACING_V2=true or leave AGENT_WORK_ENABLED unset."
    )


@pytest.mark.parametrize("missing", sorted(LANGSMITH_PAIR))
def test_validate_with_agent_work_on_still_requires_the_langsmith_pair(missing: str) -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR}
    del env[missing]
    with pytest.raises(ValueError, match=missing):
        validate_config(env, True, True)


def test_validate_passes_with_agent_work_on_and_every_variable() -> None:
    validate_config({**CORE_ENV, **LANGSMITH_PAIR}, True, True)


REPO = Path(__file__).resolve().parents[1]
# Imports backend.config as a server start does, without ever reading a developer's .env.
IMPORT_CONFIG = "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; import backend.config"
# The same import with a stand-in .env that sets AGENT_WORK_ENABLED=true; like load_dotenv, it never overrides
# a variable already in the process environment.
IMPORT_CONFIG_WITH_AGENT_WORK_IN_DOTENV = (
    "import os, dotenv; "
    "dotenv.load_dotenv = lambda *a, **k: os.environ.setdefault('AGENT_WORK_ENABLED', 'true') is not None; "
    "import backend.config"
)
AGENT_WORK_IN_DOTENV_ERROR = (
    "ValueError: AGENT_WORK_ENABLED is set in .env. Remove it from .env and set it per session: "
    "AGENT_WORK_ENABLED=true python -m uvicorn ..."
)


def boot_config(env: dict[str, str], code: str = IMPORT_CONFIG) -> subprocess.CompletedProcess:
    """Run code (by default, import backend.config) in a fresh process with exactly these variables, nothing
    inherited."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env={"PATH": os.environ.get("PATH", ""), **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("missing", sorted(ANTHROPIC_PAIR))
def test_boot_fails_when_agent_work_is_on_and_an_anthropic_variable_is_missing(missing: str) -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR, "LANGCHAIN_TRACING_V2": "true", "AGENT_WORK_ENABLED": "true"}
    del env[missing]
    result = boot_config(env)
    assert result.returncode != 0
    assert (
        f"ValueError: Missing required environment variable: {missing}. Check your .env file and ensure "
        f"{missing} is set. It is required because AGENT_WORK_ENABLED is 'true'."
    ) in result.stderr


def test_boot_succeeds_without_the_anthropic_pair_when_agent_work_is_off() -> None:
    result = boot_config(dict(SUPABASE_PAIR))
    assert result.returncode == 0, result.stderr
    assert "Agent work is off (AGENT_WORK_ENABLED is not 'true'; LANGCHAIN_TRACING_V2 is not 'true')" in result.stderr


@pytest.mark.parametrize(
    "env",
    [SUPABASE_PAIR, {**CORE_ENV, **LANGSMITH_PAIR, "LANGCHAIN_TRACING_V2": "true"}],
    ids=["read-only", "tracing-and-anthropic-pair"],
)
def test_boot_fails_when_agent_work_enabled_comes_from_dotenv(env: dict[str, str]) -> None:
    result = boot_config(dict(env), IMPORT_CONFIG_WITH_AGENT_WORK_IN_DOTENV)
    assert result.returncode != 0
    assert AGENT_WORK_IN_DOTENV_ERROR in result.stderr


def test_boot_keeps_agent_work_enabled_from_the_process_environment() -> None:
    env = {**CORE_ENV, **LANGSMITH_PAIR, "LANGCHAIN_TRACING_V2": "true", "AGENT_WORK_ENABLED": "true"}
    result = boot_config(env, IMPORT_CONFIG_WITH_AGENT_WORK_IN_DOTENV + "; print(backend.config.AGENT_WORK_ENABLED)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_boot_record_is_one_info_line_when_agent_work_is_on() -> None:
    assert config.boot_log_record(True, True) == (
        logging.INFO,
        "Agent work is on (AGENT_WORK_ENABLED and LangSmith tracing).",
    )


@pytest.mark.parametrize(
    "tracing_on, agent_work_on, named, unnamed",
    [
        (True, False, ["AGENT_WORK_ENABLED"], ["LANGCHAIN_TRACING_V2"]),
        (False, False, ["AGENT_WORK_ENABLED", "LANGCHAIN_TRACING_V2"], []),
        (False, True, ["LANGCHAIN_TRACING_V2"], ["AGENT_WORK_ENABLED"]),
    ],
    ids=["agent-work-off", "both-off", "tracing-off"],
)
def test_boot_record_is_one_warning_naming_each_switch_that_is_off(
    tracing_on: bool, agent_work_on: bool, named: list[str], unnamed: list[str]
) -> None:
    level, message = config.boot_log_record(tracing_on, agent_work_on)
    assert level == logging.WARNING
    assert "refuses every request that would start or continue agent work (503)" in message
    for name in named:
        assert f"{name} is not 'true'" in message
    for name in unnamed:
        assert name not in message


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


@pytest.mark.parametrize("path", AGENT_ROUTES, ids=["upload", "question", "resume"])
def test_agent_work_route_refuses_with_503_when_tracing_is_on_but_agent_work_is_off(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Tracing alone no longer allows agent work: AGENT_WORK_ENABLED must be on too."""
    monkeypatch.setattr(config, "TRACING_ENABLED", True)
    monkeypatch.setattr(config, "AGENT_WORK_ENABLED", False)
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


@pytest.mark.parametrize("route", ["question", "resume"])
def test_malformed_id_on_an_agent_route_is_503_while_agent_work_is_off(route: str) -> None:
    body = {"question": "q?"} if route == "question" else {"response": {"option_id": "confirm"}}
    with patch("backend.main.get_supabase_client") as get_client:
        response = client.post(f"/api/analysis/not-a-uuid/{route}", json=body, headers={"session-id": "s"})
    assert (response.status_code, response.json()) == (503, READ_ONLY)
    get_client.assert_not_called()


def test_upload_reaches_validation_when_agent_work_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard lets agent work through when both switches are on: the request gets to file validation."""
    monkeypatch.setattr(config, "TRACING_ENABLED", True)
    monkeypatch.setattr(config, "AGENT_WORK_ENABLED", True)
    with patch("backend.main.validate_file", side_effect=ValueError("USER_ERROR: bad file")) as validate:
        response = post_agent_route("/api/upload")
    assert response.status_code == 400
    validate.assert_called_once()


# ---------------------------------------------------------------------------
# agent_work_allowed() and the agent_work_on test fixture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tracing_on, agent_work_on, allowed",
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_agent_work_is_allowed_only_when_both_switches_are_on(
    monkeypatch: pytest.MonkeyPatch, tracing_on: bool, agent_work_on: bool, allowed: bool
) -> None:
    monkeypatch.setattr(config, "TRACING_ENABLED", tracing_on)
    monkeypatch.setattr(config, "AGENT_WORK_ENABLED", agent_work_on)
    assert agent_guard.agent_work_allowed() is allowed


def test_agent_work_on_gives_every_create_tracer_a_no_op_handler(agent_work_on: None) -> None:
    """The fixture patches LangChainTracer at its source, so no module's create_tracer builds a real tracer."""
    from backend.agents import analyzer, cleaner, explainer, orchestrator, profiler

    for module in (orchestrator, profiler, cleaner, analyzer, explainer):
        assert type(module.create_tracer(module.__name__)) is BaseCallbackHandler


# ---------------------------------------------------------------------------
# The refusal inside run_pipeline and answer_question (behind the gate and the route guard)
# ---------------------------------------------------------------------------


def test_run_pipeline_refuses_first_when_agent_work_is_not_allowed() -> None:
    fake = FakeSupabase(rows={"analyses": [{"id": "a-1", "status": "profiling", "error_message": None}]})
    state = {"analysis_id": "a-1", "stored_filename": "f.csv"}
    with (
        patch("backend.agents.orchestrator.get_supabase_client", return_value=fake),
        patch("backend.agents.orchestrator.create_tracer") as tracer,
        patch("backend.agents.orchestrator.StateGraph") as graph,
    ):
        result = asyncio.run(run_pipeline(state))
    assert result is state
    (update,) = fake.executes("update", "analyses")
    assert update.filters == [("eq", "id", "a-1")]
    assert sorted(update.payload) == ["error_message", "status", "updated_at"]
    assert (update.payload["status"], update.payload["error_message"]) == ("error", READ_ONLY["detail"])
    tracer.assert_not_called()
    graph.assert_not_called()


def test_answer_question_refuses_first_when_agent_work_is_not_allowed() -> None:
    refusal = "Questions are not available on this server right now."
    fake = FakeSupabase(rows={"questions": [{"id": "q-1", "analysis_id": "a-1", "status": "pending"}]})
    with (
        patch("backend.agents.explainer.get_supabase_client", return_value=fake),
        patch("backend.agents.explainer.create_tracer") as tracer,
        patch("backend.agents.explainer.download_from_storage", new=AsyncMock()) as download,
        patch("backend.agents.explainer.client") as model,
        patch("backend.agents.explainer.run_question") as run,
    ):
        result = asyncio.run(answer_question("a-1", "q-1", "What is the total?"))
    assert result == {"answer": refusal, "pandas_code": ""}
    (update,) = fake.executes("update", "questions")
    assert update.filters == [("eq", "id", "q-1")]
    assert update.payload == {"status": "error", "answer": refusal, "pandas_code": ""}
    tracer.assert_not_called()
    download.assert_not_called()
    run.assert_not_called()
    assert model.mock_calls == []
