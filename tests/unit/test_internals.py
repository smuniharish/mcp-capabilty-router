from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from mcp import types
from refresh_engine import (
    InMemoryMetrics,
    PlanAction,
    RefreshRequest,
    Resource,
    ResourceSnapshot,
)

from mcp_capability_router import (
    ConfigurationError,
    DiscoveryError,
    InMemoryRegistry,
    PromptArgument,
    ServerNotFoundError,
    Tool,
)
from mcp_capability_router import (
    Resource as ResourceCapability,
)
from mcp_capability_router._internal.concurrency import gather_or_cancel
from mcp_capability_router._internal.discovery import discover_capabilities
from mcp_capability_router._internal.metrics import ServerScopedSink, increment, observe
from mcp_capability_router._internal.servers import ServerHandle
from mcp_capability_router._internal.sources import CapabilitySource, RegistryOperation
from tests.support import FakeAdapter, mcp_prompt, mcp_resource, mcp_tool, tool


class TestDiscovery:
    async def test_maps_tools_resources_and_prompts(self) -> None:
        adapter = FakeAdapter(
            tools=[
                mcp_tool(
                    "read_file",
                    "Read a file",
                    annotations=types.ToolAnnotations(
                        title="Reader", read_only_hint=True
                    ),
                    output_schema={"type": "object"},
                    meta={"fastmcp": {"tags": ["fs", "read"]}, "depends_on": ["x:y:z"]},
                ),
                mcp_tool("titled", title="Explicit"),
            ],
            resources=[
                mcp_resource(
                    "file:///notes.md",
                    "notes",
                    "My notes",
                    mime_type="text/markdown",
                    annotations=types.Annotations(priority=0.5),
                )
            ],
            prompts=[
                mcp_prompt(
                    "plan",
                    "Plan a change",
                    arguments=[
                        types.PromptArgument(name="goal", required=True),
                        types.PromptArgument(name="style", description="Tone"),
                    ],
                )
            ],
        )
        capabilities = {
            c.capability_id: c for c in await discover_capabilities(adapter, "s")
        }

        reader = capabilities["s:tool:read_file"]
        assert isinstance(reader, Tool)
        assert reader.title == "Reader"
        assert reader.description == "Read a file"
        assert reader.tags == frozenset({"fs", "read"})
        assert reader.depends_on == frozenset({"x:y:z"})
        assert reader.metadata["annotations"] == {
            "title": "Reader",
            "read_only_hint": True,
        }
        assert reader.metadata["meta"]["fastmcp"] == {"tags": ["fs", "read"]}
        assert reader.output_schema == {"type": "object"}
        assert capabilities["s:tool:titled"].title == "Explicit"
        assert capabilities["s:tool:titled"].metadata == {}

        notes = capabilities["s:resource:file:///notes.md"]
        assert isinstance(notes, ResourceCapability)
        assert (notes.uri, notes.mime_type, notes.name) == (
            "file:///notes.md",
            "text/markdown",
            "notes",
        )
        assert notes.metadata == {"annotations": {"priority": 0.5}}

        plan = capabilities["s:prompt:plan"]
        assert plan.arguments == (  # type: ignore[attr-defined]
            PromptArgument(name="goal", required=True),
            PromptArgument(name="style", description="Tone"),
        )

    async def test_rejects_duplicates_and_foreign_types(self) -> None:
        duplicated = FakeAdapter(tools=[mcp_tool("x"), mcp_tool("x")])
        with pytest.raises(DiscoveryError, match="more than once"):
            await discover_capabilities(duplicated, "s")
        foreign = FakeAdapter()
        foreign.tools = [{"name": "x"}]  # type: ignore[list-item]
        with pytest.raises(DiscoveryError, match=r"expected mcp\.types\.Tool"):
            await discover_capabilities(foreign, "s")

    @pytest.mark.parametrize("value", ["x:y:z", 42])
    async def test_rejects_malformed_dependencies(self, value: object) -> None:
        adapter = FakeAdapter(tools=[mcp_tool("x", meta={"depends_on": value})])
        with pytest.raises(DiscoveryError, match="depends_on"):
            await discover_capabilities(adapter, "s")

    @pytest.mark.parametrize("meta", [{"fastmcp": "tags"}, {"fastmcp": {"tags": "fs"}}])
    async def test_ignores_malformed_tags(self, meta: dict[str, object]) -> None:
        adapter = FakeAdapter(tools=[mcp_tool("x", meta=meta)])
        [capability] = await discover_capabilities(adapter, "s")
        assert capability.tags == frozenset()


class TestGatherOrCancel:
    async def test_returns_results_in_order(self) -> None:
        async def value(item: int) -> int:
            await asyncio.sleep(0)
            return item

        assert await gather_or_cancel(value(1), value(2)) == [1, 2]

    async def test_cancels_the_others_when_one_fails(self) -> None:
        cancelled = asyncio.Event()

        async def slow() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def fail() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await gather_or_cancel(slow(), fail())
        assert cancelled.is_set()


class TestMetrics:
    def test_none_sink_is_ignored_and_failures_are_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        increment(None, "x", 1, {})
        observe(None, "x", 1.0, {})

        class Broken:
            def increment(self, *args: object) -> None:
                raise RuntimeError("down")

            def observe(self, *args: object) -> None:
                raise RuntimeError("down")

        with caplog.at_level(logging.ERROR, logger="mcp_capability_router"):
            increment(Broken(), "x", 1, {})
            observe(Broken(), "y", 1.0, {})
        assert [record.getMessage() for record in caplog.records] == [
            "Metrics sink failed to record x",
            "Metrics sink failed to record y",
        ]

    def test_server_scoped_sink_adds_the_server(self) -> None:
        sink = InMemoryMetrics()
        scoped = ServerScopedSink(sink, "fs")
        scoped.increment("refreshes")
        scoped.increment("refreshes", 2, {"status": "success"})
        scoped.observe("duration", 0.5)
        counters, observations = sink.snapshot()
        assert counters == {
            "refreshes{server_id=fs}": 1,
            "refreshes{server_id=fs,status=success}": 2,
        }
        assert observations == {"duration{server_id=fs}": (0.5,)}


class TestServerHandle:
    async def test_connects_lazily_once_and_reconnects(self) -> None:
        adapters: list[FakeAdapter] = []

        def factory() -> FakeAdapter:
            adapters.append(FakeAdapter())
            adapters[-1].delay = 0.01
            return adapters[-1]

        handle = ServerHandle("s", factory)
        assert adapters == []
        first, second = await asyncio.gather(handle.adapter(), handle.adapter())
        assert first is second is adapters[0]
        assert adapters[0].connects == 1
        await handle.connect()
        assert len(adapters) == 1
        await handle.reconnect()
        assert adapters[0].closes == 1
        assert await handle.adapter() is adapters[1]
        await handle.close()
        await handle.close()
        assert adapters[1].closes == 1
        with pytest.raises(ServerNotFoundError, match="server 's' is closed"):
            await handle.adapter()
        with pytest.raises(ServerNotFoundError, match="server 's' is closed"):
            await handle.reconnect()
        assert len(adapters) == 2

    async def test_discard_only_closes_the_current_adapter(self) -> None:
        adapters: list[FakeAdapter] = []

        def factory() -> FakeAdapter:
            adapters.append(FakeAdapter())
            return adapters[-1]

        handle = ServerHandle("s", factory)
        stale = await handle.adapter()
        await handle.reconnect()
        await handle.discard(stale)
        assert adapters[1].closes == 0
        assert await handle.adapter() is adapters[1]
        await handle.discard(adapters[1])
        assert adapters[1].closes == 1
        assert await handle.adapter() is adapters[2]

    async def test_rejects_factories_that_return_no_adapter(self) -> None:
        handle = ServerHandle("s", lambda: object())  # type: ignore[arg-type,return-value]
        with pytest.raises(ConfigurationError, match="does not implement MCPAdapter"):
            await handle.adapter()


class TestSources:
    async def test_discover_and_snapshot(self) -> None:
        capabilities = [tool("s", "a", tags=frozenset({"x", "w"})), tool("s", "b")]
        capabilities.append(tool("s", "c", depends_on=frozenset({"s:tool:a"})))
        pruned: list[frozenset[str]] = []

        async def discover() -> list:
            return capabilities

        async def prune(discovered: frozenset[str]) -> None:
            pruned.append(discovered)

        source = CapabilitySource(discover, prune)
        result = await source.discover()
        await source.discover()
        assert pruned == [frozenset({"s:tool:a", "s:tool:b", "s:tool:c"})]
        resources = list(result.resources)  # type: ignore[arg-type]
        assert [resource.resource_id for resource in resources] == [
            "s:tool:a",
            "s:tool:b",
            "s:tool:c",
        ]
        assert resources[0].metadata["tags"] == ("w", "x")
        assert resources[0].metadata["type"] == "tool"
        assert resources[0].dependencies is None
        assert resources[2].dependencies == frozenset({"s:tool:a"})
        snapshot = await source.snapshot(resources[0])
        assert snapshot.content is capabilities[0]
        assert source.take_error() is None

    async def test_remembers_the_last_discovery_error(self) -> None:
        async def discover() -> list:
            raise ValueError("down")

        async def prune(discovered: frozenset[str]) -> None:
            raise AssertionError

        source = CapabilitySource(discover, prune)
        with pytest.raises(ValueError, match="down"):
            await source.discover()
        error = source.take_error()
        assert isinstance(error, ValueError)
        assert source.take_error() is None

    async def test_retries_pruning_until_it_succeeds(self) -> None:
        attempts: list[frozenset[str]] = []

        async def discover() -> list:
            return [tool("s", "a")]

        async def prune(discovered: frozenset[str]) -> None:
            attempts.append(discovered)
            if len(attempts) == 1:
                raise OSError("registry unavailable")

        source = CapabilitySource(discover, prune)
        with pytest.raises(OSError, match="registry unavailable"):
            await source.discover()
        assert isinstance(source.take_error(), OSError)
        await source.discover()
        await source.discover()
        assert len(attempts) == 2

    async def test_registry_operation_applies_plans(self) -> None:
        registry = InMemoryRegistry()
        operation = RegistryOperation(registry)
        capability = tool("s", "a")
        resource = Resource("s:tool:a")
        request = RefreshRequest(requested_at=datetime.now(UTC))
        await operation(
            resource,
            ResourceSnapshot("s:tool:a", content=capability),
            PlanAction.REFRESH,
            request,
        )
        assert await registry.get("s:tool:a") is capability
        await operation(resource, None, PlanAction.DELETE, request)
        assert await registry.get("s:tool:a") is None
        with pytest.raises(RuntimeError, match="no snapshot"):
            await operation(resource, None, PlanAction.REFRESH, request)
