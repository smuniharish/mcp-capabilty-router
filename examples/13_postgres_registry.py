"""Share capability metadata between processes through PostgreSQL.

A `CapabilityRegistry` on asyncpg. Every runtime that points at the same
database sees the same capabilities, so one process can refresh while others
only retrieve.

Requires a PostgreSQL database:

    MCP_ROUTER_EXAMPLE_POSTGRES_DSN=postgresql://user:password@localhost:5432/db
"""

import asyncio
import os
from collections.abc import Iterable, Sequence

import asyncpg
from common import billing_server, capability_from_json, capability_to_json

from mcp_capability_router import Capability, CapabilityType, MCPRuntime

SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_capabilities (
    id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    type TEXT NOT NULL,
    document JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS mcp_capabilities_server ON mcp_capabilities (server_id);
"""


class PostgresRegistry:
    """A capability registry stored in PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresRegistry":
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        await pool.execute(SCHEMA)
        return cls(pool)

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
        await self._pool.execute(
            "DELETE FROM mcp_capabilities WHERE id = $1", capability_id
        )

    async def remove_server(self, server_id: str) -> None:
        await self._pool.execute(
            "DELETE FROM mcp_capabilities WHERE server_id = $1", server_id
        )

    async def get(self, capability_id: str) -> Capability | None:
        document = await self._pool.fetchval(
            "SELECT document FROM mcp_capabilities WHERE id = $1", capability_id
        )
        return capability_from_json(document) if document is not None else None

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

    async def close(self) -> None:
        await self._pool.close()


async def main() -> None:
    dsn = os.environ["MCP_ROUTER_EXAMPLE_POSTGRES_DSN"]
    registry = await PostgresRegistry.connect(dsn)
    await registry.remove_server("billing")  # start from a clean table
    async with MCPRuntime(registry=registry) as refresher:
        await refresher.register_mcp("billing", billing_server())
        result = await refresher.refresh_server("billing")
        print(f"refreshing process stored {result.added_count} capabilities")

        async with MCPRuntime(registry=await PostgresRegistry.connect(dsn)) as reader:
            await reader.register_mcp("billing", billing_server())
            [match] = await reader.retrieve("refund an invoice", limit=1)
            print(f"another process retrieves: {match.capability_id}")

        await refresher.unregister_server("billing")
    print("cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
