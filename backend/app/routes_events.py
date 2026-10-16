"""Event route: GET /api/events streams the event bus as text/event-stream (plan §6.1, §6.2).

The route is protected by `require_api_token`. It returns a streaming response
whose body is produced by `app.events.stream_events`. That generator already
formats every block as SSE text, including the connected comment and the
keep-alive comments, so this route passes its output through unchanged.

`sse_starlette.EventSourceResponse` is deliberately not used. It would wrap each
yielded string in its own `data:` framing, which would double-wrap the blocks
that `stream_events` already formats.

Shared-service access convention (matches routes_graph.py and routes_documents.py):

- The process-wide `EventBus` is stored as `app.state.event_bus` by main.py.
- The route never constructs the bus. It takes it through `get_event_bus`, which
  reads `request.app.state`. Tests replace it with
  `app.dependency_overrides[get_event_bus]`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth import require_api_token
from app.events import EventBus, stream_events

router = APIRouter()


def get_event_bus(request: Request) -> EventBus:
    """Return the process-wide EventBus stored on app.state by main.py."""
    return request.app.state.event_bus  # type: ignore[no-any-return]


@router.get("/api/events", dependencies=[Depends(require_api_token)])
async def get_events(
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """Stream every event published on the bus. Requires the X-API-Token header."""
    return StreamingResponse(
        stream_events(bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
