from __future__ import annotations

import asyncio
from collections.abc import Iterable

import pytest

from mcp_capability_router import Capability, CapabilityType, MCPRuntime, Tool

CapabilityList = list[Capability]


class TagIndexedRegistry:
    """A custom CapabilityRegistry implementing the package protocol from scratch.

    In addition to the required contract (upsert_many/remove_missing/remove/get/list/close)
    it maintains a secondary tag index, showing that applications can extend the
    registry with their own indexing strategy while remaining a drop-in for
    ``MCPRuntime(registry=...)``.
    """

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}
        self._by_tag: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self.upsert_calls = 0

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        async with self._lock:
            self.upsert_calls += 1
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


@pytest.mark.asyncio
async def test_custom_registry_plugs_into_runtime_end_to_end():
    registry = TagIndexedRegistry()
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("custom", lambda: None)
        capabilities = [
            Tool(
                capability_id="custom:tool:billing_search",
                server_id="custom",
                name="billing_search",
                description="search billing records",
                tags=frozenset({"finance"}),
            ),
            Tool(
                capability_id="custom:tool:hr_search",
                server_id="custom",
                name="hr_search",
                description="search hr records",
                tags=frozenset({"people"}),
            ),
        ]
        await runtime.registry.upsert_many(capabilities)

        assert runtime.registry is registry
        assert registry.upsert_calls == 1

        finance_matches = await registry.list_by_tag("finance")
        assert [c.capability_id for c in finance_matches] == ["custom:tool:billing_search"]

        retrieved = await runtime.retrieve("billing")
        assert len(retrieved) == 1
        assert retrieved[0].capability_id == "custom:tool:billing_search"


@pytest.mark.asyncio
async def test_custom_registry_supports_reconciliation_on_refresh():
    registry = TagIndexedRegistry()

    class ShrinkingAdapter:
        def __init__(self):
            self.names = ["a", "b"]

        async def connect(self):
            pass

        async def close(self):
            pass

        async def list_tools(self):
            return [{"name": name, "description": "tool"} for name in self.names]

        async def list_resources(self):
            return []

        async def list_prompts(self):
            return []

        async def call_tool(self, name, arguments=None):
            return name

        async def read_resource(self, uri):
            raise NotImplementedError

        async def get_prompt(self, name, arguments=None):
            raise NotImplementedError

    adapter = ShrinkingAdapter()
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("shrink", lambda: adapter)
        await runtime.refresh_server("shrink")
        assert len(await registry.list(server_id="shrink")) == 2

        adapter.names = ["a"]
        await runtime.refresh_server("shrink")
        remaining = await registry.list(server_id="shrink")
        assert [c.name for c in remaining] == ["a"]
