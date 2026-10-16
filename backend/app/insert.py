"""Background insertion of one uploaded document into the graph (plan §6.5 steps 2 to 6).

The upload route (T2.25) saves the file and creates the `documents` row with
status `processing` before it starts this task. This module starts from the saved
file and does the rest:

- Extract text and split it into chunks. Set chunks_total.
- For each chunk, in order: write a `pending` insertion_chunks row (durable before
  the Graphiti call), call GraphService.insert_episode under that row's UUID, then
  mark the row `inserted`, increment chunks_done, and publish document.status.
- A failing chunk is retried with the same UUID and the same pending row, up to
  settings.INGEST_RETRIES total attempts. When the attempts run out, the document
  is marked failed and processing stops. Chunks already inserted stay tracked.
- UnsupportedDocument marks the document failed at once. It is not retried.
- When every chunk is inserted, the document is marked done and graph.changed is
  published.

There is no queue and no batching. The caller starts `insert_document` as an
asyncio background task in the same process. The caller also owns the one shared
GraphService and EventBus, which are passed in here and never created here.

Client-facing error messages are generic. They name the exception class, never
the raw exception text, and they never contain document text. The text of an
UnsupportedDocument is the only exception message that is shown, because it
describes the document format and not its content.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.chunking import chunk_text
from app.config import settings
from app.db import SessionLocal
from app.events import EventBus
from app.extract import UnsupportedDocument, extract_text
from app.graph import GraphService
from app.registry import (
    Document,
    increment_chunks_done,
    mark_chunk_inserted,
    record_pending_chunk,
    set_document_status,
)
from app.tracing import observe

logger = logging.getLogger(__name__)

EVENT_DOCUMENT_STATUS = "document.status"
EVENT_GRAPH_CHANGED = "graph.changed"


def _publish_status(bus: EventBus, doc: Document) -> None:
    """Publish document.status with the payload fields from plan §6.2."""
    bus.publish(
        EVENT_DOCUMENT_STATUS,
        {
            "id": str(doc.id),
            "status": doc.status,
            "error": doc.error,
            "chunks_done": doc.chunks_done,
            "chunks_total": doc.chunks_total,
        },
    )


def _fail(session: Session, bus: EventBus, doc_id: uuid.UUID, error: str) -> None:
    """Mark the document failed with a client-safe message and publish the status."""
    doc = set_document_status(session, doc_id, "failed", error=error)
    _publish_status(bus, doc)


async def _insert_with_retries(
    graph: GraphService,
    *,
    episode_uuid: uuid.UUID,
    name: str,
    body: str,
    source_description: str,
) -> Exception | None:
    """Call insert_episode up to INGEST_RETRIES times with the same UUID.

    Returns None on success, or the last exception when every attempt failed.
    """
    attempts = settings.INGEST_RETRIES
    if attempts < 1:
        raise ValueError("INGEST_RETRIES must be at least 1")
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await graph.insert_episode(
                str(episode_uuid),
                name=name,
                body=body,
                source_description=source_description,
            )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Chunk insert attempt %d of %d failed: %s",
                attempt,
                attempts,
                type(exc).__name__,
            )
        else:
            return None
    return last_exc


@observe
async def insert_document(
    doc_id: uuid.UUID,
    file_path: Path,
    extension: str,
    source_description: str,
    graph: GraphService,
    bus: EventBus,
) -> None:
    """Insert every chunk of a saved document and track its progress.

    Args:
        doc_id: id of the existing `documents` row, which has status processing.
        file_path: path of the file the upload route already saved.
        extension: the file's extension (pdf, txt or docx), with or without a dot.
        source_description: passed to Graphiti as each episode's source description.
        graph: the process's shared GraphService.
        bus: the process's shared EventBus.
    """
    with SessionLocal() as session:
        try:
            content = await asyncio.to_thread(file_path.read_bytes)
            text = extract_text(content, extension)
        except UnsupportedDocument as exc:
            _fail(session, bus, doc_id, str(exc))
            return
        except Exception as exc:
            _fail(session, bus, doc_id, f"document could not be read ({type(exc).__name__})")
            return

        chunks = chunk_text(text, settings.INGEST_CHUNK_CHARS)
        total = len(chunks)
        doc = set_document_status(session, doc_id, "processing", chunks_total=total)
        _publish_status(bus, doc)

        for index, body in enumerate(chunks):
            episode_uuid = uuid.uuid4()
            record_pending_chunk(
                session,
                episode_uuid=episode_uuid,
                doc_id=doc_id,
                chunk_index=index,
            )
            failure = await _insert_with_retries(
                graph,
                episode_uuid=episode_uuid,
                name=f"chunk {index + 1} of {total}",
                body=body,
                source_description=source_description,
            )
            if failure is not None:
                _fail(
                    session,
                    bus,
                    doc_id,
                    f"insertion failed on chunk {index + 1} of {total} ({type(failure).__name__})",
                )
                return

            mark_chunk_inserted(session, episode_uuid)
            doc = increment_chunks_done(session, doc_id)
            _publish_status(bus, doc)

        doc = set_document_status(session, doc_id, "done")
        _publish_status(bus, doc)
        bus.publish(EVENT_GRAPH_CHANGED, {"doc_id": str(doc_id)})
