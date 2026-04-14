"""Single shared Supabase client for the entire backend.

This module initializes one Supabase client instance at import time and
exposes it via get_supabase_client(). All backend code should import from
here rather than constructing its own client.
"""

from supabase import Client, create_client

from backend.config import SUPABASE_SECRET_KEY, SUPABASE_URL

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
    supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
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
