"""Backend configuration, read once at import.

LangSmith tracing (CLAUDE.md Rule 8) is decided here, once: it is on only when LANGCHAIN_TRACING_V2,
stripped and lower-cased, is "true". With tracing off the server boots for read-only use, and every
route that starts or continues agent work refuses with 503 (backend/utils/agent_guard.py).
"""

import logging
import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from dotenv import load_dotenv

# First, before .env is loaded or any directory is created: the backend reads and writes paths
# relative to the working directory (backend/uploads, backend/outputs/charts, backend/prompts).
if Path.cwd().resolve() != Path(__file__).resolve().parents[1]:
    raise RuntimeError(
        "Start the backend from the repository root (the directory that contains backend/); "
        f"it uses paths relative to the working directory, which is {Path.cwd()}."
    )

logger = logging.getLogger(__name__)

_REQUIRED_VARS: list[str] = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "SUPABASE_URL",
    "SUPABASE_SECRET_KEY",
]
_TRACING_REQUIRED_VARS: list[str] = ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT"]

# The other switches langsmith and langchain-core read. langsmith checks LANGSMITH_TRACING_V2 before
# LANGCHAIN_TRACING_V2 and caches the first answer; LANGCHAIN_TRACING and LANGCHAIN_HANDLER select the
# removed v1 tracer, which makes every graph run raise.
_STRAY_TRACING_VARS: tuple[str, ...] = (
    "LANGSMITH_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_HANDLER",
)


def tracing_enabled(env: Mapping[str, str]) -> bool:
    """True only when LANGCHAIN_TRACING_V2, stripped and lower-cased, is "true"."""
    return (env.get("LANGCHAIN_TRACING_V2") or "").strip().lower() == "true"


def normalize_tracing_env(environ: MutableMapping[str, str], enabled: bool) -> None:
    """Leave LANGCHAIN_TRACING_V2 as the only tracing switch, set to exactly "true" or "false".

    Must run before any LangChain or LangGraph code reads, and caches, the environment.
    """
    for name in _STRAY_TRACING_VARS:
        environ.pop(name, None)
    environ["LANGCHAIN_TRACING_V2"] = "true" if enabled else "false"


def validate_config(env: Mapping[str, str], enabled: bool) -> None:
    """Raise ValueError naming a missing variable; the LangSmith pair is required only with tracing on."""
    for var in _REQUIRED_VARS + (_TRACING_REQUIRED_VARS if enabled else []):
        if not env.get(var):
            reason = " It is required because LANGCHAIN_TRACING_V2 is 'true'." if var in _TRACING_REQUIRED_VARS else ""
            raise ValueError(
                f"Missing required environment variable: {var}. "
                f"Check your .env file and ensure {var} is set.{reason}"
            )


load_dotenv()

TRACING_ENABLED: bool = tracing_enabled(os.environ)
normalize_tracing_env(os.environ, TRACING_ENABLED)
validate_config(os.environ, TRACING_ENABLED)

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str | None = os.getenv("ANTHROPIC_MODEL")
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY: str | None = os.getenv("SUPABASE_SECRET_KEY")
LANGSMITH_API_KEY: str | None = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT: str | None = os.getenv("LANGSMITH_PROJECT")

if TRACING_ENABLED:
    logger.info("LangSmith tracing is on.")
else:
    logger.warning(
        "LangSmith tracing is off (LANGCHAIN_TRACING_V2 is not 'true'): the server runs read-only and "
        "refuses every request that would start or continue agent work (503)."
    )
