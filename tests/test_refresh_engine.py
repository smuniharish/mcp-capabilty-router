"""Coverage for the refresh_engine-backed refresh subsystem (see refresh.py/runtime.py)."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from refresh_engine import (
    FailurePolicy,
    InMemoryStateStore,
    RefreshConfig,
    RefreshMode,
)

from mcp_capability_router import Capability, MCPRuntime, RefreshPolicy
from mcp_capability_router.errors import RefreshError
from mcp_capability_router.registry import InMemoryRegistry


class RecordingRegistry(InMemoryRegistry):
    """An ``InMemoryRegistry`` that records every upsert/remove call for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.upserted_ids: list[frozenset[str]] = []
        self.removed_ids: list[str] = []
        self.fail_for: set[str] = set()

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        capabilities = list(capabilities)
        for capability in capabilities:
            if capability.capability_id in self.fail_for:
                raise RuntimeError(f"forced failure for {capability.capability_id}")
        self.upserted_ids.append(frozenset(c.capability_id for c in capabilities))
        await super().upsert_many(capabilities)

    async def remove(self, capability_id: str) -> None:
        self.removed_ids.append(capability_id)
        await super().remove(capability_id)


class MutableAdapter:
    """Adapter whose tool list/descriptions/dependencies can change between refreshes."""

    def __init__(self) -> None:
        self.tools: list[dict[str, object]] = [{"name": "base_tool", "description": "v1"}]

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return list(self.tools)

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


class FailingAdapter:
    async def connect(self):
        raise RuntimeError("cannot connect")

    async def close(self):
        pass

    async def list_tools(self):
        raise NotImplementedError

    async def list_resources(self):
        raise NotImplementedError

    async def list_prompts(self):
        raise NotImplementedError

    async def call_tool(self, name, arguments=None):
        raise NotImplementedError

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_incremental_mode_only_touches_changed_capabilities():
    registry = RecordingRegistry()
    adapter = MutableAdapter()
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("srv", lambda: adapter)
        await runtime.refresh_server("srv", mode=RefreshMode.FULL)
        assert registry.upserted_ids == [frozenset({"srv:tool:base_tool"})]

        # Nothing changed: an incremental refresh should not re-upsert unchanged capabilities.
        await runtime.refresh_server("srv", mode=RefreshMode.INCREMENTAL)
        assert registry.upserted_ids == [frozenset({"srv:tool:base_tool"})]

        # A FULL refresh always re-touches everything currently known, changed or not.
        await runtime.refresh_server("srv", mode=RefreshMode.FULL)
        assert len(registry.upserted_ids) == 2

        adapter.tools[0]["description"] = "v2"
        await runtime.refresh_server("srv", mode=RefreshMode.INCREMENTAL)
        assert registry.upserted_ids[-1] == frozenset({"srv:tool:base_tool"})
        assert len(registry.upserted_ids) == 3


@pytest.mark.asyncio
async def test_targeted_mode_requires_resource_ids():
    adapter = MutableAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("srv", lambda: adapter)
        await runtime.refresh_server("srv", mode=RefreshMode.FULL)
        with pytest.raises(ValueError, match="resource_ids"):
            await runtime.refresh_server("srv", mode=RefreshMode.TARGETED)


@pytest.mark.asyncio
async def test_dependency_aware_mode_refreshes_dependents_of_a_changed_capability():
    registry = RecordingRegistry()
    adapter = MutableAdapter()
    adapter.tools.append(
        {
            "name": "derived_tool",
            "description": "derives from base_tool",
            "dependencies": ["srv:tool:base_tool"],
        }
    )
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("srv", lambda: adapter)
        await runtime.refresh_server("srv", mode=RefreshMode.FULL)
        registry.upserted_ids.clear()

        # Only "base_tool" changes, but "derived_tool" depends on it and must be
        # re-refreshed too under DEPENDENCY_AWARE, even though its own content is unchanged.
        adapter.tools[0]["description"] = "v2"
        await runtime.refresh_server("srv", mode=RefreshMode.DEPENDENCY_AWARE)

        refreshed = frozenset().union(*registry.upserted_ids)
        assert refreshed == frozenset({"srv:tool:base_tool", "srv:tool:derived_tool"})


@pytest.mark.asyncio
async def test_refresh_failure_raises_refresh_error_instead_of_swallowing_it():
    async with MCPRuntime() as runtime:
        await runtime.register_server("broken", lambda: FailingAdapter())
        with pytest.raises(RefreshError):
            await runtime.refresh_server("broken")


@pytest.mark.asyncio
async def test_custom_refresh_config_fail_fast_raises_on_partial_failure():
    registry = RecordingRegistry()
    adapter = MutableAdapter()
    adapter.tools.append({"name": "bad_tool", "description": "will fail to persist"})
    registry.fail_for.add("srv:tool:bad_tool")

    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server(
            "srv",
            lambda: adapter,
            refresh=RefreshPolicy(config=RefreshConfig(failure_policy=FailurePolicy.FAIL_FAST)),
        )
        with pytest.raises(RefreshError):
            await runtime.refresh_server("srv")


@pytest.mark.asyncio
async def test_custom_refresh_config_best_effort_default_does_not_raise():
    registry = RecordingRegistry()
    adapter = MutableAdapter()
    adapter.tools.append({"name": "bad_tool", "description": "will fail to persist"})
    registry.fail_for.add("srv:tool:bad_tool")

    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("srv", lambda: adapter)
        # Default FailurePolicy.BEST_EFFORT: one capability failing to persist does not
        # fail the whole refresh -- the other capability still gets stored.
        result = await runtime.refresh_server("srv")
        assert result.failed_count == 1
        assert registry.upserted_ids == [frozenset({"srv:tool:base_tool"})]


@pytest.mark.asyncio
async def test_custom_state_store_is_threaded_through_to_the_refresh_engine():
    adapter = MutableAdapter()
    store = InMemoryStateStore()
    async with MCPRuntime() as runtime:
        await runtime.register_server("srv", lambda: adapter, refresh=RefreshPolicy(store=store))
        assert runtime._refresh_engines["srv"].store is store
        await runtime.refresh_server("srv")
        assert "srv:tool:base_tool" in await store.load_all()
