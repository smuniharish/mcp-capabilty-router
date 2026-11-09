"""Keep capability metadata and refresh state in durable stores.

Implements two contracts on SQLite:

- `CapabilityRegistry`, so discovered capabilities survive a restart: a second
  runtime retrieves them without contacting any server.
- refresh-engine's `StateStore`, passed through `RefreshPolicy(state_store=...)`,
  so the restarted runtime remembers each capability's fingerprint and a refresh
  reports them as unchanged instead of rediscovering everything.

The same approach works for PostgreSQL; see 13_postgres_registry.py.
"""

import asyncio
import json
import sqlite3
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from common import capability_from_json, capability_to_json, crm_server
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
    Tool,
)


class SQLite:
    """One SQLite connection shared by the registry and the state store.

    refresh-engine works concurrently and a SQLite connection must not be used by
    several threads at once, so a lock serializes access; the work itself runs in
    a worker thread to keep the event loop free.
    """

    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.executescript(
            "CREATE TABLE IF NOT EXISTS capabilities ("
            " id TEXT PRIMARY KEY, server_id TEXT, type TEXT, document TEXT);"
            "CREATE TABLE IF NOT EXISTS refresh_state ("
            " resource_id TEXT PRIMARY KEY, state TEXT, refreshed_at TEXT);"
        )
        self._lock = asyncio.Lock()

    async def fetch(self, sql: str, parameters: Mapping[str, Any] | None = None) -> list[Any]:
        def run() -> list[Any]:
            with self._connection:
                return self._connection.execute(sql, parameters or {}).fetchall()

        async with self._lock:
            return await asyncio.to_thread(run)

    async def apply(self, *statements: tuple[str, Iterable[Mapping[str, Any]]]) -> None:
        """Run each statement for every parameter set, all in one transaction."""

        def run() -> None:
            with self._connection:
                for sql, rows in statements:
                    self._connection.executemany(sql, rows)

        async with self._lock:
            await asyncio.to_thread(run)

    def close(self) -> None:
        self._connection.close()


class SQLiteRegistry(CapabilityRegistry):
    """A capability registry stored in a SQLite database."""

    def __init__(self, database: SQLite) -> None:
        self._database = database

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        await self._database.apply(
            (
                "INSERT OR REPLACE INTO capabilities VALUES (:id, :server_id, :type, :document)",
                [
                    {
                        "id": capability.capability_id,
                        "server_id": capability.server_id,
                        "type": str(capability.type),
                        "document": capability_to_json(capability),
                    }
                    for capability in capabilities
                ],
            )
        )

    async def remove(self, capability_id: str) -> None:
        await self._database.fetch("DELETE FROM capabilities WHERE id = :id", {"id": capability_id})

    async def remove_server(self, server_id: str) -> None:
        await self._database.fetch(
            "DELETE FROM capabilities WHERE server_id = :server_id", {"server_id": server_id}
        )

    async def get(self, capability_id: str) -> Capability | None:
        rows = await self._database.fetch(
            "SELECT document FROM capabilities WHERE id = :id", {"id": capability_id}
        )
        return capability_from_json(rows[0][0]) if rows else None

    async def get_many(self, capability_ids: Iterable[str]) -> dict[str, Capability]:
        """Fetch every capability in one query instead of one query per ID."""
        rows = await self._database.fetch(
            "SELECT id, document FROM capabilities WHERE id IN (SELECT value FROM json_each(:ids))",
            {"ids": json.dumps(list(capability_ids))},
        )
        return {row[0]: capability_from_json(row[1]) for row in rows}

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> Sequence[Capability]:
        rows = await self._database.fetch(
            "SELECT document FROM capabilities"
            " WHERE (:server_id IS NULL OR server_id = :server_id)"
            " AND (:type IS NULL OR type = :type) ORDER BY id",
            {"server_id": server_id, "type": None if type is None else str(type)},
        )
        return [capability_from_json(row[0]) for row in rows]


class SQLiteStateStore(StateStore):
    """The fingerprints refresh-engine compares to detect changed capabilities."""

    def __init__(self, database: SQLite) -> None:
        self._database = database

    async def load_all(self) -> Mapping[str, ResourceState]:
        try:
            rows = await self._database.fetch("SELECT * FROM refresh_state")
        except sqlite3.Error as error:
            raise StateStoreError(f"cannot load state: {error}") from error
        states = {}
        for resource_id, document, refreshed_at in rows:
            state = json.loads(document)
            states[resource_id] = ResourceState(
                resource_id,
                ResourceFingerprint(state["algorithm"], state["value"]),
                version=state["version"],
                cheap_indicator=state["cheap_indicator"],
                snapshot_metadata=state["snapshot_metadata"],
                dependencies=frozenset(state["dependencies"]),
                refreshed_at=datetime.fromisoformat(refreshed_at),
            )
        return MappingProxyType(states)

    async def transaction(self) -> StateTransaction:
        return SQLiteTransaction(self._database)


class SQLiteTransaction(StateTransaction):
    """Applies the staged changes of a refresh in one SQLite transaction."""

    def __init__(self, database: SQLite) -> None:
        super().__init__()
        self._database = database

    async def apply_changes(
        self, puts: Mapping[str, ResourceState], deletes: AbstractSet[str], /
    ) -> None:
        rows = [
            {
                "resource_id": state.resource_id,
                "state": json.dumps(
                    {
                        "algorithm": state.fingerprint.algorithm,
                        "value": state.fingerprint.value,
                        "version": state.version,
                        "cheap_indicator": state.cheap_indicator,
                        "snapshot_metadata": dict(state.snapshot_metadata),
                        "dependencies": sorted(state.dependencies),
                    }
                ),
                "refreshed_at": state.refreshed_at.isoformat(),
            }
            for state in puts.values()
        ]
        try:
            await self._database.apply(
                (
                    "DELETE FROM refresh_state WHERE resource_id = :resource_id",
                    [{"resource_id": resource_id} for resource_id in sorted(deletes)],
                ),
                (
                    "INSERT OR REPLACE INTO refresh_state"
                    " VALUES (:resource_id, :state, :refreshed_at)",
                    rows,
                ),
            )
        except sqlite3.Error as error:
            raise StateStoreError(f"cannot commit state: {error}") from error


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "router.db"

        database = SQLite(path)
        policy = RefreshPolicy(state_store=SQLiteStateStore(database))
        async with MCPRuntime(registry=SQLiteRegistry(database)) as runtime:
            await runtime.register_mcp("crm", crm_server(), refresh=policy)
            result = await runtime.refresh_server("crm")
            print(f"first process stored {result.added_count} capabilities")
        database.close()

        database = SQLite(path)
        policy = RefreshPolicy(state_store=SQLiteStateStore(database))
        async with MCPRuntime(registry=SQLiteRegistry(database)) as restarted:
            await restarted.register_mcp("crm", crm_server(), refresh=policy)
            [match] = await restarted.retrieve("change a customer email", limit=1)
            print(f"after a restart, without refreshing: {match.capability_id}")
            assert isinstance(match, Tool)
            print(f"input schema survives: {sorted(match.input_schema['properties'])}")

            result = await restarted.refresh_server("crm")
            print(
                f"a refresh finds {result.unchanged_count} unchanged and "
                f"{result.added_count} new capabilities"
            )
        database.close()


if __name__ == "__main__":
    asyncio.run(main())
