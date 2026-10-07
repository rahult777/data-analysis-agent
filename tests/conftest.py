"""Suite-wide test settings and fixtures."""

import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import dotenv
import pytest


def _never_load_dotenv(*args: object, **kwargs: object) -> bool:
    """Stands in for dotenv.load_dotenv: the suite never reads the developer's .env."""
    return False


# Test settings. pytest imports this file before any test module, so these run before anything
# imports backend.config: no real .env, dummy credentials that reach no real service, tracing and
# agent work off, the default browser origins.
dotenv.load_dotenv = _never_load_dotenv
for _name in [name for name in os.environ if name.startswith(("LANGSMITH_", "LANGCHAIN_TRACING"))]:
    del os.environ[_name]
for _name in ("AGENT_WORK_ENABLED", "ALLOWED_ORIGINS"):
    os.environ.pop(_name, None)
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["ANTHROPIC_MODEL"] = "claude-sonnet-4-6"
os.environ["SUPABASE_URL"] = "http://127.0.0.1:9"
os.environ["SUPABASE_SECRET_KEY"] = "test-supabase-secret-key"
os.environ["LANGCHAIN_TRACING_V2"] = "false"


@pytest.fixture(autouse=True)
def retry_sleep() -> Iterator[AsyncMock]:
    """supabase_call's backoff never waits in real time; tests read its delays here."""
    with patch("backend.utils.supabase_retry._sleep", new=AsyncMock()) as sleep:
        yield sleep


@pytest.fixture
def agent_work_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent work is allowed (AGENT_WORK_ENABLED and tracing on), but nothing reaches LangSmith:
    LangChainTracer is replaced at its source, so create_tracer, wherever it was imported, returns a
    no-op handler."""
    from langchain_core.callbacks import BaseCallbackHandler

    def no_op_tracer(*args: object, **kwargs: object) -> BaseCallbackHandler:
        return BaseCallbackHandler()

    monkeypatch.setattr("backend.config.TRACING_ENABLED", True)
    monkeypatch.setattr("backend.config.AGENT_WORK_ENABLED", True)
    monkeypatch.setattr("backend.utils.langsmith_client.LangChainTracer", no_op_tracer)
