"""Shared-token check for protected routes (plan §6.4).

Routes attach `Depends(require_api_token)` to every endpoint except GET /api/health.
The browser never sends this header. The frontend proxy adds it.
"""

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import settings

API_TOKEN_HEADER = "X-API-Token"


def require_api_token(
    x_api_token: Annotated[str | None, Header(alias=API_TOKEN_HEADER)] = None,
) -> None:
    """Raise 401 unless the X-API-Token header equals settings.API_TOKEN.

    The comparison is constant-time. Both sides are encoded to bytes, so a
    non-ASCII header value cannot raise TypeError. The detail message never
    echoes the value that was sent.
    """
    if x_api_token is None or not hmac.compare_digest(
        x_api_token.encode("utf-8"), settings.API_TOKEN.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API token.",
        )
