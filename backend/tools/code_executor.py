"""Safely executes LLM-generated pandas code for custom user questions.

This module provides an AST-validated execution sandbox that runs analyst-generated
pandas operations on a cleaned DataFrame. It has zero dependencies on other project
modules — only stdlib and third-party packages — so it can be imported without
triggering agent initialization or requiring environment variables.
"""

import ast
import concurrent.futures
import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EXECUTION_TIMEOUT_SECONDS: int = 30

SAFE_BUILTINS: dict[str, Any] = {
    "len": len,
    "range": range,
    "isinstance": isinstance,
    "enumerate": enumerate,
    "zip": zip,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sorted": sorted,
    "reversed": reversed,
    "print": print,
    "repr": repr,
    "hasattr": hasattr,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "Exception": Exception,
}


def validate_code(code: str) -> Optional[str]:
    """Return None if code is safe to execute, or a plain-English error message.

    Validation order: emptiness -> result variable present -> syntax -> AST safety.
    """
    if not code or not code.strip():
        return "The code is empty. Please provide a pandas expression."

    if "result" not in code:
        return (
            "The code must assign its output to a variable named 'result'. "
            "Example: result = df['column'].mean()"
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"The code contains a syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            return "The code must not import modules."
        if isinstance(node, ast.ImportFrom):
            return "The code must not use from-imports."
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return (
                f"The code must not access dunder attributes "
                f"(blocked: '{node.attr}')."
            )

    return None


def sanitize_result(value: Any) -> Any:
    """Recursively convert pandas/numpy types to JSON-serializable Python types.

    Check order matters -- pd.NA/pd.NaT identity checks must come before any
    isinstance calls because math.isnan(pd.NA) raises TypeError.
    """
    # Identity checks first -- pd.NA and pd.NaT are singletons
    if value is pd.NA or value is pd.NaT:
        return None

    # pandas scalar types
    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    # numpy string type
    if isinstance(value, np.str_):
        return str(value)

    # numpy temporal types
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return str(value)

    # numpy floating -- convert first, then check NaN/Inf
    if isinstance(value, np.floating):
        f = float(value.item())
        return None if (math.isnan(f) or math.isinf(f)) else f

    # numpy integer
    if isinstance(value, np.integer):
        return int(value.item())

    # numpy boolean
    if isinstance(value, np.bool_):
        return bool(value)

    # numpy array -- tolist() converts to Python scalars, then recurse
    if isinstance(value, np.ndarray):
        return [sanitize_result(v) for v in value.tolist()]

    # Python container types -- recurse into values
    if isinstance(value, dict):
        return {k: sanitize_result(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_result(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_result(v) for v in value]

    # Python float -- check NaN/Inf
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value

    return value


def execute_pandas_code(
    df: pd.DataFrame, code: str
) -> tuple[Any, Optional[str]]:
    """Execute code in a restricted sandbox with a timeout.

    Synchronous blocking function. Callers must use:
        await asyncio.to_thread(run_question, df, code)
    """
    try:
        exec_globals: dict[str, Any] = {
            "df": df,
            "pd": pd,
            "np": np,
            "__builtins__": SAFE_BUILTINS,
        }
        exec_locals: dict[str, Any] = {}

        def _run() -> Any:
            exec(code, exec_globals, exec_locals)  # noqa: S102
            return exec_locals.get("result")

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            try:
                result = future.result(timeout=EXECUTION_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                return (
                    None,
                    f"The computation timed out after "
                    f"{EXECUTION_TIMEOUT_SECONDS} seconds.",
                )

        if result is None:
            return (
                None,
                "The code ran but did not assign a result to the "
                "'result' variable.",
            )

        if isinstance(result, pd.DataFrame):
            result = result.to_dict(orient="records")
        elif isinstance(result, pd.Series):
            result = result.tolist()

        result = sanitize_result(result)
        return (result, None)

    except Exception as e:
        logger.exception("Code execution failed")
        return (None, f"The computation failed: {type(e).__name__}: {str(e)}")


def run_question(
    df: pd.DataFrame, code: str
) -> tuple[Any, Optional[str]]:
    """Validate and execute a pandas code string against a cleaned DataFrame.

    Synchronous blocking function. Callers must use:
        await asyncio.to_thread(run_question, df, code)

    Returns (result, None) on success or (None, error_message) on failure.
    """
    validation_error = validate_code(code)
    if validation_error is not None:
        return (None, validation_error)
    return execute_pandas_code(df, code)
