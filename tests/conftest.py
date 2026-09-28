"""Suite-wide fixtures."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def retry_sleep() -> Iterator[AsyncMock]:
    """supabase_call's backoff never waits in real time; tests read its delays here."""
    with patch("backend.utils.supabase_retry._sleep", new=AsyncMock()) as sleep:
        yield sleep
