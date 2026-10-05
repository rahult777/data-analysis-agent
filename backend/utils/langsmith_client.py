"""
Sets up LangSmith tracing for all agent runs. Exposes a configured Client,
a LangChainTracer for use as a callback in LangGraph graph.invoke() calls,
and a fail-fast connection validator that runs on import when tracing is on.

Tracing is on only when backend.config says so (config.TRACING_ENABLED). With
tracing off this module makes no network call and create_tracer returns None;
the agent-work routes refuse instead (backend/utils/agent_guard.py).
"""

import os

from langchain_core.tracers.langchain import LangChainTracer
from langsmith import Client

from backend import config
from backend.config import LANGSMITH_API_KEY, LANGSMITH_PROJECT

# Set env vars so LangChain's internal machinery picks them up automatically.
# LangChain reads LANGCHAIN_API_KEY, LANGCHAIN_ENDPOINT and LANGCHAIN_PROJECT at
# callback instantiation time. LANGCHAIN_TRACING_V2 is owned by backend.config.
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY or ""
os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT or ""


def get_langsmith_client() -> Client:
    return Client(api_key=LANGSMITH_API_KEY)


def create_tracer(run_name: str) -> LangChainTracer | None:
    """Return a LangChainTracer for use as a callback in LangGraph graph.invoke(),
    or None when tracing is off.

    Pass it as a callback only when it is not None, as run_pipeline does — never
    pass callbacks=[None]:
        run_config = {}
        if tracer is not None:
            run_config["callbacks"] = [tracer]
        await graph.ainvoke(inputs, config=run_config)
    """
    if not config.TRACING_ENABLED:
        return None
    return LangChainTracer(project_name=LANGSMITH_PROJECT, tags=[run_name])


def validate_langsmith_connection() -> None:
    """Verify LangSmith connectivity by making a real API call.

    Raises RuntimeError naming exactly what failed if the connection cannot
    be established.
    """
    try:
        client = get_langsmith_client()
        list(client.list_projects(limit=1))
    except Exception as exc:
        raise RuntimeError(
            f"LangSmith connection failed — {type(exc).__name__}: {exc}. "
            "Verify LANGSMITH_API_KEY is valid and LANGCHAIN_ENDPOINT "
            "(https://api.smith.langchain.com) is reachable."
        ) from exc


if config.TRACING_ENABLED:
    validate_langsmith_connection()
