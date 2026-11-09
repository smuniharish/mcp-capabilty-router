"""The runtime's extension points: state stores, events, fingerprints, and policies."""

from __future__ import annotations

import pytest
import refresh_engine
from fastmcp import Client
from purgatory import AsyncCircuitBreakerFactory
from refresh_engine import (
    AsyncEventPublisher,
    ContentHash,
    EventKind,
    InMemoryMetrics,
    InMemoryStateStore,
    RefreshEvent,
    ResourceFingerprint,
    ResourceSnapshot,
    StateStore,
)

from mcp_capability_router import (
    CapabilityRoutingMiddleware,
    ConfigurationError,
    FastMCPAdapter,
    HealthState,
    InMemoryRegistry,
    MCPRuntime,
    RefreshPolicy,
    ResiliencePolicy,
    ServerConnectionError,
    Tool,
)
from tests.support import FakeAdapter, capability_ids, demo_server, mcp_tool


def adapter() -> FakeAdapter:
    return FakeAdapter(
        tools=[
            mcp_tool("search", "Search records", annotations={"readOnlyHint": True}),
            mcp_tool("delete", "Delete a record"),
        ]
    )


ON_REGISTER = RefreshPolicy(on_register=True)


class TestStateStores:
    async def test_policy_store_restores_the_registry_after_a_restart(self) -> None:
        store = InMemoryStateStore()
        policy = RefreshPolicy(on_register=True, state_store=store)
        async with MCPRuntime() as first:
            await first.register_server("crm", adapter, refresh=policy)
            assert len(await first.registry.list()) == 2
        async with MCPRuntime() as second:
            await second.register_server("crm", adapter, refresh=policy)
            assert sorted(capability_ids(await second.registry.list())) == [
                "crm:tool:delete",
                "crm:tool:search",
            ]

    @pytest.mark.parametrize("asynchronous", [False, True])
    async def test_factories_create_one_store_per_server(self, asynchronous: bool) -> None:
        stores: dict[str, StateStore] = {}

        def create(server_id: str) -> StateStore:
            stores[server_id] = InMemoryStateStore()
            return stores[server_id]

        async def create_async(server_id: str) -> StateStore:
            return create(server_id)

        factory = create_async if asynchronous else create
        async with MCPRuntime(state_store_factory=factory) as runtime:
            await runtime.register_server("crm", adapter, refresh=ON_REGISTER)
            await runtime.register_server("billing", adapter, refresh=ON_REGISTER)
            assert sorted(stores) == ["billing", "crm"]
            own = InMemoryStateStore()
            await runtime.register_server("erp", adapter, refresh=RefreshPolicy(state_store=own))
            assert "erp" not in stores

    async def test_invalid_stores_are_rejected(self) -> None:
        async with MCPRuntime(
            state_store_factory=lambda server_id: object()  # type: ignore[arg-type,return-value]
        ) as runtime:
            with pytest.raises(ConfigurationError, match="does not subclass"):
                await runtime.register_server("crm", adapter)
            assert runtime.servers == ()
        with pytest.raises(ConfigurationError, match="state_store_factory"):
            MCPRuntime(state_store_factory=object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="state_store"):
            RefreshPolicy(state_store=object())  # type: ignore[arg-type]

    async def test_a_store_serves_one_server_at_a_time(self) -> None:
        store = InMemoryStateStore()
        policy = RefreshPolicy(state_store=store)
        async with MCPRuntime() as runtime:
            await runtime.register_server("crm", adapter, refresh=policy)
            with pytest.raises(ConfigurationError, match="used by server 'crm'"):
                await runtime.register_server("billing", adapter, refresh=policy)
            await runtime.unregister_server("crm")
            await runtime.register_server("billing", adapter, refresh=policy)


class TestEventsAndFingerprints:
    async def test_shared_publishers_receive_every_server_and_unsubscribe(self) -> None:
        publisher = AsyncEventPublisher()
        received: list[RefreshEvent] = []

        async def record(event: RefreshEvent) -> None:
            received.append(event)

        policy = RefreshPolicy(on_register=True, events=publisher, event_handlers=(record,))
        async with MCPRuntime() as runtime:
            await runtime.register_server("crm", adapter, refresh=policy)
            await runtime.unregister_server("crm")
        assert any(event.kind is EventKind.REFRESH_COMPLETED for event in received)
        count = len(received)
        async with MCPRuntime() as runtime:
            await runtime.register_server(
                "crm", adapter, refresh=RefreshPolicy(on_register=True, events=publisher)
            )
        assert len(received) == count

    async def test_metrics_are_published_without_a_policy_publisher(self) -> None:
        metrics = InMemoryMetrics()
        async with MCPRuntime(metrics=metrics) as runtime:
            await runtime.register_server("crm", adapter, refresh=ON_REGISTER)
        counters, _ = metrics.snapshot()
        assert any("server_id=crm" in name for name in counters)

    async def test_custom_fingerprints_are_used(self) -> None:
        calls: list[int] = []

        class Counting(ContentHash):
            async def fingerprint(self, snapshot: ResourceSnapshot, /) -> ResourceFingerprint:
                calls.append(1)
                return await super().fingerprint(snapshot)

        policy = RefreshPolicy(on_register=True, fingerprint=Counting())
        async with MCPRuntime() as runtime:
            await runtime.register_server("crm", adapter, refresh=policy)
        assert calls

    def test_invalid_events_and_fingerprints_are_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="events"):
            RefreshPolicy(events=object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="fingerprint"):
            RefreshPolicy(fingerprint=object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="config"):
            RefreshPolicy(config=object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="event handler"):
            RefreshPolicy(event_handlers=(lambda event: None,))  # type: ignore[arg-type]


class TestResilienceAndFilters:
    async def test_unhealthy_servers_are_left_out_of_retrieval(self) -> None:
        failing = adapter()
        failing.failures["call_tool"] = [ServerConnectionError("down")]
        breakers = AsyncCircuitBreakerFactory(default_threshold=1, default_ttl=60)
        async with MCPRuntime() as runtime:
            assert runtime.resilience == ResiliencePolicy()
            await runtime.register_server(
                "crm",
                lambda: failing,
                refresh=ON_REGISTER,
                resilience=ResiliencePolicy(circuit_breaker=breakers),
            )
            await runtime.register_server("billing", adapter, refresh=ON_REGISTER)
            with pytest.raises(ServerConnectionError):
                await runtime.execute("crm:tool:search")
            assert await runtime.health("crm") is HealthState.UNHEALTHY
            assert await runtime.health("billing") is HealthState.HEALTHY
            healthy = await runtime.retrieve("search")
            assert {c.server_id for c in healthy} == {"billing"}
            everything = await runtime.query("search", include_unhealthy=True)
            assert {c.server_id for c in everything} == {"billing", "crm"}

    async def test_where_filters_candidates(self) -> None:
        async with MCPRuntime() as runtime:
            await runtime.register_server("crm", adapter, refresh=ON_REGISTER)
            read_only = await runtime.retrieve(
                "record", where=lambda c: isinstance(c, Tool) and c.read_only
            )
            assert capability_ids(read_only) == ["crm:tool:search"]
            assert await runtime.query("record", where=lambda c: False) == []

    async def test_invalid_resilience_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="ResiliencePolicy"):
            MCPRuntime(resilience=object())  # type: ignore[arg-type]
        async with MCPRuntime() as runtime:
            with pytest.raises(ConfigurationError, match="ResiliencePolicy"):
                await runtime.register_server(
                    "crm",
                    adapter,
                    resilience=object(),  # type: ignore[arg-type]
                )


class TestRegisterMcp:
    async def test_client_options_reach_each_connection(self) -> None:
        async with MCPRuntime() as runtime:
            await runtime.register_mcp("demo", demo_server(), refresh=ON_REGISTER, timeout=5)
            result = await runtime.execute("demo:tool:add", {"a": 2, "b": 3})
            assert result.artifact == {"structured_content": {"result": 5}}

    async def test_client_options_need_a_target_not_a_client(self) -> None:
        async with MCPRuntime() as runtime:
            with pytest.raises(ConfigurationError, match=r"prebuilt fastmcp\.Client"):
                await runtime.register_mcp("demo", Client(demo_server()), timeout=5)


class TestEdges:
    def test_adapters_reject_options_for_prebuilt_clients(self) -> None:
        with pytest.raises(ConfigurationError, match=r"prebuilt fastmcp\.Client"):
            FastMCPAdapter(Client(demo_server()), timeout=5)

    async def test_middleware_filters_must_be_callable(self) -> None:
        async with MCPRuntime() as runtime:
            with pytest.raises(ConfigurationError, match="where"):
                CapabilityRoutingMiddleware(runtime, where=42)  # type: ignore[arg-type]

    def test_tool_hints(self) -> None:
        plain = Tool(capability_id="s:tool:t", server_id="s", name="t")
        assert plain.destructive
        assert plain.open_world
        assert not plain.idempotent
        hinted = Tool(
            capability_id="s:tool:t",
            server_id="s",
            name="t",
            metadata={"annotations": {"destructive_hint": False, "open_world_hint": False}},
        )
        assert not hinted.destructive
        assert not hinted.open_world

    async def test_failed_engine_construction_releases_the_subscriptions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        publisher = AsyncEventPublisher()

        def broken(*args: object, **kwargs: object) -> None:
            raise refresh_engine.ConfigurationError("bad engine")

        monkeypatch.setattr("mcp_capability_router.runtime.RefreshEngine", broken)
        async with MCPRuntime(metrics=InMemoryMetrics()) as runtime:
            with pytest.raises(refresh_engine.ConfigurationError, match="bad engine"):
                await runtime.register_server(
                    "crm", adapter, refresh=RefreshPolicy(events=publisher)
                )
            assert runtime.servers == ()

    async def test_restoring_into_a_complete_registry_stores_nothing(self) -> None:
        class Durable(InMemoryRegistry):
            async def close(self) -> None:
                """Keep the capabilities, as a database would."""

        registry = Durable()
        policy = RefreshPolicy(on_register=True, state_store=InMemoryStateStore())
        async with MCPRuntime(registry=registry) as first:
            await first.register_server("crm", adapter, refresh=policy)
        async with MCPRuntime(registry=registry) as second:
            await second.register_server("crm", adapter, refresh=policy)
            assert len(await registry.list()) == 2
