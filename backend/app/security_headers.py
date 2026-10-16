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
- An unhandled exception in a route is caught here. The full traceback is
  logged, and the client gets the generic 500 JSON body
  ``{"detail": "Internal server error."}``, the same shape ``main.py`` uses.
  The response also gets the headers. Starlette's own 500 handler sits
  outside user middleware and would otherwise send it without them.
- This except-branch is the path that actually runs for route exceptions.
  ``BaseHTTPMiddleware`` sits outside the app's exception-handling machinery,
  so it catches the exception before the ``@app.exception_handler(Exception)``
  registered in ``main.py`` gets a chance. Do not remove it as redundant.
- ``GENERIC_ERROR_DETAIL`` below must stay in sync with ``main.py``'s
  ``GENERIC_ERROR_DETAIL`` if either value changes.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# Must match main.py's GENERIC_ERROR_DETAIL exactly. Hard-coded here on purpose:
# this module does not import main.py.
GENERIC_ERROR_DETAIL = "Internal server error."


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the plan §9.3 security headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            # The message names the method and path only. It never includes
            # str(exc), because that can carry document text. exc_info logs the
            # full traceback separately. It is never sent to the client.
            logger.error(
                "Unhandled exception in %s %s",
                request.method,
                request.url.path,
                exc_info=exc,
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": GENERIC_ERROR_DETAIL},
            )
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response
