"""Security headers for every API response (plan §9.3 "Application security").

Plan §9.3 says the nginx layer sends ``X-Content-Type-Options: nosniff`` and
``Referrer-Policy: no-referrer``, and that the backend sends the same two
headers for API responses. This module holds the backend half: a middleware
that adds exactly those two headers.

- ``SecurityHeadersMiddleware`` is a ``BaseHTTPMiddleware`` subclass. The app
  registers it in a later task (T2.31, ``main.py``). This module does not
  register it.
- The header values are fixed by the plan. They are not ``Settings`` entries
  (plan §5 does not define them), so they are module constants.
- Every response gets the headers, whatever the route's status code.
- An unhandled exception in a route becomes a plain 500 response built here,
  so that response also gets the headers. Starlette's own 500 handler sits
  outside user middleware and would otherwise send it without them.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the plan §9.3 security headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            # Log the exception type only. The message can carry document text.
            logger.error(
                "Unhandled exception in %s %s: %s",
                request.method,
                request.url.path,
                type(exc).__name__,
            )
            response = PlainTextResponse("Internal Server Error", status_code=500)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response
