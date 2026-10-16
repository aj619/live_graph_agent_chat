"""Document routes: GET, POST and DELETE /api/documents (plan §6.1, §6.3, §6.5).

All three routes are protected by `require_api_token`.

- GET lists every document, newest first, with its status.
- POST validates the upload in plan §6.3 order (token, count, extension, size),
  saves the file under DATA_DIR/uploads, inserts the `documents` row, publishes the
  first `document.status` event, and starts `insert_document` as a background task.
  Content checks (PDF magic, DOCX open, TXT decode) run first inside that background
  task, through extract.py. A bad file therefore gets 201 and then status `failed`.
- DELETE removes the graph episodes, the registry row and the stored file, through
  `delete_document_everywhere` (T2.19). It returns 204, or 404 for an unknown id.

The file name from the client is never used as a filesystem path. Only the
generated `stored_name` (doc id plus the validated extension) touches the disk.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.auth import require_api_token
from app.config import settings
from app.db import SessionLocal
from app.events import EventBus
from app.graph import GraphService
from app.insert import insert_document
from app.recovery import delete_document_everywhere
from app.registry import Document, count_documents, create_document, list_documents

router = APIRouter()

EVENT_DOCUMENT_STATUS = "document.status"
_BYTES_PER_MB = 1024 * 1024


class DocumentResponse(BaseModel):
    """One document as the API shows it. `stored_name` is internal and never exposed."""

    id: str
    filename: str
    status: str
    error: str | None
    chunks_total: int | None
    chunks_done: int
    created_at: datetime


class DocumentListResponse(BaseModel):
    """The GET /api/documents body: every document, newest first."""

    documents: list[DocumentResponse]


def get_graph_service(request: Request) -> GraphService:
    """Return the process-wide GraphService stored on app.state by main.py."""
    return request.app.state.graph_service  # type: ignore[no-any-return]


def get_event_bus(request: Request) -> EventBus:
    """Return the process-wide EventBus stored on app.state by main.py."""
    return request.app.state.event_bus  # type: ignore[no-any-return]


def _to_response(doc: Document) -> DocumentResponse:
    """Map a Document row to the public response shape."""
    return DocumentResponse(
        id=str(doc.id),
        filename=doc.filename,
        status=doc.status,
        error=doc.error,
        chunks_total=doc.chunks_total,
        chunks_done=doc.chunks_done,
        created_at=doc.created_at,
    )


def _allowed_extensions() -> set[str]:
    """Return ALLOWED_EXTENSIONS as a set of lowercase extensions without dots."""
    return {
        entry.strip().lower().lstrip(".")
        for entry in settings.ALLOWED_EXTENSIONS.split(",")
        if entry.strip()
    }


@router.get(
    "/api/documents",
    response_model=DocumentListResponse,
    dependencies=[Depends(require_api_token)],
)
def get_documents() -> DocumentListResponse:
    """List every document with its status. Requires the X-API-Token header."""
    with SessionLocal() as session:
        rows = list_documents(session)
        return DocumentListResponse(documents=[_to_response(doc) for doc in rows])


@router.post(
    "/api/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_token)],
)
async def upload_document(
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    graph: Annotated[GraphService, Depends(get_graph_service)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> DocumentResponse:
    """Validate and store one upload, then start its insertion. Requires the X-API-Token header.

    Errors: 409 when MAX_DOCUMENTS is reached, 415 for a disallowed extension,
    413 when the file is larger than MAX_FILE_SIZE_MB.
    """
    max_bytes = settings.MAX_FILE_SIZE_MB * _BYTES_PER_MB

    with SessionLocal() as session:
        if count_documents(session) >= settings.MAX_DOCUMENTS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The maximum number of documents has been reached.",
            )

    original_name = file.filename or ""
    extension = Path(original_name).suffix.lstrip(".").lower()
    if not extension or extension not in _allowed_extensions():
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This file type is not allowed.",
        )

    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The file is larger than the allowed size.",
        )

    doc_id = uuid.uuid4()
    stored_name = f"{doc_id}.{extension}"
    uploads_dir = Path(settings.DATA_DIR) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    file_path = uploads_dir / stored_name
    file_path.write_bytes(content)

    try:
        with SessionLocal() as session:
            doc = create_document(
                session,
                doc_id=doc_id,
                filename=original_name,
                stored_name=stored_name,
                size_bytes=len(content),
            )
            response = _to_response(doc)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    bus.publish(
        EVENT_DOCUMENT_STATUS,
        {
            "id": str(doc_id),
            "status": "processing",
            "error": None,
            "chunks_done": 0,
            "chunks_total": None,
        },
    )
    # insert_document is wrapped by tracing.observe, whose return type mypy reads as a
    # union, so the callable does not match add_task's signature. The runtime call is correct.
    background_tasks.add_task(
        insert_document,  # type: ignore[arg-type]
        doc_id,
        file_path,
        extension,
        original_name,
        graph,
        bus,
    )
    return response


@router.delete(
    "/api/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_token)],
)
async def remove_document(
    doc_id: uuid.UUID,
    graph: Annotated[GraphService, Depends(get_graph_service)],
) -> Response:
    """Remove one document everywhere. Returns 204, or 404 when it does not exist."""
    if not await delete_document_everywhere(graph, doc_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
