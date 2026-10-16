"""Startup recovery for insertions cut off by a restart (plan §6.5).

`run_startup_recovery` runs in the app lifespan before the server accepts
requests, and it runs on every boot. For each document whose status is
processing:

1. Remove every tracked episode of the document from the graph, pending and
   inserted alike. A missing episode is skipped by GraphService.remove_episode.
2. Delete the document's insertion_chunks rows. This happens only after all of
   its removals have been attempted, so an interrupted recovery is retried.
3. Set the status to interrupted with a safe message. The document row stays so
   the owner can delete it.

A second run finds no processing documents and does nothing. Logs carry document
IDs and counts only, never filenames or text.
"""

import logging
import uuid
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.graph import GraphService
from app.registry import (
    Document,
    delete_document,
    list_documents,
    list_tracked_chunks,
    set_document_status,
)

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE: Final[str] = "Insertion was interrupted by a restart. Delete and upload again."
PROCESSING_STATUS: Final[str] = "processing"
INTERRUPTED_STATUS: Final[str] = "interrupted"


async def _recover_document(
    session: Session,
    graph: GraphService,
    doc_id: uuid.UUID,
) -> int:
    """Clean up one interrupted document. Returns the number of tracked episodes removed."""
    chunks = list_tracked_chunks(session, doc_id)
    for chunk in chunks:
        await graph.remove_episode(str(chunk.episode_uuid))
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    set_document_status(session, doc_id, INTERRUPTED_STATUS, error=INTERRUPTED_MESSAGE)
    return len(chunks)


async def run_startup_recovery(graph: GraphService) -> int:
    """Clean up every document left in processing by a restart.

    Args:
        graph: The GraphService used to remove episodes from the graph.

    Returns:
        The number of documents recovered on this run. Zero on a second run.
    """
    recovered = 0
    with SessionLocal() as session:
        interrupted = [doc for doc in list_documents(session) if doc.status == PROCESSING_STATUS]
        for doc in interrupted:
            episode_count = await _recover_document(session, graph, doc.id)
            logger.info(
                "recovered interrupted document %s: removed %d tracked episodes",
                doc.id,
                episode_count,
            )
            recovered += 1
    return recovered


async def delete_document_everywhere(graph: GraphService, doc_id: uuid.UUID) -> bool:
    """Delete one document from the graph, the registry, and the upload store.

    This is the removal path the DELETE document API route uses. It runs in
    crash-safety order:

    1. Remove every tracked episode of the document from the graph.
    2. Delete the document row. The ORM cascade removes its insertion_chunks rows.
    3. Delete the stored file last.

    Args:
        graph: The GraphService used to remove episodes from the graph.
        doc_id: The ID of the document to delete.

    Returns:
        True when the document existed and was deleted. False when no such
        document exists, in which case nothing is touched.
    """
    with SessionLocal() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            return False
        stored_name = doc.stored_name
        chunks = list_tracked_chunks(session, doc_id)
        for chunk in chunks:
            await graph.remove_episode(str(chunk.episode_uuid))
        delete_document(session, doc_id)
        episode_count = len(chunks)

    stored_path = Path(settings.DATA_DIR) / "uploads" / stored_name
    try:
        stored_path.unlink()
    except FileNotFoundError:
        logger.warning("stored file for document %s was already missing", doc_id)

    logger.info(
        "deleted document %s: removed %d tracked episodes and their rows",
        doc_id,
        episode_count,
    )
    return True
