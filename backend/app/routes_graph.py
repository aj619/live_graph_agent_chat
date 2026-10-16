"""Graph route: GET /api/graph returns the snapshot of this group's graph (plan §6.1).

The route is protected by `require_api_token`. It returns
`{"nodes": [...], "edges": [...]}`, with each node and edge mirroring the
`SnapshotNode` and `SnapshotEdge` dataclasses in `app.graph` field for field.

Shared-service access convention (used by every route that needs a process-wide
service, including routes_documents.py and routes_chat.py):

- The single `GraphService` for the process is created by main.py (T2.29) and
  stored as `app.state.graph_service`.
- The `event_bus` service follows the same pattern as `app.state.event_bus`.
- Routes never construct those services. They take them through a dependency
  such as `get_graph_service` below, which reads `request.app.state`. Tests
  replace the dependency with `app.dependency_overrides[get_graph_service]`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth import require_api_token
from app.graph import GraphService

router = APIRouter()


class GraphNodeResponse(BaseModel):
    """One Entity node. `id` is the node UUID."""

    id: str
    name: str


class GraphEdgeResponse(BaseModel):
    """One RELATES_TO edge. `source_id` and `target_id` are node UUIDs."""

    id: str
    name: str
    fact: str
    source_id: str
    target_id: str


class GraphSnapshotResponse(BaseModel):
    """The graph snapshot. Each list is capped by GRAPH_SNAPSHOT_LIMIT on the server."""

    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


def get_graph_service(request: Request) -> GraphService:
    """Return the process-wide GraphService stored on app.state by main.py."""
    return request.app.state.graph_service  # type: ignore[no-any-return]


@router.get(
    "/api/graph",
    response_model=GraphSnapshotResponse,
    dependencies=[Depends(require_api_token)],
)
async def get_graph(
    graph: Annotated[GraphService, Depends(get_graph_service)],
) -> GraphSnapshotResponse:
    """Return the nodes and edges of GRAPH_GROUP_ID. Requires the X-API-Token header."""
    snapshot = await graph.snapshot()
    return GraphSnapshotResponse(
        nodes=[GraphNodeResponse(id=node.id, name=node.name) for node in snapshot.nodes],
        edges=[
            GraphEdgeResponse(
                id=edge.id,
                name=edge.name,
                fact=edge.fact,
                source_id=edge.source_id,
                target_id=edge.target_id,
            )
            for edge in snapshot.edges
        ],
    )
