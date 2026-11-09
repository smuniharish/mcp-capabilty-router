"""Conformance tests for registry, retriever, and result cache implementations.

Subclass a contract in a test module and implement its factory method, and your
test runner collects one test per promise of the contract:

```python
from mcp_capability_router.testing import CapabilityRegistryContract


class TestPostgresRegistry(CapabilityRegistryContract):
    async def make_registry(self):
        registry = PostgresRegistry(dsn)
        await registry.truncate()  # every test starts from an empty registry
        return registry
```

The tests are plain synchronous methods that raise `AssertionError` with a
descriptive message, so they run under pytest, or under unittest when the
subclass also inherits `unittest.TestCase`. Neither pytest nor an async plugin
is required.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from mcp import types

from .contracts import CapabilityRegistry, CapabilityRetriever, MCPAdapter
from .interceptors import ResultCacheStore
from .models import CapabilityType, Prompt, PromptArgument, Resource, Tool, make_capability_id

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from .models import Capability

__all__ = [
    "CapabilityRegistryContract",
    "CapabilityRetrieverContract",
    "MCPAdapterContract",
    "ResultCacheStoreContract",
    "sample_capabilities",
]


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sample_capabilities(server_id: str = "contract") -> list[Capability]:
    """Return a tool, a resource, and a prompt of `server_id` with every field set."""
    return [
        Tool(
            capability_id=make_capability_id(server_id, CapabilityType.TOOL, "search_tickets"),
            server_id=server_id,
            name="search_tickets",
            title="Search tickets",
            description="Search support tickets by keyword.",
            tags=frozenset({"support"}),
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            metadata={"annotations": {"read_only_hint": True}},
        ),
        Resource(
            capability_id=make_capability_id(server_id, CapabilityType.RESOURCE, "docs://handbook"),
            server_id=server_id,
            name="handbook",
            description="The support handbook.",
            uri="docs://handbook",
            mime_type="text/markdown",
        ),
        Prompt(
            capability_id=make_capability_id(server_id, CapabilityType.PROMPT, "triage"),
            server_id=server_id,
            name="triage",
            description="Triage a ticket.",
            arguments=(PromptArgument(name="ticket", required=True),),
        ),
    ]


class _Contract:
    def run_scenario(self, scenario: Coroutine[Any, Any, None]) -> None:
        """Run one scenario to completion; the default is `asyncio.run`."""
        asyncio.run(scenario)


class MCPAdapterContract(_Contract, ABC):
    """Checks adapter lifecycle and MCP listing types against a stable test server.

    Implement `make_adapter` with a fresh adapter. These tests do not invoke
    application tools: test tool arguments, resource contents, and prompt results
    separately against the semantics of your server.
    """

    @abstractmethod
    async def make_adapter(self) -> MCPAdapter:
        """Return a fresh adapter connected to a stable test catalog."""

    def test_connect_close_and_reconnect(self) -> None:
        """Connecting and closing repeatedly is safe, and the adapter can reconnect."""

        async def scenario() -> None:
            adapter = await self.make_adapter()
            _check(isinstance(adapter, MCPAdapter), "adapter does not subclass MCPAdapter")
            try:
                await adapter.connect()
                await adapter.connect()
                before = list(await adapter.list_tools())
                await adapter.close()
                await adapter.close()
                await adapter.connect()
                _check(list(await adapter.list_tools()) == before, "reconnect changed the catalog")
            finally:
                await adapter.close()

        self.run_scenario(scenario())

    def test_listings_use_mcp_types_and_unique_identifiers(self) -> None:
        """Listings use SDK records and do not duplicate names or resource URIs."""

        async def scenario() -> None:
            adapter = await self.make_adapter()
            _check(isinstance(adapter, MCPAdapter), "adapter does not subclass MCPAdapter")
            try:
                await adapter.connect()
                tools, resources, prompts = await asyncio.gather(
                    adapter.list_tools(), adapter.list_resources(), adapter.list_prompts()
                )
                _check(all(isinstance(item, types.Tool) for item in tools), "invalid tool listing")
                _check(
                    all(isinstance(item, types.Resource) for item in resources),
                    "invalid resource listing",
                )
                _check(
                    all(isinstance(item, types.Prompt) for item in prompts),
                    "invalid prompt listing",
                )
                for identifiers in (
                    [item.name for item in tools],
                    [item.uri for item in resources],
                    [item.name for item in prompts],
                ):
                    _check(
                        len(identifiers) == len(set(identifiers)), "duplicate listing identifiers"
                    )
            finally:
                await adapter.close()

        self.run_scenario(scenario())


class CapabilityRegistryContract(_Contract, ABC):
    """Tests every promise a `CapabilityRegistry` makes to the runtime.

    Each test calls `make_registry` for a new, empty registry, runs one scenario
    on it, and closes it. Override `run_scenario` to run scenarios on a specific
    event loop.
    """

    @abstractmethod
    async def make_registry(self) -> CapabilityRegistry:
        """Return a new, empty, ready-to-use registry."""

    def _run(self, scenario: Any) -> None:
        async def run() -> None:
            registry = await self.make_registry()
            _check(
                isinstance(registry, CapabilityRegistry),
                f"{registry!r} does not subclass CapabilityRegistry",
            )
            try:
                await scenario(registry)
            finally:
                await registry.close()

        self.run_scenario(run())

    def test_round_trips_every_capability_type(self) -> None:
        """A stored capability is returned equal to what was stored."""

        async def scenario(registry: CapabilityRegistry) -> None:
            capabilities = sample_capabilities()
            await registry.upsert_many(capabilities)
            for capability in capabilities:
                stored = await registry.get(capability.capability_id)
                _check(stored == capability, f"get returned {stored!r}, not {capability!r}")

        self._run(scenario)

    def test_upsert_replaces_by_capability_id(self) -> None:
        """Upserting a capability with a stored ID replaces it."""

        async def scenario(registry: CapabilityRegistry) -> None:
            tool = sample_capabilities()[0]
            assert isinstance(tool, Tool)
            changed = Tool(
                capability_id=tool.capability_id,
                server_id=tool.server_id,
                name=tool.name,
                description="Changed.",
                input_schema=tool.input_schema,
            )
            await registry.upsert_many([tool])
            await registry.upsert_many([changed])
            stored = await registry.get(tool.capability_id)
            _check(stored == changed, f"upsert kept {stored!r}")
            listed = await registry.list()
            _check(len(listed) == 1, f"upsert duplicated the capability: {listed!r}")

        self._run(scenario)

    def test_get_of_unknown_id_returns_none(self) -> None:
        """Getting an ID that is not stored returns `None`."""

        async def scenario(registry: CapabilityRegistry) -> None:
            _check(await registry.get("missing:tool:x") is None, "get invented a capability")

        self._run(scenario)

    def test_get_many_returns_only_stored_ids(self) -> None:
        """`get_many` maps each stored ID to its capability and skips the others."""

        async def scenario(registry: CapabilityRegistry) -> None:
            capabilities = sample_capabilities()
            await registry.upsert_many(capabilities)
            ids = [capabilities[0].capability_id, "missing:tool:x", capabilities[2].capability_id]
            found = await registry.get_many(ids)
            expected = {c.capability_id: c for c in (capabilities[0], capabilities[2])}
            _check(found == expected, f"get_many returned {found!r}")

        self._run(scenario)

    def test_list_filters_by_server_and_type(self) -> None:
        """`list` returns every capability, or those of one server or type."""

        async def scenario(registry: CapabilityRegistry) -> None:
            first, second = sample_capabilities("first"), sample_capabilities("second")
            await registry.upsert_many([*first, *second])
            everything = {c.capability_id for c in await registry.list()}
            _check(
                everything == {c.capability_id for c in [*first, *second]},
                f"list returned {sorted(everything)}",
            )
            of_first = {c.capability_id for c in await registry.list(server_id="first")}
            _check(
                of_first == {c.capability_id for c in first},
                f"list(server_id=...) returned {sorted(of_first)}",
            )
            tools = await registry.list(type=CapabilityType.TOOL)
            _check(
                {c.capability_id for c in tools}
                == {first[0].capability_id, second[0].capability_id},
                f"list(type=TOOL) returned {tools!r}",
            )
            narrow = await registry.list(server_id="second", type=CapabilityType.PROMPT)
            _check(list(narrow) == [second[2]], f"list(server_id, type) returned {narrow!r}")

        self._run(scenario)

    def test_remove_and_remove_server(self) -> None:
        """`remove` drops one capability; `remove_server` drops a whole server."""

        async def scenario(registry: CapabilityRegistry) -> None:
            first, second = sample_capabilities("first"), sample_capabilities("second")
            await registry.upsert_many([*first, *second])
            await registry.remove(first[0].capability_id)
            await registry.remove("missing:tool:x")
            _check(
                await registry.get(first[0].capability_id) is None,
                "remove kept the capability",
            )
            await registry.remove_server("second")
            remaining = {c.capability_id for c in await registry.list()}
            _check(
                remaining == {c.capability_id for c in first[1:]},
                f"remove_server left {sorted(remaining)}",
            )

        self._run(scenario)


class CapabilityRetrieverContract(_Contract, ABC):
    """Tests every promise a `CapabilityRetriever` makes to the runtime."""

    @abstractmethod
    async def make_retriever(self) -> CapabilityRetriever:
        """Return a new, ready-to-use retriever."""

    def _run(self, scenario: Any) -> None:
        async def run() -> None:
            retriever = await self.make_retriever()
            _check(
                isinstance(retriever, CapabilityRetriever),
                f"{retriever!r} does not subclass CapabilityRetriever",
            )
            await scenario(retriever)

        self.run_scenario(run())

    def test_returns_only_candidates_within_the_limit(self) -> None:
        """Results are distinct candidates, at most `limit` of them."""

        async def scenario(retriever: CapabilityRetriever) -> None:
            candidates = sample_capabilities("first") + sample_capabilities("second")
            for limit in (1, 2, len(candidates) + 5):
                results = await retriever.retrieve("search tickets", candidates, limit=limit)
                ids = [c.capability_id for c in results]
                _check(len(ids) <= limit, f"returned {len(ids)} results for limit {limit}")
                _check(len(set(ids)) == len(ids), f"returned duplicates: {ids}")
                _check(
                    all(c in candidates for c in results),
                    f"returned capabilities that are not candidates: {results!r}",
                )

        self._run(scenario)

    def test_no_candidates_returns_nothing(self) -> None:
        """Without candidates, the result is empty."""

        async def scenario(retriever: CapabilityRetriever) -> None:
            results = await retriever.retrieve("search tickets", [], limit=5)
            _check(results == [], f"returned {results!r} without candidates")

        self._run(scenario)


class ResultCacheStoreContract(_Contract, ABC):
    """Tests every promise a `ResultCacheStore` makes to `ToolResultCache`."""

    @abstractmethod
    async def make_store(self) -> ResultCacheStore:
        """Return a new, empty, ready-to-use store."""

    def _run(self, scenario: Any) -> None:
        async def run() -> None:
            store = await self.make_store()
            _check(
                isinstance(store, ResultCacheStore),
                f"{store!r} does not subclass ResultCacheStore",
            )
            try:
                await scenario(store)
            finally:
                await store.close()

        self.run_scenario(run())

    def test_set_then_get(self) -> None:
        """A stored value is returned until it expires; unknown keys return `None`."""

        async def scenario(store: ResultCacheStore) -> None:
            await store.set("server:key", {"value": 1}, 60.0)
            _check(await store.get("server:key") == {"value": 1}, "get lost the value")
            _check(await store.get("server:missing") is None, "get invented a value")

        self._run(scenario)

    def test_expired_values_are_not_returned(self) -> None:
        """A value is not returned after its TTL."""

        async def scenario(store: ResultCacheStore) -> None:
            await store.set("server:key", "value", 0.05)
            await asyncio.sleep(0.2)
            _check(await store.get("server:key") is None, "get returned an expired value")

        self._run(scenario)

    def test_clear_by_prefix(self) -> None:
        """`clear` removes the keys with the prefix, or every key without one."""

        async def scenario(store: ResultCacheStore) -> None:
            await store.set("first:a", 1, 60.0)
            await store.set("second:a", 2, 60.0)
            await store.clear("first:")
            _check(await store.get("first:a") is None, "clear(prefix) kept a key")
            _check(await store.get("second:a") == 2, "clear(prefix) removed another key")
            await store.clear()
            _check(await store.get("second:a") is None, "clear() kept a key")

        self._run(scenario)
