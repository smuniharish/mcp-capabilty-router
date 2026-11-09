"""Application-owned registry template; replace the dictionary with async storage."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mcp_capability_router import Capability, CapabilityRegistry, CapabilityType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class TableRegistry(CapabilityRegistry):
    """A complete in-memory reference for the registry's observable behavior."""

    def __init__(self) -> None:
        self._rows: dict[str, Capability] = {}

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        self._rows.update((item.capability_id, item) for item in capabilities)

    async def remove(self, capability_id: str) -> None:
        self._rows.pop(capability_id, None)

    async def remove_server(self, server_id: str) -> None:
        self._rows = {
            key: value for key, value in self._rows.items() if value.server_id != server_id
        }

    async def get(self, capability_id: str) -> Capability | None:
        return self._rows.get(capability_id)

    async def get_many(self, capability_ids: Iterable[str]) -> dict[str, Capability]:
        return {key: self._rows[key] for key in capability_ids if key in self._rows}

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> Sequence[Capability]:
        return [
            item
            for item in self._rows.values()
            if (server_id is None or item.server_id == server_id)
            and (type is None or item.type is type)
        ]


async def main() -> None:
    registry = TableRegistry()
    assert await registry.list() == []
    await registry.close()
    print("Registry ready.")


if __name__ == "__main__":
    asyncio.run(main())
