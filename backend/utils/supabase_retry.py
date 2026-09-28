"""Retry for transient Supabase transport failures (Build L.2).

One dropped connection must not fail a status read, lose a user's pause answer,
or end a paused pipeline (errors.md 2026-09-28). Every Supabase call in the
backend goes through supabase_call; a structural test in
tests/test_supabase_retry.py fails on any call site that bypasses it.
"""

import asyncio
import logging
from typing import Callable, Optional, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Transport failures only: the request never reached the server (connect, pool)
# or its response was lost (disconnect, read or write error). Never retried: HTTP
# error statuses (postgrest APIError, StorageApiError, HTTPStatusError), which are
# answers rather than faults; validation errors; and read or write timeouts, which
# have already waited the full 120 s.
TRANSIENT: tuple[type[Exception], ...] = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)

# Module-level so tests can replace it; no test waits in real time.
_sleep = asyncio.sleep


async def supabase_call(
    fn: Callable[[], T],
    *,
    what: str,
    attempts: int = 3,
    delays: tuple[float, ...] = (0.5, 1.5),
    landed: Optional[Callable[[], bool]] = None,
) -> Optional[T]:
    """Run a sync Supabase call in a worker thread, retrying transient failures.

    A write whose response was lost may already have committed. When `landed`
    is given, it is asked after each failure's delay whether the write is
    already in the database: True returns None without re-sending, False
    re-sends. A transient failure inside landed() uses up that attempt without
    re-sending fn, and the next attempt asks again. Any other exception, from fn
    or from landed(), is raised at once. When attempts run out, fn's original
    transient error is raised.
    """
    original: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            await _sleep(delays[min(attempt - 2, len(delays) - 1)])
            if landed is not None:
                try:
                    already = await asyncio.to_thread(landed)
                except TRANSIENT as exc:
                    logger.warning(
                        "supabase_call[%s]: landed check failed transiently (%s: %s) "
                        "on attempt %d of %d; not re-sent",
                        what, type(exc).__name__, exc, attempt, attempts,
                    )
                    continue
                if already:
                    logger.warning(
                        "supabase_call[%s]: landed despite the lost response "
                        "(%s); not re-sent",
                        what, type(original).__name__,
                    )
                    return None
        try:
            return await asyncio.to_thread(fn)
        except TRANSIENT as exc:
            if original is None:
                original = exc
            logger.warning(
                "supabase_call[%s]: transient %s (%s) on attempt %d of %d; %s",
                what, type(exc).__name__, exc, attempt, attempts,
                "retrying" if attempt < attempts else "no attempts left",
            )
    if original is None:  # unreachable: attempt 1 always sends fn
        raise RuntimeError(f"supabase_call[{what}]: no attempt was made")
    logger.warning("supabase_call[%s]: giving up after %d attempts", what, attempts)
    raise original
