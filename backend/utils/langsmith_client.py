"""
Sets up LangSmith tracing for all agent runs. Exposes a configured Client,
a LangChainTracer for use as a callback in LangGraph graph.invoke() calls,
and a fail-fast connection validator that runs on import.
"""

import os

from langchain_core.tracers.langchain import LangChainTracer
from langsmith import Client

from backend.config import LANGCHAIN_TRACING_V2, LANGSMITH_API_KEY, LANGSMITH_PROJECT

# Set env vars so LangChain's internal machinery picks them up automatically.
# LangChain reads LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY, LANGCHAIN_ENDPOINT,
# and LANGCHAIN_PROJECT at callback instantiation time.
os.environ["LANGCHAIN_TRACING_V2"] = LANGCHAIN_TRACING_V2 or "false"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY or ""
os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT or ""


def get_langsmith_client() -> Client:
    return Client(api_key=LANGSMITH_API_KEY)


def create_tracer(run_name: str) -> LangChainTracer:
    """Return a LangChainTracer for use as a callback in LangGraph graph.invoke().

    Pass the returned tracer via:
        graph.invoke(inputs, config={"callbacks": [tracer], "run_name": run_name})
    """
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


validate_langsmith_connection()
