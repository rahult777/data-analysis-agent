"""Single shared Supabase client for the entire backend.

This module initializes one Supabase client instance at import time and
exposes it via get_supabase_client(). All backend code should import from
here rather than constructing its own client.

The database, Storage and auth clients share one injected HTTP/1.1 client
(Build L.2). The libraries' own default is a separate HTTP/2 client each, and
over HTTP/2 every concurrent database call rides one connection, so a single
dropped connection failed every in-flight request at once. Over HTTP/1.1 each
concurrent request has its own pooled connection; the retry helper
(supabase_retry.py) covers the one request a drop still fails. The injected
client's timeouts replace the libraries' own (database 120 s, Storage 20 s).
"""

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from backend.config import SUPABASE_SECRET_KEY, SUPABASE_URL


def build_http_client() -> httpx.Client:
    """The one HTTP client every Supabase request goes through."""
    return httpx.Client(
        http2=False,
        follow_redirects=True,
        timeout=httpx.Timeout(120, connect=10, pool=10),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=5,
        ),
    )


try:
    if not SUPABASE_URL:
        raise ValueError(
            "SUPABASE_URL is missing or empty. "
            "Check the SUPABASE_URL value in your .env file."
        )
    if not SUPABASE_SECRET_KEY:
        raise ValueError(
            "SUPABASE_SECRET_KEY is missing or empty. "
            "Check the SUPABASE_SECRET_KEY value in your .env file."
        )
    supabase_client: Client = create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY,
        options=SyncClientOptions(httpx_client=build_http_client()),
    )
except ValueError:
    raise
except Exception as exc:
    raise RuntimeError(
        f"Supabase client initialization failed: {exc}. "
        "Check the SUPABASE_URL and SUPABASE_SECRET_KEY values in your .env file."
    ) from exc


def get_supabase_client() -> Client:
    """Return the shared Supabase client instance."""
    return supabase_client
