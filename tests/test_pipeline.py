from __future__ import annotations

import asyncio

import pytest

from mcp_capability_router import CapabilityType, MCPRuntime
from mcp_capability_router.errors import CircuitOpenError


class RecordingMetrics:
    """In-memory metrics hook used to assert on emitted pipeline events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def record(self, event, *, attributes=None):
        self.events.append((event, dict(attributes or {})))

    def operations(self, event: str) -> set[str]:
        return {
            str(attrs["operation"])
            for name, attrs in self.events
            if name == event and "operation" in attrs
        }


class FakeAdapter:
    def __init__(self, prefix: str, *, fail_calls: bool = False):
        self.prefix = prefix
        self.fail_calls = fail_calls
        self.connect_count = 0

    async def connect(self):
        self.connect_count += 1

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": f"{self.prefix}_tool", "description": "d"}]

    async def list_resources(self):
        return [{"uri": f"file:///{self.prefix}.txt", "name": self.prefix}]

    async def list_prompts(self):
        return [{"name": f"{self.prefix}_prompt", "arguments": []}]

    async def call_tool(self, name, arguments=None):
        if self.fail_calls:
            raise RuntimeError("boom")
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        return uri

    async def get_prompt(self, name, arguments=None):
        return {"name": name, "arguments": arguments}


class TrackingAdapter(FakeAdapter):
    """Adapter whose connect() records peak concurrent invocations."""

    _active = 0
    _peak = 0
    _lock = asyncio.Lock()

    async def connect(self):
        cls = TrackingAdapter
        async with cls._lock:
            cls._active += 1
            cls._peak = max(cls._peak, cls._active)
        await asyncio.sleep(0.02)
        async with cls._lock:
            cls._active -= 1
        self.connect_count += 1


@pytest.mark.asyncio
async def test_metrics_are_emitted_for_every_pipeline_operation():
    metrics = RecordingMetrics()
    adapter = FakeAdapter("alpha")
    async with MCPRuntime(metrics=metrics) as runtime:
        await runtime.register_server("alpha", lambda: adapter)
        await runtime.refresh_server("alpha")
        tool = (await runtime.retrieve("tool", type=CapabilityType.TOOL))[0]
        resource = (await runtime.retrieve("alpha", type=CapabilityType.RESOURCE))[0]
        prompt = (await runtime.retrieve("prompt", type=CapabilityType.PROMPT))[0]
        await runtime.execute(tool.capability_id)
        await runtime.read_resource(resource.capability_id)
        await runtime.get_prompt(prompt.capability_id)

    started = metrics.operations("operation.start")
    succeeded = metrics.operations("operation.success")
    assert {"connect", "discover", "call_tool", "read_resource", "get_prompt"} <= started
    assert {"connect", "discover", "call_tool", "read_resource", "get_prompt"} <= succeeded
    assert metrics.operations("operation.failure") == set()


@pytest.mark.asyncio
async def test_bulkhead_admission_covers_connect_across_servers():
    TrackingAdapter._active = 0
    TrackingAdapter._peak = 0
    adapters = [TrackingAdapter(f"s{i}") for i in range(6)]
    async with MCPRuntime(max_concurrency=2) as runtime:
        for i, adapter in enumerate(adapters):
            await runtime.register_server(f"s{i}", lambda a=adapter: a)
        await asyncio.gather(*(runtime.connect(f"s{i}") for i in range(6)))

    assert all(a.connect_count == 1 for a in adapters)
    assert TrackingAdapter._peak <= 2


@pytest.mark.asyncio
async def test_operation_failure_degrades_health_and_is_isolated_per_server():
    healthy = FakeAdapter("ok")
    failing = FakeAdapter("bad", fail_calls=True)
    async with MCPRuntime() as runtime:
        await runtime.register_server("ok", lambda: healthy)
        await runtime.register_server("bad", lambda: failing)
        await runtime.refresh_server("ok")
        await runtime.refresh_server("bad")

        good_tool = (await runtime.retrieve("ok", type=CapabilityType.TOOL))[0]
        bad_tool = (await runtime.retrieve("bad", type=CapabilityType.TOOL))[0]

        await runtime.execute(good_tool.capability_id)
        with pytest.raises(RuntimeError):
            await runtime.execute(bad_tool.capability_id)

        assert await runtime.health("ok") == "healthy"
        assert await runtime.health("bad") == "degraded"


@pytest.mark.asyncio
async def test_unregister_resets_circuit_breaker_and_health_state():
    failing = FakeAdapter("bad", fail_calls=True)
    async with MCPRuntime() as runtime:
        await runtime.register_server("bad", lambda: failing)
        await runtime.refresh_server("bad")
        tool = (await runtime.retrieve("bad", type=CapabilityType.TOOL))[0]

        for _ in range(5):
            with pytest.raises(RuntimeError):
                await runtime.execute(tool.capability_id)

        with pytest.raises(CircuitOpenError):
            await runtime.execute(tool.capability_id)

        await runtime.unregister_server("bad")

        recovered = FakeAdapter("bad")
        await runtime.register_server("bad", lambda: recovered)
        await runtime.refresh_server("bad")
        tool = (await runtime.retrieve("bad", type=CapabilityType.TOOL))[0]
        result = await runtime.execute(tool.capability_id)
        assert result["name"] == f"{recovered.prefix}_tool"
        assert await runtime.health("bad") == "healthy"


@pytest.mark.asyncio
async def test_pipeline_fallback_serves_a_degraded_response_instead_of_raising():
    from mcp_capability_router.pipeline import OperationPipeline

    pipeline = OperationPipeline()

    async def always_fails():
        raise RuntimeError("upstream MCP server unavailable")

    async def degraded(error):
        return {"degraded": True, "reason": str(error)}

    result = await pipeline.run("flaky-server", "call_tool", always_fails, fallback=degraded)
    assert result == {"degraded": True, "reason": "upstream MCP server unavailable"}
    # Fallback resolved the call, so health reflects success rather than failure.
    assert await pipeline.health("flaky-server") == "healthy"
