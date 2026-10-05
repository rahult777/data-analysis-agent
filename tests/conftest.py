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
# imports backend.config: no real .env, dummy credentials that reach no real service, tracing off.
dotenv.load_dotenv = _never_load_dotenv
for _name in [name for name in os.environ if name.startswith(("LANGSMITH_", "LANGCHAIN_TRACING"))]:
    del os.environ[_name]
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
def tracing_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent-work routes open as with tracing on, but nothing reaches LangSmith:
    TRACING_ENABLED is True and every create_tracer import site returns a no-op handler."""
    from langchain_core.callbacks import BaseCallbackHandler

    def no_op_tracer(run_name: str) -> BaseCallbackHandler:
        return BaseCallbackHandler()

    monkeypatch.setattr("backend.config.TRACING_ENABLED", True)
    for module in ("orchestrator", "profiler", "cleaner", "analyzer", "explainer"):
        monkeypatch.setattr(f"backend.agents.{module}.create_tracer", no_op_tracer)
