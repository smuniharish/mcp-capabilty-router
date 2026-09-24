from __future__ import annotations

import asyncio

import pytest
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from mcp_capability_router import CapabilityType, MCPRuntime
from mcp_capability_router.errors import ServerError
from mcp_capability_router.resilience import semantic_classifier


class FakeAdapter:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.connected = False
        self.connect_count = 0

    async def connect(self):
        self.connect_count += 1
        await asyncio.sleep(0)
        self.connected = True

    async def close(self):
        self.connected = False

    async def list_tools(self):
        return [{"name": f"{self.prefix}_search", "description": "search records"}]

    async def list_resources(self):
        return [{"uri": f"file:///{self.prefix}.txt", "name": self.prefix, "description": "text"}]

    async def list_prompts(self):
        return [{"name": f"{self.prefix}_prompt", "arguments": [{"name": "topic"}]}]

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        return uri

    async def get_prompt(self, name, arguments=None):
        return {"name": name, "arguments": arguments}


class FlakyAdapter(FakeAdapter):
    def __init__(self):
        super().__init__("flaky")
        self.failures = 1

    async def call_tool(self, name, arguments=None):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary MCP failure")
        return await super().call_tool(name, arguments)


@pytest.mark.asyncio
async def test_discovery_routing_and_jit():
    adapter = FakeAdapter("alpha")
    async with MCPRuntime() as runtime:
        await runtime.register_server("alpha", lambda: adapter)
        assert adapter.connect_count == 0
        await runtime.refresh_server("alpha")
        assert adapter.connect_count == 1
        tools = await runtime.retrieve("search", type=CapabilityType.TOOL)
        assert len(tools) == 1
        result = await runtime.execute(tools[0].capability_id, {"q": "x"})
        assert result["name"] == "alpha_search"


@pytest.mark.asyncio
async def test_all_capability_types_and_isolation():
    a, b = FakeAdapter("a"), FakeAdapter("b")
    async with MCPRuntime() as first, MCPRuntime() as second:
        await first.register_server("a", lambda: a)
        await second.register_server("b", lambda: b)
        await first.refresh()
        await second.refresh()
        assert len(await first.retrieve("a")) == 3
        assert await second.retrieve("zzzz") == []
        resources = await first.retrieve("file", type=CapabilityType.RESOURCE)
        prompts = await first.retrieve("prompt", type=CapabilityType.PROMPT)
        assert await first.read_resource(resources[0].capability_id)
        assert (await first.get_prompt(prompts[0].capability_id, {"topic": "x"}))["name"]


@pytest.mark.asyncio
async def test_concurrent_connect_is_deduplicated():
    adapter = FakeAdapter("alpha")
    async with MCPRuntime() as runtime:
        await runtime.register_server("alpha", lambda: adapter)
        await asyncio.gather(*(runtime.connect("alpha") for _ in range(10)))
        assert adapter.connect_count == 1


@pytest.mark.asyncio
async def test_runtime_resilience_retries_operations_and_recovers_health():
    adapter = FlakyAdapter()
    retry = AsyncRetrying(
        stop=stop_after_attempt(2),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )
    async with MCPRuntime(retry=retry) as runtime:
        await runtime.register_server("flaky", lambda: adapter)
        await runtime.refresh_server("flaky")
        tool = (await runtime.retrieve("search"))[0]
        result = await runtime.execute(tool.capability_id)
        assert result["name"] == "flaky_search"
        assert await runtime.health("flaky") == "healthy"


@pytest.mark.asyncio
async def test_duplicate_server_registration_raises():
    adapter = FakeAdapter("dup")
    async with MCPRuntime() as runtime:
        await runtime.register_server("dup", lambda: adapter)
        with pytest.raises(ServerError):
            await runtime.register_server("dup", lambda: adapter)


@pytest.mark.asyncio
async def test_jit_load_is_cached_and_prevents_duplicate_loads():
    class CountingAdapter(FakeAdapter):
        def __init__(self):
            super().__init__("count")
            self.get_tool_calls = 0

        def get_tool(self, name):
            self.get_tool_calls += 1
            return f"loaded:{name}"

    adapter = CountingAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("count", lambda: adapter)
        await runtime.refresh_server("count")
        tool = (await runtime.retrieve("search"))[0]

        first, second, *rest = await asyncio.gather(
            runtime.load(tool.capability_id),
            runtime.load(tool.capability_id),
            runtime.load(tool.capability_id),
        )
        assert first == second == rest[0] == f"loaded:{tool.name}"
        assert adapter.get_tool_calls == 1
