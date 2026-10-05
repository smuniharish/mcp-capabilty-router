from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from mcp import types
from purgatory import AsyncCircuitBreakerFactory
from refresh_engine import RefreshMode, RefreshStatus, TriggerSource

from mcp_capability_router import (
    Capability,
    CapabilityNotFoundError,
    CapabilityTypeError,
    ConfigurationError,
    HealthState,
    InMemoryRegistry,
    InvalidRequestError,
    KeywordRetriever,
    MCPRuntime,
    RefreshError,
    RefreshPolicy,
    RuntimeClosedError,
    ServerConnectionError,
    ServerNotFoundError,
)
from tests.support import (
    FakeAdapter,
    capability_ids,
    mcp_prompt,
    mcp_resource,
    mcp_tool,
    tool,
)


def catalog() -> FakeAdapter:
    return FakeAdapter(
        tools=[
            mcp_tool("search", "Search records"),
            mcp_tool("delete", "Delete a record"),
        ],
        resources=[mcp_resource("file:///guide.md", "guide", "User guide")],
        prompts=[
            mcp_prompt(
                "summarize",
                "Summarize text",
                arguments=[types.PromptArgument(name="text", required=True)],
            )
        ],
    )


class Factory:
    """Creates adapters on demand and remembers them."""

    def __init__(self, make: type[FakeAdapter] | None = None) -> None:
        self.adapters: list[FakeAdapter] = []
        self._make = make or catalog

    def __call__(self) -> FakeAdapter:
        self.adapters.append(self._make())
        return self.adapters[-1]


@pytest.fixture
async def runtime() -> AsyncIterator[MCPRuntime]:
    async with MCPRuntime() as instance:
        yield instance


class TestConstruction:
    @pytest.mark.parametrize("argument", ["registry", "retriever", "metrics"])
    def test_rejects_objects_without_the_contract(self, argument: str) -> None:
        with pytest.raises(ConfigurationError, match="does not implement"):
            MCPRuntime(**{argument: object()})  # type: ignore[arg-type]

    async def test_defaults_and_custom_collaborators(self) -> None:
        async with MCPRuntime() as default:
            assert isinstance(default.registry, InMemoryRegistry)
            assert isinstance(default.retriever, KeywordRetriever)
            assert default.servers == ()
            assert not default.closed
        assert default.closed
        registry, retriever = InMemoryRegistry(), KeywordRetriever()
        async with MCPRuntime(registry=registry, retriever=retriever) as custom:
            assert custom.registry is registry
            assert custom.retriever is retriever


class TestRegistration:
    async def test_registration_is_lazy(self, runtime: MCPRuntime) -> None:
        factory = Factory()
        await runtime.register_server("crm", factory)
        assert runtime.servers == ("crm",)
        assert factory.adapters == []
        assert await runtime.registry.list() == []

    async def test_rejects_invalid_registrations(self, runtime: MCPRuntime) -> None:
        with pytest.raises(ConfigurationError, match="invalid server ID"):
            await runtime.register_server("bad id", Factory())
        with pytest.raises(ConfigurationError, match="not callable"):
            await runtime.register_server("crm", object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="RefreshPolicy"):
            await runtime.register_server("crm", Factory(), refresh=object())  # type: ignore[arg-type]
        await runtime.register_server("crm", Factory())
        with pytest.raises(ConfigurationError, match="already registered"):
            await runtime.register_server("crm", Factory())

    async def test_refresh_on_register(self, runtime: MCPRuntime) -> None:
        await runtime.register_server(
            "crm", Factory(), refresh=RefreshPolicy(on_register=True)
        )
        assert len(await runtime.registry.list()) == 4

    async def test_failed_refresh_on_register_undoes_the_registration(
        self, runtime: MCPRuntime
    ) -> None:
        def broken() -> FakeAdapter:
            adapter = catalog()
            adapter.failures["list_tools"] = [ServerConnectionError("down")]
            return adapter

        with pytest.raises(RefreshError) as raised:
            await runtime.register_server(
                "crm", broken, refresh=RefreshPolicy(on_register=True)
            )
        assert isinstance(raised.value.__cause__, ServerConnectionError)
        assert raised.value.result.status is RefreshStatus.FAILED
        assert runtime.servers == ()
        await runtime.register_server("crm", Factory())

    async def test_cleanup_failures_are_logged_without_hiding_the_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class StickyRegistry(InMemoryRegistry):
            async def remove_server(self, server_id: str) -> None:
                raise OSError("disk full")

        def broken() -> FakeAdapter:
            adapter = catalog()
            adapter.failures["list_tools"] = [ServerConnectionError("down")]
            return adapter

        async with MCPRuntime(registry=StickyRegistry()) as runtime:
            with (
                caplog.at_level(logging.ERROR, logger="mcp_capability_router"),
                pytest.raises(RefreshError),
            ):
                await runtime.register_server(
                    "crm", broken, refresh=RefreshPolicy(on_register=True)
                )
        assert "failed registration of server 'crm'" in caplog.text

    async def test_unregister_forgets_capabilities_and_closes(
        self, runtime: MCPRuntime
    ) -> None:
        factory = Factory()
        await runtime.register_server("crm", factory)
        await runtime.refresh_server("crm")
        await runtime.unregister_server("crm")
        assert runtime.servers == ()
        assert await runtime.registry.list() == []
        assert factory.adapters[0].closes == 1
        with pytest.raises(ServerNotFoundError):
            await runtime.unregister_server("crm")

    async def test_connect_and_reconnect(self, runtime: MCPRuntime) -> None:
        factory = Factory()
        await runtime.register_server("crm", factory)
        await runtime.connect("crm")
        await runtime.connect("crm")
        assert len(factory.adapters) == 1
        await runtime.reconnect("crm")
        assert len(factory.adapters) == 2
        assert factory.adapters[0].closes == 1
        with pytest.raises(ServerNotFoundError):
            await runtime.connect("other")


class TestRefresh:
    async def test_refresh_server_reconciles_the_registry(
        self, runtime: MCPRuntime
    ) -> None:
        factory = Factory()
        await runtime.register_server("crm", factory)
        result = await runtime.refresh_server("crm")
        assert (result.status, result.added_count) == (RefreshStatus.SUCCESS, 4)
        assert result.request.trigger is TriggerSource.MANUAL
        adapter = factory.adapters[0]
        adapter.tools = [mcp_tool("search", "Search records and files")]
        result = await runtime.refresh_server("crm", mode=RefreshMode.FULL)
        assert (result.modified_count, result.deleted_count) == (1, 1)
        assert "crm:tool:delete" not in capability_ids(await runtime.registry.list())

    async def test_targeted_refreshes(self, runtime: MCPRuntime) -> None:
        from refresh_engine import TagSelector

        await runtime.register_server("crm", Factory())
        result = await runtime.refresh_server("crm", resource_ids=["crm:tool:search"])
        assert (result.request.mode, result.refreshed_count) == (
            RefreshMode.TARGETED,
            1,
        )
        result = await runtime.refresh_server(
            "crm", selector=TagSelector("tool", key="type")
        )
        assert result.refreshed_count == 2
        with pytest.raises(ConfigurationError):
            await runtime.refresh_server("crm", mode=RefreshMode.TARGETED)

    async def test_failed_discovery_raises_with_its_cause(
        self, runtime: MCPRuntime
    ) -> None:
        factory = Factory()
        await runtime.register_server("crm", factory)
        await runtime.connect("crm")
        factory.adapters[0].failures["list_prompts"] = [ValueError("listing failed")]
        with pytest.raises(
            RefreshError, match="refresh of server 'crm' failed"
        ) as raised:
            await runtime.refresh_server("crm")
        assert isinstance(raised.value.__cause__, ValueError)

    async def test_refresh_all_servers(self, runtime: MCPRuntime) -> None:
        await runtime.register_server("a", Factory())
        await runtime.register_server("b", Factory())
        results = await runtime.refresh()
        assert sorted(results) == ["a", "b"]
        assert all(
            result.status is RefreshStatus.SUCCESS for result in results.values()
        )

        def broken() -> FakeAdapter:
            adapter = catalog()
            adapter.failures["list_tools"] = [ServerConnectionError("down")]
            return adapter

        await runtime.register_server("c", broken)
        with pytest.raises(ExceptionGroup) as raised:
            await runtime.refresh()
        assert [type(error) for error in raised.value.exceptions] == [RefreshError]

    async def test_refresh_all_propagates_base_exceptions(
        self, runtime: MCPRuntime
    ) -> None:
        class Abort(BaseException):
            pass

        def aborting() -> FakeAdapter:
            adapter = catalog()
            adapter.failures["list_tools"] = [Abort()]
            return adapter

        await runtime.register_server("a", aborting)
        with pytest.raises(Abort):
            await runtime.refresh()

    async def test_refresh_of_a_closed_engine(self, runtime: MCPRuntime) -> None:
        await runtime.register_server("crm", Factory())
        server = runtime._servers["crm"]
        await server.engine.close()
        with pytest.raises(
            ServerNotFoundError, match="unregistered during the refresh"
        ):
            await runtime.refresh_server("crm")
        await runtime.close()
        with pytest.raises(RuntimeClosedError):
            await runtime._refresh(server, mode=None, trigger=TriggerSource.MANUAL)


class TestRetrieval:
    async def test_retrieve_filters_and_validates(self, runtime: MCPRuntime) -> None:
        await runtime.register_server(
            "crm", Factory(), refresh=RefreshPolicy(on_register=True)
        )
        assert capability_ids(await runtime.retrieve("search records", limit=1)) == [
            "crm:tool:search"
        ]
        assert capability_ids(await runtime.retrieve("guide", type="resource")) == [  # type: ignore[arg-type]
            "crm:resource:file:///guide.md"
        ]
        assert await runtime.retrieve("guide", type="prompt") == []  # type: ignore[arg-type]
        with pytest.raises(ServerNotFoundError):
            await runtime.retrieve("x", server_id="other")
        with pytest.raises(ConfigurationError):
            await runtime.retrieve("x", limit=0)

    async def test_query_returns_matches_without_refreshing(
        self, runtime: MCPRuntime
    ) -> None:
        factory = Factory()
        await runtime.register_server(
            "crm", factory, refresh=RefreshPolicy(on_register=True, on_query_miss=True)
        )
        calls = len(factory.adapters[0].calls)
        assert capability_ids(await runtime.query("search", limit=1)) == [
            "crm:tool:search"
        ]
        assert len(factory.adapters[0].calls) == calls

    async def test_query_refreshes_policy_and_hinted_servers_on_a_miss(
        self, runtime: MCPRuntime
    ) -> None:
        await runtime.register_server(
            "a", Factory(), refresh=RefreshPolicy(on_query_miss=True)
        )
        await runtime.register_server("b", Factory())
        found = await runtime.query("search", limit=5)
        assert capability_ids(found) == ["a:tool:search"]
        found = await runtime.query("delete", server_id="b", refresh_servers=["b"])
        assert capability_ids(found) == ["b:tool:delete"]
        assert await runtime.query("nothing matches", server_id="a") == []
        await runtime.register_server("c", Factory())
        assert await runtime.query("search", server_id="c") == []
        with pytest.raises(ServerNotFoundError):
            await runtime.query("x", refresh_servers=["missing"])

    async def test_query_logs_failed_refreshes(
        self, runtime: MCPRuntime, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken() -> FakeAdapter:
            adapter = catalog()
            adapter.failures["list_tools"] = [ServerConnectionError("down")]
            return adapter

        await runtime.register_server(
            "crm", broken, refresh=RefreshPolicy(on_query_miss=True)
        )
        with caplog.at_level(logging.WARNING, logger="mcp_capability_router"):
            assert await runtime.query("search") == []
        assert "Automatic query refresh of server 'crm' failed" in caplog.text


class TestOperations:
    async def test_execute_read_and_render(self, runtime: MCPRuntime) -> None:
        factory = Factory()
        await runtime.register_server(
            "crm", factory, refresh=RefreshPolicy(on_register=True)
        )
        assert await runtime.execute("crm:tool:search", {"q": "x"}) == {
            "tool": "search",
            "arguments": {"q": "x"},
        }
        assert await runtime.execute("crm:tool:search") == {
            "tool": "search",
            "arguments": {},
        }
        assert (
            await runtime.read_resource("crm:resource:file:///guide.md")
            == "contents of file:///guide.md"
        )
        rendered = await runtime.get_prompt("crm:prompt:summarize", {"text": "hello"})
        assert rendered == "prompt summarize with {'text': 'hello'}"
        assert factory.adapters[0].connects == 1

    async def test_type_and_argument_errors(self, runtime: MCPRuntime) -> None:
        await runtime.register_server(
            "crm", Factory(), refresh=RefreshPolicy(on_register=True)
        )
        with pytest.raises(CapabilityNotFoundError, match="refresh its server first"):
            await runtime.execute("crm:tool:missing")
        with pytest.raises(CapabilityTypeError, match="is a resource, not a tool"):
            await runtime.execute("crm:resource:file:///guide.md")
        with pytest.raises(CapabilityTypeError, match="not a resource"):
            await runtime.read_resource("crm:tool:search")
        with pytest.raises(CapabilityTypeError, match="not a prompt"):
            await runtime.get_prompt("crm:tool:search")
        with pytest.raises(InvalidRequestError, match="requires the arguments"):
            await runtime.get_prompt("crm:prompt:summarize")
        with pytest.raises(InvalidRequestError, match="must be strings"):
            await runtime.get_prompt("crm:prompt:summarize", {"text": 3})  # type: ignore[dict-item]

    async def test_lost_connections_reconnect_on_next_use(
        self, runtime: MCPRuntime
    ) -> None:
        factory = Factory()
        await runtime.register_server(
            "crm", factory, refresh=RefreshPolicy(on_register=True)
        )
        factory.adapters[0].failures["call_tool"] = [ServerConnectionError("lost")]
        with pytest.raises(ServerConnectionError):
            await runtime.execute("crm:tool:search")
        assert factory.adapters[0].closes == 1
        await runtime.execute("crm:tool:search")
        assert len(factory.adapters) == 2

    async def test_as_tool(self, runtime: MCPRuntime) -> None:
        await runtime.register_server(
            "crm", Factory(), refresh=RefreshPolicy(on_register=True)
        )
        routed = await runtime.as_tool("crm:tool:search")
        assert isinstance(routed, StructuredTool)
        assert (routed.name, routed.description) == ("search", "Search records")
        assert routed.metadata == {
            "capability_id": "crm:tool:search",
            "server_id": "crm",
        }
        assert (await runtime.as_tool("crm:tool:search", name="crm_search")).name == (
            "crm_search"
        )

    async def test_health(self, runtime: MCPRuntime) -> None:
        await runtime.register_server("crm", Factory())
        assert await runtime.health("crm") is HealthState.HEALTHY
        with pytest.raises(ServerNotFoundError):
            await runtime.health("other")


class TestClose:
    async def test_close_is_idempotent_and_final(self) -> None:
        factory = Factory()
        runtime = MCPRuntime()
        await runtime.register_server(
            "crm", factory, refresh=RefreshPolicy(on_register=True)
        )
        await runtime.close()
        await runtime.close()
        assert factory.adapters[0].closes == 1
        assert runtime.servers == ()
        for call in (
            runtime.register_server("x", Factory()),
            runtime.retrieve("x"),
            runtime.resolve("crm:tool:search"),
            runtime.refresh(),
            runtime.unregister_server("crm"),
        ):
            with pytest.raises(RuntimeClosedError):
                await call
        with pytest.raises(RuntimeClosedError):
            await runtime.health("crm")

    async def test_external_registries_keep_capabilities(self) -> None:
        class Durable(InMemoryRegistry):
            closed = False

            async def close(self) -> None:
                self.closed = True

        registry = Durable()
        async with MCPRuntime(registry=registry) as runtime:
            await runtime.register_server(
                "crm", Factory(), refresh=RefreshPolicy(on_register=True)
            )
        assert registry.closed
        assert len(await registry.list()) == 4

    async def test_close_collects_every_error(self) -> None:
        class Failing(InMemoryRegistry):
            async def close(self) -> None:
                raise OSError("registry down")

        def sticky() -> FakeAdapter:
            adapter = catalog()
            adapter.failures["close"] = [OSError("adapter stuck")]
            return adapter

        runtime = MCPRuntime(registry=Failing())
        await runtime.register_server("crm", sticky)
        await runtime.connect("crm")
        with pytest.raises(ExceptionGroup) as raised:
            await runtime.close()
        assert sorted(str(error) for error in raised.value.exceptions) == [
            "adapter stuck",
            "registry down",
        ]

    async def test_cancelled_close_still_closes_the_registry(self) -> None:
        class Recording(InMemoryRegistry):
            closed = False

            async def close(self) -> None:
                self.closed = True

        class StuckClose(FakeAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.closing = asyncio.Event()

            async def close(self) -> None:
                self.closing.set()
                await asyncio.Event().wait()

        registry = Recording()
        breakers = AsyncCircuitBreakerFactory()
        adapter = StuckClose()
        runtime = MCPRuntime(registry=registry, circuit_breaker=breakers)
        await runtime.register_server("crm", lambda: adapter)
        await runtime.connect("crm")
        closing = asyncio.create_task(runtime.close())
        await adapter.closing.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert registry.closed
        assert breakers.listeners == {}
        await runtime.close()


class GatedDiscovery(FakeAdapter):
    """Blocks discovery until the test releases it, then lists or fails."""

    def __init__(self, failure: BaseException | None = None) -> None:
        super().__init__(tools=[mcp_tool("search", "Search records")])
        self.discovering = asyncio.Event()
        self.release = asyncio.Event()
        self.failure = failure

    async def list_tools(self) -> list[types.Tool]:
        self.discovering.set()
        await self.release.wait()
        if self.failure is not None:
            raise self.failure
        return await super().list_tools()


class TestConcurrentLifecycle:
    @pytest.mark.parametrize(
        ("failure", "raised", "message"),
        [
            (None, ServerNotFoundError, "while it was being registered"),
            (ServerConnectionError("down"), RefreshError, "down"),
        ],
    )
    async def test_unregister_during_registration_undoes_it(
        self,
        runtime: MCPRuntime,
        failure: BaseException | None,
        raised: type[Exception],
        message: str,
    ) -> None:
        adapter = GatedDiscovery(failure)
        registering = asyncio.create_task(
            runtime.register_server(
                "crm", lambda: adapter, refresh=RefreshPolicy(on_register=True)
            )
        )
        await adapter.discovering.wait()
        assert runtime.servers == ("crm",)
        unregistering = asyncio.create_task(runtime.unregister_server("crm"))
        await asyncio.sleep(0)
        assert runtime.servers == ()
        with pytest.raises(ConfigurationError, match="being unregistered"):
            await runtime.register_server("crm", Factory())
        adapter.release.set()
        with pytest.raises(raised, match=message):
            await registering
        await unregistering
        assert await runtime.registry.list() == []
        assert adapter.closes == 1
        await runtime.register_server(
            "crm", Factory(), refresh=RefreshPolicy(on_register=True)
        )
        assert len(await runtime.registry.list()) == 4

    async def test_close_during_registration_undoes_it(self) -> None:
        adapter = GatedDiscovery()
        runtime = MCPRuntime()
        registering = asyncio.create_task(
            runtime.register_server(
                "crm", lambda: adapter, refresh=RefreshPolicy(on_register=True)
            )
        )
        await adapter.discovering.wait()
        closing = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        adapter.release.set()
        with pytest.raises(RuntimeClosedError):
            await registering
        await closing
        assert adapter.closes == 1

    async def test_operations_queued_at_close_do_not_reconnect(self) -> None:
        class SlowCalls(FakeAdapter):
            def __init__(self) -> None:
                super().__init__(tools=[mcp_tool("search", "Search records")])
                self.calling = asyncio.Event()
                self.release = asyncio.Event()

            async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
                self.calling.set()
                await self.release.wait()
                return await super().call_tool(name, arguments)

        adapters: list[SlowCalls] = []

        def factory() -> SlowCalls:
            adapters.append(SlowCalls())
            return adapters[-1]

        runtime = MCPRuntime(max_concurrency=1)
        await runtime.register_server(
            "crm", factory, refresh=RefreshPolicy(on_register=True)
        )
        first = asyncio.create_task(runtime.execute("crm:tool:search"))
        await adapters[0].calling.wait()
        queued = asyncio.create_task(runtime.execute("crm:tool:search"))
        for _ in range(5):
            await asyncio.sleep(0)
        await runtime.close()
        adapters[0].release.set()
        assert await first == {"tool": "search", "arguments": {}}
        with pytest.raises(ServerNotFoundError, match="server 'crm' is closed"):
            await queued
        assert len(adapters) == 1

    async def test_first_refresh_prunes_capabilities_the_server_dropped(self) -> None:
        registry = InMemoryRegistry()
        await registry.upsert_many(
            [tool("crm", "retired"), tool("crm", "search"), tool("billing", "pay")]
        )
        async with MCPRuntime(registry=registry) as runtime:
            await runtime.register_server(
                "crm", Factory(), refresh=RefreshPolicy(on_register=True)
            )
            assert capability_ids(await registry.list()) == [
                "billing:tool:pay",
                "crm:prompt:summarize",
                "crm:resource:file:///guide.md",
                "crm:tool:delete",
                "crm:tool:search",
            ]


async def test_capability_records_survive_custom_registries() -> None:
    class Listing(InMemoryRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.upserts: list[list[str]] = []

        async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
            items = list(capabilities)
            self.upserts.append(capability_ids(items))
            await super().upsert_many(items)

    registry = Listing()
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("crm", Factory())
        await runtime.refresh_server("crm")
        await runtime.refresh_server("crm")
        assert len(registry.upserts) == 4
        await runtime.refresh_server("crm", mode=RefreshMode.FULL)
        assert len(registry.upserts) == 8


async def test_concurrent_operations_share_one_connection() -> None:
    factory = Factory()
    async with MCPRuntime() as runtime:
        await runtime.register_server(
            "crm", factory, refresh=RefreshPolicy(on_register=True)
        )
        await runtime.reconnect("crm")
        factory.adapters[-1].delay = 0.01
        await asyncio.gather(*(runtime.execute("crm:tool:search") for _ in range(10)))
        assert len(factory.adapters) == 2
