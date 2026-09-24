"""Custom CapabilityRegistry example.

Run:
    uv run python -m examples.custom_registry

This example is credential-free. It implements the ``CapabilityRegistry`` protocol
from scratch -- via structural typing only, no inheritance -- with a secondary tag index,
and plugs it into ``MCPRuntime`` via the ``registry=`` constructor argument. Both styles
work equally well with ``MCPRuntime``; pick whichever fits a project's conventions. See
``examples/postgres_registry.py`` for the same protocol implemented by subclassing the
optional ``CapabilityRegistryBase`` abstract base class instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from mcp_capability_router import Capability, CapabilityType, MCPRuntime, Tool

CapabilityList = list[Capability]


class TagIndexedRegistry:
    """A minimal application-owned registry with an extra tag index."""

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}
        self._by_tag: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        async with self._lock:
            for capability in capabilities:
                self._items[capability.capability_id] = capability
                for tag in capability.tags:
                    self._by_tag.setdefault(tag, set()).add(capability.capability_id)

    async def remove_missing(self, server_id: str, current_ids: set[str]) -> None:
        async with self._lock:
            stale = [
                key
                for key, value in self._items.items()
                if value.server_id == server_id and key not in current_ids
            ]
            for key in stale:
                del self._items[key]
                for ids in self._by_tag.values():
                    ids.discard(key)

    async def remove(self, capability_id: str) -> None:
        async with self._lock:
            self._items.pop(capability_id, None)
            for ids in self._by_tag.values():
                ids.discard(capability_id)

    async def get(self, capability_id: str) -> Capability | None:
        async with self._lock:
            return self._items.get(capability_id)

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> CapabilityList:
        async with self._lock:
            return [
                value
                for value in self._items.values()
                if (server_id is None or value.server_id == server_id)
                and (type is None or value.type == type)
            ]

    async def list_by_tag(self, tag: str) -> CapabilityList:
        async with self._lock:
            return [self._items[cid] for cid in self._by_tag.get(tag, ()) if cid in self._items]

    async def close(self) -> None:
        self._items.clear()
        self._by_tag.clear()


class FinanceAdapter:
    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "billing_search", "description": "search billing records"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    registry = TagIndexedRegistry()
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("finance", lambda: FinanceAdapter())
        await runtime.refresh_server("finance")

        # Discovery does not populate tags; applications label capabilities with
        # their own taxonomy after discovery (or via a custom discovery step).
        capability = (await runtime.retrieve("billing"))[0]
        tagged = Tool(
            capability_id=capability.capability_id,
            server_id=capability.server_id,
            name=capability.name,
            description=capability.description,
            tags=frozenset({"finance"}),
        )
        await registry.upsert_many([tagged])

        finance_capabilities = await registry.list_by_tag("finance")
        print("tagged as finance:", [c.name for c in finance_capabilities])


if __name__ == "__main__":
    asyncio.run(main())
