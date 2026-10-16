"""System routes: liveness and client-facing limits (plan §6.1).

GET /api/health is public. It carries no auth dependency, so a probe without
a token gets 200. GET /api/config needs the shared token, because it exposes
server limits that only the frontend proxy should read.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_api_token
from app.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


class ConfigResponse(BaseModel):
    """Limits the frontend reads to pre-validate uploads.

    Field names stay snake_case, which matches the other API bodies.
    allowed_extensions is a list. The raw setting is comma-separated, so it
    is split on commas, each entry is stripped of whitespace, and empty
    entries are dropped.
    """

    max_documents: int
    max_file_size_mb: int
    allowed_extensions: list[str]


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe. No token required."""
    return HealthResponse(status="ok")


@router.get(
    "/api/config",
    response_model=ConfigResponse,
    dependencies=[Depends(require_api_token)],
)
def config() -> ConfigResponse:
    """Return the upload and agent limits. Requires the X-API-Token header."""
    extensions = [
        entry.strip() for entry in settings.ALLOWED_EXTENSIONS.split(",") if entry.strip()
    ]
    return ConfigResponse(
        max_documents=settings.MAX_DOCUMENTS,
        max_file_size_mb=settings.MAX_FILE_SIZE_MB,
        allowed_extensions=extensions,
    )
