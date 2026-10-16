"""MySQL engine, session factory, and shared declarative Base (plan §6.7).

This module owns the one SQLAlchemy Engine for the app and a session factory
bound to it. It defines no tables. `Base` is exported so the registry module
(T2.6) can register its ORM models on `Base.metadata`, and startup can call
`Base.metadata.create_all(engine)` against this engine.

The connection URL is built with `URL.create()`, never by string concatenation,
so special characters in the password are escaped by SQLAlchemy. The password
is never logged here. `str(engine.url)` and `repr(engine.url)` print
`***` in place of the password.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models. Tables are registered on its metadata."""


def build_database_url() -> URL:
    """Return the MySQL URL for the PyMySQL driver, with utf8mb4 as the charset."""
    return URL.create(
        drivername="mysql+pymysql",
        username=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        database=settings.MYSQL_DATABASE,
        query={"charset": "utf8mb4"},
    )


def build_engine() -> Engine:
    """Create the pooled engine. Pooling stays on (QueuePool); no NullPool.

    create_engine does not open a connection, so building the engine never
    needs a live MySQL server.
    """
    return create_engine(
        build_database_url(),
        pool_pre_ping=True,
    )


engine: Engine = build_engine()

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)
