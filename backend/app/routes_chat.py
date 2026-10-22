"""Chat route: POST /api/chat starts one agent run, returns 202 with its chat_id.

Plan §6.1 and §9.3 cover this route.

The route is protected by `require_api_token`. For each request it runs these steps in order:

0. `time.monotonic()` is captured as `received_at`, before any validation —
   the closest app-level approximation of "when the request reached the web
   server" (true socket-accept time belongs to uvicorn, not route code). It
   is passed through to `agent.run`, which logs the gap from this instant to
   the agent run actually starting as the chat log's first row.
1. Pydantic validates the body. A missing or non-string `message` gives 422.
2. The route rejects a `message` that is empty after stripping whitespace, with 422.
   A whitespace-only message is not a real question.
3. The rate limiter is checked for the caller's API token. A refused call gives 429.
   This check runs before any chat_id is made or any background task is added, so a
   rate-limited request has no side effects.
4. A new `chat_id` (UUID4 string) is made, and `agent.run` is added as a FastAPI
   background task. Background tasks are used, not a bare `asyncio.create_task`, so the
   task keeps a reference and cannot be garbage-collected before it finishes.
5. The route returns 202 with `{"chat_id": ...}`. The answer arrives over GET /api/events.

The rate limiter is keyed by the raw `X-API-Token` value. The route reads that header
again, only to use it as the key. `require_api_token` has already checked the value by
then, so it is never None here. The `"unknown"` fallback is defensive only.

Shared-service access convention (matches routes_graph.py and routes_documents.py):

- The process-wide `GraphService` is stored as `app.state.graph_service` by main.py.
- The process-wide `EventBus` is stored as `app.state.event_bus` by main.py.
- The process-wide `RateLimiter` is stored as `app.state.rate_limiter` by main.py.
  T2.29 (main.py, a separate future task) must set `app.state.rate_limiter = RateLimiter()`
  for this route to work at runtime, the same as it must set `graph_service` and `event_bus`.
- The route takes each one through a dependency that reads `request.app.state`. Tests
  replace them with `app.dependency_overrides`.

The rate limiter is single-process only (see app/ratelimit.py). That matches plan decision D6.
"""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.agent import run
from app.auth import API_TOKEN_HEADER, require_api_token
from app.events import EventBus
from app.graph import GraphService
from app.ratelimit import RateLimiter

router = APIRouter()

_UNKNOWN_TOKEN_KEY = "unknown"


class ChatRequest(BaseModel):
    """The POST /api/chat body. `message` is the user's question."""

    message: str


class ChatResponse(BaseModel):
    """The 202 body. `chat_id` identifies the run in the SSE events."""

    chat_id: str


def get_graph_service(request: Request) -> GraphService:
    """Return the process-wide GraphService stored on app.state by main.py."""
    return request.app.state.graph_service  # type: ignore[no-any-return]


def get_event_bus(request: Request) -> EventBus:
    """Return the process-wide EventBus stored on app.state by main.py."""
    return request.app.state.event_bus  # type: ignore[no-any-return]


def get_rate_limiter(request: Request) -> RateLimiter:
    """Return the process-wide RateLimiter stored on app.state by main.py."""
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


@router.post(
    "/api/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_token)],
)
async def post_chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    graph: Annotated[GraphService, Depends(get_graph_service)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
    x_api_token: Annotated[str | None, Header(alias=API_TOKEN_HEADER)] = None,
) -> ChatResponse:
    """Start one agent run for `message` and return its chat_id with 202.

    Errors: 401 from `require_api_token` for a missing or wrong token. 422 when the
    message is empty after stripping whitespace. 429 when the token is over its
    rate limit. In each error case, no agent run is started.
    """
    received_at = time.monotonic()

    if not body.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The message must not be empty.",
        )

    if not limiter.allow(x_api_token or _UNKNOWN_TOKEN_KEY):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many chat requests. Try again later.",
        )

    chat_id = str(uuid.uuid4())
    background_tasks.add_task(run, chat_id, body.message, graph, bus, received_at)
    return ChatResponse(chat_id=chat_id)
