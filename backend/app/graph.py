"""Graph lifecycle for Graphiti (plan §6.6).

`GraphService` owns one Neo4j driver and one Graphiti client. It builds both
from `Settings` and the three model clients from `build_model_clients()`.

- Construction does not contact Neo4j. The neo4j driver only stores the URI
  and credentials; the first network call happens inside start() or a later
  Graphiti call.
- start() creates the Neo4j indices and constraints.
- close() releases the driver connection.

Tests inject model clients by passing `models=ModelClients(...)`. Only the
clients the caller does not supply are built from Settings through
`build_model_clients()`, which the caller can also override.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from graphiti_core import Graphiti
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.errors import NodeNotFoundError
from graphiti_core.nodes import EpisodeType, EpisodicNode
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_CROSS_ENCODER

from app.config import Settings, settings
from app.models import ModelClients, build_model_clients

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrieveResult:
    """The IDs and facts returned by one hybrid search.

    `facts` and `edge_ids` are parallel lists. `episode_uuids_by_edge` maps each
    edge UUID to the UUIDs of the episodes that reference it. Mapping those
    episode UUIDs to document IDs is left to the caller.
    """

    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    episode_uuids_by_edge: dict[str, list[str]] = field(default_factory=dict)


class GraphService:
    """Holds the Neo4j driver and the Graphiti client for the process lifetime."""

    def __init__(
        self,
        cfg: Settings = settings,
        *,
        models: ModelClients | None = None,
    ) -> None:
        """Build the driver and the Graphiti client. Does not connect to Neo4j.

        Args:
            cfg: The settings to build from. Defaults to the module-level `settings`.
            models: The model clients to pass to Graphiti. If None, they are built
                from `cfg` by `build_model_clients()`.
        """
        clients = models if models is not None else build_model_clients(cfg)
        self.driver = Neo4jDriver(
            uri=cfg.NEO4J_URI,
            user=cfg.NEO4J_USER,
            password=cfg.NEO4J_PASSWORD,
            database=cfg.NEO4J_DATABASE,
        )
        self.graphiti = Graphiti(
            llm_client=clients.llm_client,
            embedder=clients.embedder,
            cross_encoder=clients.reranker,
            graph_driver=self.driver,
        )
        self._group_id = cfg.GRAPH_GROUP_ID
        self._retrieval_limit = cfg.RETRIEVAL_LIMIT

    async def start(self) -> None:
        """Create the Neo4j indices and constraints. Needs a reachable Neo4j."""
        await self.graphiti.build_indices_and_constraints()

    async def close(self) -> None:
        """Close the Graphiti client and its Neo4j driver."""
        # graphiti-core 0.31.1 declares Graphiti.close without annotations.
        await self.graphiti.close()  # type: ignore[no-untyped-call]

    async def insert_episode(
        self,
        episode_uuid: str,
        name: str,
        body: str,
        source_description: str,
    ) -> None:
        """Add one text episode to the graph under the caller's UUID.

        Writes no tracking row; the insert pipeline (plan §6.5) writes that
        before and after this call. graphiti-core 0.31.1 only accepts a `uuid`
        for an episode that already exists, so a bare episode is saved under
        that UUID first and then `add_episode` runs extraction against it.

        Args:
            episode_uuid: The UUID the caller generated for this episode.
            name: The episode name.
            body: The episode text (one chunk).
            source_description: Where the text came from.
        """
        reference_time = datetime.now(UTC)
        stub = EpisodicNode(
            uuid=episode_uuid,
            name=name,
            group_id=self._group_id,
            source=EpisodeType.text,
            content=body,
            source_description=source_description,
            valid_at=reference_time,
        )
        await stub.save(self.driver)
        await self.graphiti.add_episode(
            name=name,
            episode_body=body,
            source_description=source_description,
            reference_time=reference_time,
            source=EpisodeType.text,
            group_id=self._group_id,
            uuid=episode_uuid,
        )

    async def remove_episode(self, episode_uuid: str) -> None:
        """Remove one episode from the graph. A missing episode counts as success.

        Graphiti looks the episode up first and raises NodeNotFoundError when no
        episode has that UUID. A pending chunk may never have been written, so
        that case is logged and treated as already removed. Other errors propagate.

        Args:
            episode_uuid: The UUID of the episode to remove.
        """
        try:
            await self.graphiti.remove_episode(episode_uuid)
        except NodeNotFoundError:
            logger.info("episode %s not found, treating as already removed", episode_uuid)

    async def retrieve(self, query: str) -> RetrieveResult:
        """Run the cross-encoder hybrid search, limited to this service's group.

        The recipe is copied with `limit` set from `RETRIEVAL_LIMIT`. Only edges
        carry facts and episode references, so the per-edge episode UUIDs are
        taken from each edge's `episodes` list.

        Args:
            query: The search text.

        Returns:
            The node UUIDs, the edge UUIDs, the fact text of each edge, and the
            episode UUIDs of each edge.
        """
        config = COMBINED_HYBRID_SEARCH_CROSS_ENCODER.model_copy(
            update={"limit": self._retrieval_limit}
        )
        results = await self.graphiti.search_(
            query,
            config=config,
            group_ids=[self._group_id],
        )
        return RetrieveResult(
            node_ids=[node.uuid for node in results.nodes],
            edge_ids=[edge.uuid for edge in results.edges],
            facts=[edge.fact for edge in results.edges],
            episode_uuids_by_edge={edge.uuid: list(edge.episodes) for edge in results.edges},
        )
