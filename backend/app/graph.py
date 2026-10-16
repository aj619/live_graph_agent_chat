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

from graphiti_core import Graphiti
from graphiti_core.driver.neo4j_driver import Neo4jDriver

from app.config import Settings, settings
from app.models import ModelClients, build_model_clients


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

    async def start(self) -> None:
        """Create the Neo4j indices and constraints. Needs a reachable Neo4j."""
        await self.graphiti.build_indices_and_constraints()

    async def close(self) -> None:
        """Close the Graphiti client and its Neo4j driver."""
        # graphiti-core 0.31.1 declares Graphiti.close without annotations.
        await self.graphiti.close()  # type: ignore[no-untyped-call]
