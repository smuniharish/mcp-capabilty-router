"""Keep capability metadata in a durable registry.

Implements the `CapabilityRegistry` contract on SQLite, so discovered capabilities
survive a restart: a second runtime retrieves them without contacting any
server. The same approach works for PostgreSQL; see 13_postgres_registry.py.
"""

import asyncio
import sqlite3
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from common import capability_from_json, capability_to_json, crm_server

from mcp_capability_router import (
    Capability,
    CapabilityRegistry,
    CapabilityType,
    MCPRuntime,
    Tool,
)


class SQLiteRegistry:
    """A capability registry stored in a SQLite database file.

    refresh-engine stores capabilities concurrently, and a SQLite connection must
    not be used by several threads at once, so a lock serializes database access.
    """

    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS capabilities ("
            " id TEXT PRIMARY KEY, server_id TEXT, type TEXT, document TEXT)"
        )
        self._lock = asyncio.Lock()

    async def _run(self, sql: str, *parameters: object) -> list[tuple[Any, ...]]:
        def run() -> list[tuple[Any, ...]]:
            with self._connection:
                return self._connection.execute(sql, parameters).fetchall()

        async with self._lock:
            return await asyncio.to_thread(run)

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        for capability in capabilities:
            await self._run(
                "INSERT OR REPLACE INTO capabilities VALUES (?, ?, ?, ?)",
                capability.capability_id,
                capability.server_id,
                str(capability.type),
                capability_to_json(capability),
            )

    async def remove(self, capability_id: str) -> None:
        await self._run("DELETE FROM capabilities WHERE id = ?", capability_id)

    async def remove_server(self, server_id: str) -> None:
        await self._run("DELETE FROM capabilities WHERE server_id = ?", server_id)

    async def get(self, capability_id: str) -> Capability | None:
        rows = await self._run(
            "SELECT document FROM capabilities WHERE id = ?", capability_id
        )
        return capability_from_json(rows[0][0]) if rows else None

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> Sequence[Capability]:
        rows = await self._run(
            "SELECT document FROM capabilities"
            " WHERE (?1 IS NULL OR server_id = ?1) AND (?2 IS NULL OR type = ?2)"
            " ORDER BY id",
            server_id,
            None if type is None else str(type),
        )
        return [capability_from_json(row[0]) for row in rows]

    async def close(self) -> None:
        self._connection.close()


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "capabilities.db"

        registry = SQLiteRegistry(database)
        print(
            f"implements CapabilityRegistry: {isinstance(registry, CapabilityRegistry)}"
        )
        async with MCPRuntime(registry=registry) as runtime:
            await runtime.register_mcp("crm", crm_server())
            result = await runtime.refresh_server("crm")
            print(f"first process stored {result.added_count} capabilities")

        async with MCPRuntime(registry=SQLiteRegistry(database)) as restarted:
            await restarted.register_mcp("crm", crm_server())
            [match] = await restarted.retrieve("change a customer email", limit=1)
            print(f"after a restart, without refreshing: {match.capability_id}")
            assert isinstance(match, Tool)
            print(f"input schema survives: {sorted(match.input_schema['properties'])}")


if __name__ == "__main__":
    asyncio.run(main())
