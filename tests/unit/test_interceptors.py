from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from mcp_capability_router import (
    ConfigurationError,
    InMemoryResultCacheStore,
    MCPRuntime,
    Operation,
    OperationContext,
    RefreshPolicy,
    ServerConnectionError,
    ToolResultCache,
)
from tests.support import FakeAdapter, mcp_tool, resource, tool

READ_ONLY = tool("crm", "search", metadata={"annotations": {"read_only_hint": True}})
WRITER = tool("crm", "delete")


def call(capability: Any = READ_ONLY, **arguments: Any) -> OperationContext:
    return OperationContext(
        server_id="crm",
        operation=Operation.CALL_TOOL,
        capability=capability,
        arguments=arguments,
    )


class Counter:
    """A `call_next` that counts its calls and returns their number."""

    def __init__(self, result: Any = "result") -> None:
        self.calls = 0
        self.result = result

    async def __call__(self) -> Any:
        self.calls += 1
        await asyncio.sleep(0)
        return self.result


class TestInMemoryResultCacheStore:
    @pytest.mark.parametrize("value", [0, True, 1.5])
    def test_rejects_invalid_sizes(self, value: Any) -> None:
        with pytest.raises(ConfigurationError, match="max_entries"):
            InMemoryResultCacheStore(max_entries=value)

    async def test_evicts_least_recently_used_and_expired_entries(self) -> None:
        store = InMemoryResultCacheStore(max_entries=2)
        await store.set("a", 1, 60)
        await store.set("b", 2, 60)
        assert await store.get("a") == 1
        await store.set("c", 3, 60)
        assert len(store) == 2
        assert await store.get("b") is None
        assert await store.get("a") == 1
        await store.set("d", 4, 0.001)
        await asyncio.sleep(0.01)
        assert await store.get("d") is None
        assert len(store) == 1

    async def test_clears_by_prefix(self) -> None:
        store = InMemoryResultCacheStore()
        for key in ("crm:1", "crm:2", "billing:1"):
            await store.set(key, key, 60)
        await store.clear("crm:")
        assert [await store.get(key) for key in ("crm:1", "billing:1")] == [None, "billing:1"]
        await store.clear()
        assert len(store) == 0
        await store.close()


class TestToolResultCache:
    @pytest.mark.parametrize(
        ("options", "message"),
        [
            ({"ttl": 0}, "ttl"),
            ({"ttl": True}, "ttl"),
            ({"ttl": float("nan")}, "ttl"),
            ({"store": object()}, "ResultCacheStore"),
            ({"cacheable": 42}, "cacheable"),
        ],
    )
    def test_rejects_invalid_options(self, options: dict[str, Any], message: str) -> None:
        with pytest.raises(ConfigurationError, match=message):
            ToolResultCache(**options)

    async def test_caches_read_only_calls_by_arguments(self) -> None:
        cache = ToolResultCache()
        counter = Counter()
        assert await cache(call(q="a"), counter) == "result"
        assert await cache(call(q="a"), counter) == "result"
        assert counter.calls == 1
        await cache(call(q="b"), counter)
        assert counter.calls == 2
        assert isinstance(cache.store, InMemoryResultCacheStore)
        assert len(cache.store) == 2

    async def test_skips_uncacheable_operations(self) -> None:
        cache = ToolResultCache()
        counter = Counter()
        read = OperationContext(
            server_id="crm",
            operation=Operation.READ_RESOURCE,
            capability=resource("crm", "file:///a", "a"),
        )
        for context in (call(WRITER), call(q=object()), read, read):
            await cache(context, counter)
        assert counter.calls == 4
        custom = ToolResultCache(cacheable=lambda capability: capability.name == "delete")
        await custom(call(WRITER), counter)
        await custom(call(WRITER), counter)
        assert counter.calls == 5

    async def test_none_results_and_errors_are_not_cached(self) -> None:
        cache = ToolResultCache()
        empty = Counter(result=None)
        await cache(call(), empty)
        await cache(call(), empty)
        assert empty.calls == 2

        async def failing() -> Any:
            raise ServerConnectionError("down")

        with pytest.raises(ServerConnectionError):
            await cache(call(), failing)
        counter = Counter()
        assert await cache(call(), counter) == "result"

    async def test_concurrent_identical_calls_share_one_call(self) -> None:
        cache = ToolResultCache()
        release = asyncio.Event()
        calls = 0

        async def slow() -> str:
            nonlocal calls
            calls += 1
            await release.wait()
            return "shared"

        tasks = [asyncio.create_task(cache(call(), slow)) for _ in range(3)]
        await asyncio.sleep(0.01)
        release.set()
        assert await asyncio.gather(*tasks) == ["shared"] * 3
        assert calls == 1

    async def test_waiters_share_the_error_of_the_call(self) -> None:
        cache = ToolResultCache()
        release = asyncio.Event()

        async def failing() -> Any:
            await release.wait()
            raise ServerConnectionError("down")

        tasks = [asyncio.create_task(cache(call(), failing)) for _ in range(2)]
        await asyncio.sleep(0.01)
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, ServerConnectionError) for result in results)

    async def test_waiters_call_themselves_when_the_shared_call_is_cancelled(self) -> None:
        cache = ToolResultCache()
        started = asyncio.Event()

        async def stuck() -> str:
            started.set()
            await asyncio.Event().wait()
            return "never"

        leader = asyncio.create_task(cache(call(), stuck))
        await started.wait()
        waiter = asyncio.create_task(cache(call(), Counter("own")))
        await asyncio.sleep(0)
        leader.cancel()
        assert await waiter == "own"
        with pytest.raises(asyncio.CancelledError):
            await leader

    async def test_cancelled_waiters_stay_cancelled(self) -> None:
        cache = ToolResultCache()
        release = asyncio.Event()

        async def slow() -> str:
            await release.wait()
            return "done"

        leader = asyncio.create_task(cache(call(), slow))
        await asyncio.sleep(0)
        waiter = asyncio.create_task(cache(call(), slow))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        assert await leader == "done"

    async def test_invalidation_and_fresh_tool_call_ids(self) -> None:
        cache = ToolResultCache()
        message = ToolMessage(content="ok", tool_call_id="call_1")
        counter = Counter(message)
        first = await cache(call(), counter)
        second = await cache(call(), counter)
        assert first is message
        assert second.content == "ok"
        assert second.tool_call_id != "call_1"
        await cache.invalidate("billing")
        await cache(call(), counter)
        assert counter.calls == 1
        await cache.invalidate("crm")
        await cache(call(), counter)
        assert counter.calls == 2
        await cache.invalidate()
        await cache(call(), counter)
        assert counter.calls == 3

    async def test_serves_cached_results_through_the_runtime(self) -> None:
        adapter = FakeAdapter(
            tools=[mcp_tool("search", "Search", annotations={"readOnlyHint": True})]
        )
        cache = ToolResultCache(ttl=60)
        async with MCPRuntime(interceptors=[cache]) as runtime:
            await runtime.register_server(
                "crm", lambda: adapter, refresh=RefreshPolicy(on_register=True)
            )
            first = await runtime.execute("crm:tool:search", {"q": "x"})
            adapter.failures["call_tool"] = [ServerConnectionError("down")]
            assert await runtime.execute("crm:tool:search", {"q": "x"}) == first
