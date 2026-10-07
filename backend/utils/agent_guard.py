"""The one decision on agent work, and the refusals that enforce it (CLAUDE.md Rule 8, enforced in code).

Agent work runs only when agent_work_allowed(): AGENT_WORK_ENABLED and LangSmith tracing both on, read from
backend.config at call time. Everything else refuses with READ_ONLY_DETAIL, in layers: the ASGI gate
(backend/utils/request_gate.py) before a request body is read; require_agent_work_enabled, a decorator-level
dependency on every route that starts or continues agent work, so it runs before the route's own dependencies
(including get_session's database read); and the first statement of run_pipeline and answer_question.
"""

from fastapi import HTTPException

from backend import config

READ_ONLY_DETAIL = "SYSTEM_ERROR: Analysis is not available on this server (read-only mode)."
CROSS_ORIGIN_DETAIL = "Cross-origin request refused."


def agent_work_allowed() -> bool:
    """True only when AGENT_WORK_ENABLED and tracing are both on; reads backend.config at call time."""
    return config.AGENT_WORK_ENABLED and config.TRACING_ENABLED


async def require_agent_work_enabled() -> None:
    """Raise 503 unless agent work is allowed."""
    if not agent_work_allowed():
        raise HTTPException(status_code=503, detail=READ_ONLY_DETAIL)
