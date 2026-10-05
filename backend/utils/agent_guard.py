"""Refuses agent work while LangSmith tracing is off (CLAUDE.md Rule 8, enforced in code).

Attached as a decorator-level dependency to every route that starts or continues agent work, so it
runs before the route's own dependencies, including get_session's database read. FastAPI still reads
the request body before any dependency runs.
"""

from fastapi import HTTPException

from backend import config


async def require_agent_work_enabled() -> None:
    """Raise 503 unless tracing is on; reads config.TRACING_ENABLED at call time."""
    if not config.TRACING_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="SYSTEM_ERROR: Analysis is not available on this server (read-only mode).",
        )
