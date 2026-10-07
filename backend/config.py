"""Backend configuration, read once at import.

Agent work (the paid model calls) is opt-in and always traced (CLAUDE.md Rule 8). Both switches are decided
here, once, each on only when its value, stripped and lower-cased, is "true": LANGCHAIN_TRACING_V2 turns
LangSmith tracing on, and AGENT_WORK_ENABLED, set per session (the boot fails if .env sets it), allows agent
work, which also needs tracing. Unless both are on, the server boots read-only and every request that would start or
continue agent work is refused with 503 (backend/utils/agent_guard.py). ALLOWED_ORIGINS lists the browser
origins the API accepts (CORS and the Origin check in backend/utils/request_gate.py).
"""

import logging
import os
import re
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

_REQUIRED_VARS: list[str] = ["SUPABASE_URL", "SUPABASE_SECRET_KEY"]
_TRACING_REQUIRED_VARS: list[str] = ["LANGSMITH_API_KEY", "LANGSMITH_PROJECT"]
_AGENT_WORK_REQUIRED_VARS: list[str] = ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"]

_DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
# An origin exactly as a browser sends it in the Origin header: http or https, a lower-case host name or a
# bracketed IPv6 address, an optional port, and nothing after it. A browser omits the scheme's default port
# and never writes a port with a leading zero.
_EXACT_ORIGIN = re.compile(
    r"(?P<scheme>https?)://(?:(?:[a-z0-9-]+\.)*[a-z0-9-]+|\[[0-9a-f:.]+\])(?::(?P<port>[0-9]{1,5}))?"
)
_DEFAULT_PORTS: dict[str, str] = {"http": "80", "https": "443"}

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


def agent_work_enabled(env: Mapping[str, str]) -> bool:
    """True only when AGENT_WORK_ENABLED, stripped and lower-cased, is "true"."""
    return (env.get("AGENT_WORK_ENABLED") or "").strip().lower() == "true"


def allowed_origins(env: Mapping[str, str]) -> list[str]:
    """The browser origins the API accepts, from ALLOWED_ORIGINS.

    Unset: the local frontend. Set: comma-separated, each item stripped and empty items ignored, so a
    set-but-empty value allows no browser origin. Raises ValueError naming ALLOWED_ORIGINS for a wildcard,
    "null", anything that is not an exact origin (scheme://host[:port]), or a port a browser never sends (the
    scheme's default port, or a leading zero).
    """
    value = env.get("ALLOWED_ORIGINS")
    if value is None:
        return list(_DEFAULT_ALLOWED_ORIGINS)
    origins = [item.strip() for item in value.split(",") if item.strip()]
    for origin in origins:
        if "*" in origin:
            problem = "contains '*'; wildcards are refused"
        elif origin == "null":
            problem = "is 'null', the origin of sandboxed and local-file pages, which is refused"
        elif not _is_exact_origin(origin):
            problem = (
                "is not an exact origin: use scheme://host[:port] (http or https, lower case, no path, "
                "query or trailing slash)"
            )
        elif port_problem := _port_problem(origin):
            problem = port_problem
        else:
            continue
        raise ValueError(
            f"ALLOWED_ORIGINS item {origin!r} {problem}. Fix ALLOWED_ORIGINS or leave it unset for the "
            f"default ({','.join(_DEFAULT_ALLOWED_ORIGINS)})."
        )
    return origins


def _is_exact_origin(origin: str) -> bool:
    match = _EXACT_ORIGIN.fullmatch(origin)
    return match is not None and (match["port"] is None or 1 <= int(match["port"]) <= 65535)


def _port_problem(origin: str) -> str | None:
    """For an exact origin whose port a browser never sends, the problem and its fix; otherwise None."""
    match = _EXACT_ORIGIN.fullmatch(origin)
    if match is None or match["port"] is None:
        return None
    if match["port"].startswith("0"):
        return "has a port with a leading zero, which a browser never sends: remove the leading zero"
    if match["port"] == _DEFAULT_PORTS[match["scheme"]]:
        return f"has the default port for {match['scheme']}, which a browser never sends: drop the default port"
    return None


def validate_config(env: Mapping[str, str], tracing_on: bool, agent_work_on: bool = False) -> None:
    """Raise ValueError naming the variable and the fix.

    SUPABASE_URL and SUPABASE_SECRET_KEY are always required; the LangSmith pair only with tracing on. Agent
    work needs tracing on and the Anthropic pair; with agent work off, neither Anthropic variable is required.
    """
    for var in _REQUIRED_VARS:
        _require(env, var, "")
    if agent_work_on and not tracing_on:
        raise ValueError(
            "AGENT_WORK_ENABLED is 'true' but LANGCHAIN_TRACING_V2 is not: agent work must be traced "
            "(CLAUDE.md Rule 8). Set LANGCHAIN_TRACING_V2=true or leave AGENT_WORK_ENABLED unset."
        )
    for var in _TRACING_REQUIRED_VARS if tracing_on else []:
        _require(env, var, " It is required because LANGCHAIN_TRACING_V2 is 'true'.")
    for var in _AGENT_WORK_REQUIRED_VARS if agent_work_on else []:
        _require(env, var, " It is required because AGENT_WORK_ENABLED is 'true'.")


def _require(env: Mapping[str, str], var: str, reason: str) -> None:
    if not env.get(var):
        raise ValueError(
            f"Missing required environment variable: {var}. "
            f"Check your .env file and ensure {var} is set.{reason}"
        )


def boot_log_record(tracing_on: bool, agent_work_on: bool) -> tuple[int, str]:
    """The one record logged at import: info when agent work is on, otherwise a warning naming each switch
    that is off."""
    if tracing_on and agent_work_on:
        return logging.INFO, "Agent work is on (AGENT_WORK_ENABLED and LangSmith tracing)."
    switches = (("AGENT_WORK_ENABLED", agent_work_on), ("LANGCHAIN_TRACING_V2", tracing_on))
    off = "; ".join(f"{name} is not 'true'" for name, on in switches if not on)
    return logging.WARNING, (
        f"Agent work is off ({off}): the server runs read-only and refuses every request that would start "
        "or continue agent work (503)."
    )


# AGENT_WORK_ENABLED comes only from the process environment, set per session. load_dotenv never overrides a
# variable already set there, so one that is present only after it ran came from .env.
_AGENT_WORK_SET_BEFORE_DOTENV: bool = "AGENT_WORK_ENABLED" in os.environ
load_dotenv()
if "AGENT_WORK_ENABLED" in os.environ and not _AGENT_WORK_SET_BEFORE_DOTENV:
    raise ValueError(
        "AGENT_WORK_ENABLED is set in .env. Remove it from .env and set it per session: "
        "AGENT_WORK_ENABLED=true python -m uvicorn ..."
    )

TRACING_ENABLED: bool = tracing_enabled(os.environ)
normalize_tracing_env(os.environ, TRACING_ENABLED)
AGENT_WORK_ENABLED: bool = agent_work_enabled(os.environ)
ALLOWED_ORIGINS: list[str] = allowed_origins(os.environ)
validate_config(os.environ, TRACING_ENABLED, AGENT_WORK_ENABLED)

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str | None = os.getenv("ANTHROPIC_MODEL")
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY: str | None = os.getenv("SUPABASE_SECRET_KEY")
LANGSMITH_API_KEY: str | None = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT: str | None = os.getenv("LANGSMITH_PROJECT")

logger.log(*boot_log_record(TRACING_ENABLED, AGENT_WORK_ENABLED))
