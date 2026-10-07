"""ASGI gate in front of the app: refuses a state-changing request before its body is read.

GET, HEAD and OPTIONS requests, and every non-HTTP scope (lifespan), pass through untouched. Any other
request, whatever its path, is checked in this order, and a refusal never reads the body:

1. An Origin header outside ALLOWED_ORIGINS gets 403. A browser attaches Origin to cross-origin POSTs,
   and an upload needs no CORS preflight, so without this check a web page the owner visits could make
   the owner's browser start a paid run on the local server.
2. Unless agent work is allowed (backend/utils/agent_guard.py), 503: the read-only refusal.
3. A body over its cap gets 413: MAX_FILE_SIZE plus 1 MiB for multipart framing on /api/upload, 64 KiB
   anywhere else. A declared Content-Length over the cap is refused before the app runs; otherwise the
   body is counted as the app reads it, and the read that passes the cap raises HTTPException(413), which
   FastAPI re-raises from body parsing and renders as JSON.

Registered inside CORSMiddleware (backend/main.py): preflights never reach the gate, and its 503 and 413
carry CORS headers for allowed origins.
"""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.utils import file_handler
from backend.utils.agent_guard import CROSS_ORIGIN_DETAIL, READ_ONLY_DETAIL, agent_work_allowed

REQUEST_TOO_LARGE_MESSAGE = "USER_ERROR: This request is too large."

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_UPLOAD_PATH = "/api/upload"
_UPLOAD_FRAMING_ALLOWANCE = 1024 * 1024
_REQUEST_SIZE_LIMIT = 64 * 1024


class RequestGate:
    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        origin = _header(scope, b"origin")
        if origin is not None and origin not in self.allowed_origins:
            await JSONResponse({"detail": CROSS_ORIGIN_DETAIL}, status_code=403)(scope, receive, send)
            return
        if not agent_work_allowed():
            await JSONResponse({"detail": READ_ONLY_DETAIL}, status_code=503)(scope, receive, send)
            return

        if scope["path"] == _UPLOAD_PATH:
            # Read at call time, so the cap follows MAX_FILE_SIZE.
            limit = file_handler.MAX_FILE_SIZE + _UPLOAD_FRAMING_ALLOWANCE
            detail = file_handler.FILE_TOO_LARGE_MESSAGE
        else:
            limit, detail = _REQUEST_SIZE_LIMIT, REQUEST_TOO_LARGE_MESSAGE
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)
            return

        received = 0

        async def receive_within_limit() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail=detail)
            return message

        await self.app(scope, receive_within_limit, send)


def _header(scope: Scope, name: bytes) -> str | None:
    """The first value of a request header, decoded as latin-1 (as Starlette does), or None."""
    for key, value in scope["headers"]:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _content_length(scope: Scope) -> int | None:
    value = _header(scope, b"content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
