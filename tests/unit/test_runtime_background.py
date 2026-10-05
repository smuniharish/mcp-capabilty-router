from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import pytest
from refresh_engine import EventKind, InMemoryMetrics, RefreshEvent, TriggerSource

from mcp_capability_router import MCPRuntime, RefreshPolicy, ServerConnectionError
from tests.support import FakeAdapter, mcp_tool


class Completions:
    """Counts completed refreshes and wakes up waiters."""

    def __init__(self) -> None:
        self.count = 0
        self._changed = asyncio.Condition()

    async def __call__(self, event: RefreshEvent) -> None:
        if event.kind is EventKind.REFRESH_COMPLETED:
            async with self._changed:
                self.count += 1
                self._changed.notify_all()

    async def wait_for(self, count: int) -> None:
        async with asyncio.timeout(5), self._changed:
            await self._changed.wait_for(lambda: self.count >= count)


async def test_interval_refreshes_until_close() -> None:
    adapter = FakeAdapter(tools=[mcp_tool("first")])
    completions = Completions()
    runtime = MCPRuntime()
    await runtime.register_server(
        "s",
        lambda: adapter,
        refresh=RefreshPolicy(
            on_register=True, interval=0.02, event_handlers=(completions,)
        ),
    )
    adapter.tools.append(mcp_tool("second"))
    await completions.wait_for(2)
    assert await runtime.registry.get("s:tool:second") is not None
    await runtime.close()
    listings = adapter.calls.count(("list_tools", None))
    await asyncio.sleep(0.06)
    assert adapter.calls.count(("list_tools", None)) == listings


async def test_queue_events_are_coalesced_and_acknowledged() -> None:
    adapter = FakeAdapter(tools=[mcp_tool("first")])
    events: asyncio.Queue[str] = asyncio.Queue()
    async with MCPRuntime() as runtime:
        await runtime.register_server(
            "s", lambda: adapter, refresh=RefreshPolicy(change_events=events)
        )
        for index in range(5):
            events.put_nowait(f"change {index}")
        async with asyncio.timeout(5):
            await events.join()
        assert adapter.calls.count(("list_tools", None)) <= 2
        assert await runtime.registry.get("s:tool:first") is not None


async def test_async_iterable_events_trigger_refreshes() -> None:
    adapter = FakeAdapter(tools=[mcp_tool("first")])
    completions = Completions()

    async def changes() -> AsyncIterator[str]:
        yield "created"
        yield "updated"

    async with MCPRuntime() as runtime:
        await runtime.register_server(
            "s",
            lambda: adapter,
            refresh=RefreshPolicy(
                change_events=changes(), event_handlers=(completions,)
            ),
        )
        await completions.wait_for(2)
        assert adapter.calls.count(("list_tools", None)) == 2


async def test_finite_event_sources_are_consumed_to_the_end() -> None:
    adapter = FakeAdapter(tools=[mcp_tool("first")])

    async def changes() -> AsyncIterator[str]:
        yield "created"
        yield "updated"

    async with MCPRuntime() as runtime:
        await runtime.register_server("s", lambda: adapter)
        await runtime._watch("s", changes())
        assert adapter.calls.count(("list_tools", None)) == 2


async def test_failing_event_sources_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken() -> AsyncIterator[str]:
        raise RuntimeError("stream closed")
        yield "never"

    with caplog.at_level(logging.ERROR, logger="mcp_capability_router"):
        async with MCPRuntime() as runtime:
            await runtime.register_server(
                "s", FakeAdapter, refresh=RefreshPolicy(change_events=broken())
            )
            await asyncio.sleep(0.05)
    assert "The change events of server 's' failed" in caplog.text


async def test_failed_background_refreshes_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> FakeAdapter:
        adapter = FakeAdapter()
        adapter.failures["list_tools"] = [ServerConnectionError("down")]
        return adapter

    events: asyncio.Queue[str] = asyncio.Queue()
    with caplog.at_level(logging.WARNING, logger="mcp_capability_router"):
        async with MCPRuntime() as runtime:
            await runtime.register_server(
                "s", broken, refresh=RefreshPolicy(change_events=events)
            )
            events.put_nowait("changed")
            async with asyncio.timeout(5):
                await events.join()

            async def boom(*args: object, **kwargs: object) -> None:
                raise ValueError("unexpected")

            runtime._refresh = boom  # type: ignore[method-assign]
            await runtime._background_refresh("s", TriggerSource.EVENT)
            await runtime._background_refresh("missing", TriggerSource.EVENT)
    assert "Automatic event refresh of server 's' failed" in caplog.text
    assert "unexpected" in caplog.text


async def test_event_handlers_and_metrics_observe_refreshes() -> None:
    received: list[RefreshEvent] = []
    metrics = InMemoryMetrics()
    async with MCPRuntime(metrics=metrics) as runtime:
        await runtime.register_server(
            "s",
            lambda: FakeAdapter(tools=[mcp_tool("first")]),
            refresh=RefreshPolicy(on_register=True, event_handlers=(received.append,)),
        )
    assert EventKind.REFRESH_COMPLETED in {event.kind for event in received}
    counters, _ = metrics.snapshot()
    assert (
        counters[
            "refresh_engine.refreshes{mode=incremental,server_id=s,status=success,"
            "trigger=manual}"
        ]
        == 1
    )
    assert (
        counters[
            "mcp_capability_router.operations"
            "{operation=discover,outcome=success,server_id=s}"
        ]
        == 1
    )


async def test_event_handlers_work_without_metrics() -> None:
    received: list[RefreshEvent] = []
    async with MCPRuntime() as runtime:
        await runtime.register_server(
            "s",
            FakeAdapter,
            refresh=RefreshPolicy(on_register=True, event_handlers=(received.append,)),
        )
    assert EventKind.REFRESH_COMPLETED in {event.kind for event in received}
