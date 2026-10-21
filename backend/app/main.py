"""FastAPI app factory and lifespan (plan §6.5, §6.10, §9.3).

Importing this module:
- configures structured logging before anything else logs (logging_setup);
- imports app.config, which fails loudly when the env file or APP_ENV is missing;
- builds the MySQL engine through app.db (no connection is opened yet).

The lifespan runs on every boot, in this order:
1. create the DATA_DIR/uploads directory and the per-chat call-timing log
   directory (app/call_logging.py);
2. create the MySQL tables;
3. start the graph service (needs a reachable Neo4j);
4. run startup recovery, which must finish before the app serves requests.

Any failure in those steps propagates and stops startup. The graph service is
closed when the app shuts down.

Unhandled exceptions get a generic 500 body. The full traceback goes to the log only.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db  # noqa: F401  (imported so the engine is built before create_all)
from app.call_logging import LOG_DIR
from app.config import settings
from app.events import EventBus
from app.graph import GraphService
from app.logging_setup import configure_logging
from app.ratelimit import RateLimiter
from app.recovery import run_startup_recovery
from app.registry import create_all
from app.routes_chat import router as chat_router
from app.routes_documents import router as documents_router
from app.routes_events import router as events_router
from app.routes_graph import router as graph_router
from app.routes_system import router as system_router
from app.security_headers import SecurityHeadersMiddleware

configure_logging()

logger = logging.getLogger(__name__)

GENERIC_ERROR_DETAIL = "Internal server error."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare storage, tables, the graph service, and recovery before serving."""
    Path(settings.DATA_DIR).joinpath("uploads").mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    create_all()
    graph = GraphService()
    await graph.start()
    await run_startup_recovery(graph)
    app.state.graph_service = graph
    app.state.event_bus = EventBus()
    app.state.rate_limiter = RateLimiter()
    try:
        yield
    finally:
        await graph.close()


app = FastAPI(lifespan=lifespan)

# Allow-list from CORS_ORIGINS. The API needs the X-API-Token header, so headers and
# methods are open, but only the listed origins may call it cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added after CORS so it wraps CORS: every response, including CORS replies, gets the headers.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(system_router)
app.include_router(documents_router)
app.include_router(graph_router)
app.include_router(chat_router)
app.include_router(events_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the full traceback and return a generic 500 with no exception details."""
    logger.error(
        "unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR_DETAIL})
