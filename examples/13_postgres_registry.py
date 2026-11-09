"""Share capability metadata and refresh state between processes through PostgreSQL.

Two extension points, one database:

- `PostgresRegistry` implements `CapabilityRegistry` on asyncpg, so every runtime
  that points at the database sees the same capabilities: one process can refresh
  while others only retrieve.
- `PostgresStateStore` implements refresh-engine's `StateStore`, keeping the
  fingerprints of each server's capabilities. `MCPRuntime(state_store_factory=...)`
  gives every server its own store, partitioned by server ID, so a restarted
  process knows what it already stored and a refresh writes only what changed.

Requires a PostgreSQL database:

    MCP_ROUTER_EXAMPLE_POSTGRES_DSN=postgresql://user:password@localhost:5432/db
"""

import asyncio
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from types import MappingProxyType

import asyncpg
from common import billing_server, capability_from_json, capability_to_json
from refresh_engine import (
    ResourceFingerprint,
    ResourceState,
    StateStore,
    StateStoreError,
    StateTransaction,
)

from mcp_capability_router import (
    Capability,
    CapabilityRegistry,
    CapabilityType,
    MCPRuntime,
    RefreshPolicy,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_capabilities (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    type TEXT NOT NULL,
    document JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS mcp_capabilities_server ON mcp_capabilities (server_id);
CREATE TABLE IF NOT EXISTS mcp_refresh_state (
    server_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    state JSONB NOT NULL,
    refreshed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (server_id, resource_id)
);
"""


class PostgresRegistry(CapabilityRegistry):
    """A capability registry stored in PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        await self._pool.executemany(
            "INSERT INTO mcp_capabilities VALUES ($1, $2, $3, $4)"
            " ON CONFLICT (id) DO UPDATE SET server_id = EXCLUDED.server_id,"
            " type = EXCLUDED.type, document = EXCLUDED.document",
            [
                (
                    capability.capability_id,
                    capability.server_id,
                    str(capability.type),
                    capability_to_json(capability),
                )
                for capability in capabilities
            ],
        )

    async def remove(self, capability_id: str) -> None:
        await self._pool.execute("DELETE FROM mcp_capabilities WHERE id = $1", capability_id)

    async def remove_server(self, server_id: str) -> None:
        await self._pool.execute("DELETE FROM mcp_capabilities WHERE server_id = $1", server_id)

    async def get(self, capability_id: str) -> Capability | None:
        document = await self._pool.fetchval(
            "SELECT document FROM mcp_capabilities WHERE id = $1", capability_id
        )
        return capability_from_json(document) if document is not None else None

    async def get_many(self, capability_ids: Iterable[str]) -> dict[str, Capability]:
        """Fetch every capability in one round trip instead of one query per ID."""
        rows = await self._pool.fetch(
            "SELECT id, document FROM mcp_capabilities WHERE id = ANY($1::text[])",
            list(capability_ids),
        )
        return {row["id"]: capability_from_json(row["document"]) for row in rows}

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> Sequence[Capability]:
        rows = await self._pool.fetch(
            "SELECT document FROM mcp_capabilities"
            " WHERE ($1::text IS NULL OR server_id = $1)"
            " AND ($2::text IS NULL OR type = $2) ORDER BY id",
            server_id,
            None if type is None else str(type),
        )
        return [capability_from_json(row["document"]) for row in rows]


class PostgresStateStore(StateStore):
    """The refresh state of one server, in a table shared by every server."""

    def __init__(self, pool: asyncpg.Pool, server_id: str) -> None:
        self._pool = pool
        self._server_id = server_id

    async def load_all(self) -> Mapping[str, ResourceState]:
        try:
            rows = await self._pool.fetch(
                "SELECT resource_id, state, refreshed_at FROM mcp_refresh_state"
                " WHERE server_id = $1",
                self._server_id,
            )
        except asyncpg.PostgresError as error:
            msg = f"cannot load the state of {self._server_id!r}: {error}"
            raise StateStoreError(msg) from error
        states = {}
        for row in rows:
            state = json.loads(row["state"])
            states[row["resource_id"]] = ResourceState(
                row["resource_id"],
                ResourceFingerprint(state["algorithm"], state["value"]),
                version=state["version"],
                cheap_indicator=state["cheap_indicator"],
                snapshot_metadata=state["snapshot_metadata"],
                dependencies=frozenset(state["dependencies"]),
                refreshed_at=row["refreshed_at"],
            )
        return MappingProxyType(states)

    async def transaction(self) -> StateTransaction:
        return PostgresTransaction(self._pool, self._server_id)


class PostgresTransaction(StateTransaction):
    """Applies the staged changes of a refresh in one PostgreSQL transaction."""

    def __init__(self, pool: asyncpg.Pool, server_id: str) -> None:
        super().__init__()
        self._pool = pool
        self._server_id = server_id

    async def apply_changes(
        self, puts: Mapping[str, ResourceState], deletes: AbstractSet[str], /
    ) -> None:
        rows = [
            (
                self._server_id,
                state.resource_id,
                json.dumps(
                    {
                        "algorithm": state.fingerprint.algorithm,
                        "value": state.fingerprint.value,
                        "version": state.version,
                        "cheap_indicator": state.cheap_indicator,
                        "snapshot_metadata": dict(state.snapshot_metadata),
                        "dependencies": sorted(state.dependencies),
                    }
                ),
                state.refreshed_at,
            )
            for state in puts.values()
        ]
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "DELETE FROM mcp_refresh_state"
                    " WHERE server_id = $1 AND resource_id = ANY($2::text[])",
                    self._server_id,
                    sorted(deletes),
                )
                await connection.executemany(
                    "INSERT INTO mcp_refresh_state VALUES ($1, $2, $3, $4)"
                    " ON CONFLICT (server_id, resource_id) DO UPDATE SET"
                    " state = EXCLUDED.state, refreshed_at = EXCLUDED.refreshed_at",
                    rows,
                )
        except asyncpg.PostgresError as error:
            msg = f"cannot commit the state of {self._server_id!r}: {error}"
            raise StateStoreError(msg) from error


async def main() -> None:
    dsn = os.environ["MCP_ROUTER_EXAMPLE_POSTGRES_DSN"]
    async with asyncpg.create_pool(dsn, min_size=1, max_size=4) as pool:
        await pool.execute(SCHEMA)
        # Start from clean tables, so the example can run repeatedly.
        await pool.execute("DELETE FROM mcp_capabilities WHERE server_id = 'billing'")
        await pool.execute("DELETE FROM mcp_refresh_state WHERE server_id = 'billing'")

        def runtime() -> MCPRuntime:
            return MCPRuntime(
                registry=PostgresRegistry(pool),
                state_store_factory=lambda server_id: PostgresStateStore(pool, server_id),
            )

        policy = RefreshPolicy(on_register=True)
        async with runtime() as refresher:
            await refresher.register_mcp("billing", billing_server(), refresh=policy)
            stored = await pool.fetchval(
                "SELECT count(*) FROM mcp_refresh_state WHERE server_id = 'billing'"
            )
            print(f"refreshing process stored {stored} fingerprints")

            async with runtime() as reader:
                await reader.register_mcp("billing", billing_server())
                [match] = await reader.retrieve("refund an invoice", limit=1)
                print(f"another process retrieves: {match.capability_id}")

        async with runtime() as restarted:
            await restarted.register_mcp("billing", billing_server())
            result = await restarted.refresh_server("billing")
            print(
                f"after a restart, a refresh finds {result.unchanged_count} unchanged and "
                f"{result.added_count + result.modified_count} new or modified capabilities"
            )
            await restarted.unregister_server("billing")
    print("cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
