"""Document and insertion-tracking registry tables and operations (plan §6.5).

Two tables are registered on the shared `Base` from `app.db`:

- documents: one row per uploaded file, with its insertion status and progress.
- insertion_chunks: one row per chunk. It is written as `pending` before the
  Graphiti call and changed to `inserted` once the insert is confirmed. Startup
  recovery reads these rows to find interrupted insertions.

The functions take an explicit SQLAlchemy Session from the caller. Each write
commits before it returns, so a pending row is durable before the Graphiti call
that follows it. All queries use the ORM with bound parameters. No SQL text is
built from strings.
"""

import uuid
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db import Base, engine

DOCUMENT_STATUSES: Final[tuple[str, ...]] = ("processing", "done", "failed", "interrupted")
CHUNK_STATES: Final[tuple[str, ...]] = ("pending", "inserted")


def _utc_now() -> datetime:
    """Current UTC time as a naive datetime, the form MySQL DATETIME stores."""
    return datetime.now(UTC).replace(tzinfo=None)


class Document(Base):
    """An uploaded document and its insertion progress."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks_done: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    chunks: Mapped[list[InsertionChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class InsertionChunk(Base):
    """Tracking row for one chunk. The episode UUID is generated before the Graphiti call."""

    __tablename__ = "insertion_chunks"

    episode_uuid: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))

    document: Mapped[Document] = relationship(back_populates="chunks")


def _check_status(status: str) -> None:
    if status not in DOCUMENT_STATUSES:
        raise ValueError(f"unknown document status: {status!r}")


def _get_document(session: Session, doc_id: uuid.UUID) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise LookupError(f"no document with id {doc_id}")
    return doc


def _get_chunk(session: Session, episode_uuid: uuid.UUID) -> InsertionChunk:
    chunk = session.get(InsertionChunk, episode_uuid)
    if chunk is None:
        raise LookupError(f"no insertion chunk with episode_uuid {episode_uuid}")
    return chunk


def create_document(
    session: Session,
    *,
    doc_id: uuid.UUID,
    filename: str,
    stored_name: str,
    size_bytes: int,
) -> Document:
    """Insert a documents row with status processing and no progress yet."""
    doc = Document(
        id=doc_id,
        filename=filename,
        stored_name=stored_name,
        size_bytes=size_bytes,
        status="processing",
        error=None,
        chunks_total=None,
        chunks_done=0,
    )
    session.add(doc)
    session.commit()
    return doc


def set_document_status(
    session: Session,
    doc_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
    chunks_total: int | None = None,
) -> Document:
    """Set a document's status. Sets error (None clears it) and chunks_total when given."""
    _check_status(status)
    doc = _get_document(session, doc_id)
    doc.status = status
    doc.error = error
    if chunks_total is not None:
        doc.chunks_total = chunks_total
    session.commit()
    return doc


def increment_chunks_done(session: Session, doc_id: uuid.UUID) -> Document:
    """Add one to chunks_done after a chunk insert is confirmed."""
    doc = _get_document(session, doc_id)
    doc.chunks_done = doc.chunks_done + 1
    session.commit()
    return doc


def record_pending_chunk(
    session: Session,
    *,
    episode_uuid: uuid.UUID,
    doc_id: uuid.UUID,
    chunk_index: int,
) -> InsertionChunk:
    """Insert an insertion_chunks row with state pending. Call this before the Graphiti call."""
    chunk = InsertionChunk(
        episode_uuid=episode_uuid,
        doc_id=doc_id,
        chunk_index=chunk_index,
        state="pending",
    )
    session.add(chunk)
    session.commit()
    return chunk


def mark_chunk_inserted(session: Session, episode_uuid: uuid.UUID) -> InsertionChunk:
    """Change one tracking row from pending to inserted."""
    chunk = _get_chunk(session, episode_uuid)
    chunk.state = "inserted"
    session.commit()
    return chunk


def list_documents(session: Session) -> list[Document]:
    """Return all documents, newest first."""
    stmt = select(Document).order_by(Document.created_at.desc(), Document.id)
    return list(session.scalars(stmt).all())


def list_tracked_chunks(session: Session, doc_id: uuid.UUID) -> list[InsertionChunk]:
    """Return every insertion_chunks row for one document, in chunk order."""
    stmt = (
        select(InsertionChunk)
        .where(InsertionChunk.doc_id == doc_id)
        .order_by(InsertionChunk.chunk_index)
    )
    return list(session.scalars(stmt).all())


def delete_document(session: Session, doc_id: uuid.UUID) -> bool:
    """Delete a document and its tracking rows. Returns False when no such document exists.

    The ORM cascade removes the insertion_chunks rows. The foreign key's
    ON DELETE CASCADE does the same at the database level.
    """
    doc = session.get(Document, doc_id)
    if doc is None:
        return False
    session.delete(doc)
    session.commit()
    return True


def count_documents(session: Session) -> int:
    """Return how many documents exist. Used for the MAX_DOCUMENTS check."""
    total = session.scalar(select(func.count()).select_from(Document))
    return int(total or 0)


def create_all() -> None:
    """Create any missing registry tables on the app engine. Called from the startup lifespan."""
    Base.metadata.create_all(engine)
