"""Real Postgres-backed CapabilityRegistry, proving the registry is a swappable plugin.

Run:
    podman run -d --name mcp-router-postgres -e POSTGRES_PASSWORD=router \\
        -e POSTGRES_DB=mcp_router -p 5432:5432 postgres:16-alpine
    uv sync --extra examples
    uv run python -m examples.postgres_registry

Just as ``QdrantCapabilityRetriever`` (see ``examples/vector_retrieval_qdrant.py``) proves
retrieval is pluggable without changing ``MCPRuntime``, this example proves the *registry*
is pluggable the same way: ``PostgresCapabilityRegistry`` implements the exact
``CapabilityRegistry`` protocol (``upsert_many``/``remove_missing``/``remove``/``get``/``list``/
``close``) that ``InMemoryRegistry`` implements, backed by a real Postgres table instead of an
in-process dict, and is handed to ``MCPRuntime(registry=...)`` with zero core changes. It
subclasses the optional ``CapabilityRegistryBase`` abstract base class to show that style
of implementing the protocol (see ``examples/custom_registry.py`` for the same protocol
implemented via structural typing only, with no inheritance).
``POSTGRES_URL`` defaults to ``postgresql://postgres:router@localhost:5432/mcp_router``. If a
container runtime's published port is not reachable at ``localhost`` on your host (observed in
this sandbox with Podman on Windows/WSL2 -- see ``docs/guides/agent-integrations.md``), point
``POSTGRES_URL`` at whatever address is actually reachable, e.g. the Podman machine's own IP.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable

import asyncpg

from mcp_capability_router import Capability, CapabilityType, MCPRuntime, Prompt, Resource, Tool
from mcp_capability_router.registry import CapabilityRegistryBase

POSTGRES_URL = os.environ.get(
    "POSTGRES_URL", "postgresql://postgres:router@localhost:5432/mcp_router"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_capabilities (
    capability_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    uri TEXT,
    arguments JSONB NOT NULL DEFAULT '[]'::jsonb
);
"""


class PostgresCapabilityRegistry(CapabilityRegistryBase):
    """``CapabilityRegistry`` implementation backed by a real Postgres table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresCapabilityRegistry:
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
        async with pool.acquire() as connection:
            await connection.execute(_SCHEMA)
        return cls(pool)

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        rows = [
            (
                c.capability_id,
                c.server_id,
                c.type.value,
                c.name,
                c.description,
                getattr(c, "uri", None),
            )
            for c in capabilities
        ]
        if not rows:
            return
        async with self._pool.acquire() as connection:
            await connection.executemany(
                """
                INSERT INTO mcp_capabilities
                    (capability_id, server_id, type, name, description, uri)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (capability_id) DO UPDATE SET
                    server_id = EXCLUDED.server_id,
                    type = EXCLUDED.type,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    uri = EXCLUDED.uri
                """,
                rows,
            )

    async def remove_missing(self, server_id: str, current_ids: set[str]) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                DELETE FROM mcp_capabilities
                WHERE server_id = $1 AND NOT (capability_id = ANY($2::text[]))
                """,
                server_id,
                list(current_ids),
            )

    async def remove(self, capability_id: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM mcp_capabilities WHERE capability_id = $1", capability_id
            )

    async def get(self, capability_id: str) -> Capability | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM mcp_capabilities WHERE capability_id = $1", capability_id
            )
        return _row_to_capability(row) if row else None

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> list[Capability]:
        clauses, params = [], []
        if server_id is not None:
            params.append(server_id)
            clauses.append(f"server_id = ${len(params)}")
        if type is not None:
            params.append(type.value)
            clauses.append(f"type = ${len(params)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(f"SELECT * FROM mcp_capabilities {where}", *params)
        return [_row_to_capability(row) for row in rows]

    async def close(self) -> None:
        await self._pool.close()


def _row_to_capability(row: asyncpg.Record) -> Capability:
    kind = CapabilityType(row["type"])
    common = {
        "capability_id": row["capability_id"],
        "server_id": row["server_id"],
        "name": row["name"],
        "description": row["description"],
    }
    if kind is CapabilityType.TOOL:
        return Tool(**common)
    if kind is CapabilityType.RESOURCE:
        return Resource(**common, uri=row["uri"] or row["name"])
    return Prompt(**common)


class DirectoryAdapter:
    """Small Tool+Resource in-process adapter used to exercise the Postgres registry."""

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "search_orders", "description": "search customer orders"}]

    async def list_resources(self):
        return [{"uri": "file:///policy.txt", "name": "policy", "description": "order policy"}]

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        return "Orders may be cancelled within 24 hours."

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    registry = await PostgresCapabilityRegistry.connect(POSTGRES_URL)
    try:
        async with MCPRuntime(registry=registry) as runtime:
            await runtime.register_server("directory", lambda: DirectoryAdapter())
            await runtime.refresh_server("directory")

            tools = await registry.list(server_id="directory", type=CapabilityType.TOOL)
            print("persisted in Postgres, tools:", [t.name for t in tools])

            match = (await runtime.retrieve("search orders"))[0]
            result = await runtime.execute(match.capability_id, {"customer": "42"})
            print("executed via runtime backed by Postgres registry:", result)

            # Prove persistence: a brand-new registry instance reading the same
            # database sees the capabilities without any runtime/discovery involved.
            reread_registry = await PostgresCapabilityRegistry.connect(POSTGRES_URL)
            try:
                reread = await reread_registry.list(server_id="directory")
                print(
                    "re-read from a second, independent registry connection:",
                    [c.name for c in reread],
                )
            finally:
                await reread_registry.close()
    finally:
        await registry.close()


if __name__ == "__main__":
    asyncio.run(main())
