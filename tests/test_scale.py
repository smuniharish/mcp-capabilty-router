from __future__ import annotations

import asyncio
import time

import pytest

from mcp_capability_router import CapabilityType, MCPRuntime, Prompt, Resource, Tool


class BenchmarkAdapter:
    """Minimal adapter used to benchmark execute() dispatch against a large registry."""

    def __init__(self):
        self.connected = False
        self.call_count = 0

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def list_tools(self):
        return [{"name": "needle", "description": "the one real tool"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        self.call_count += 1
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        return uri

    async def get_prompt(self, name, arguments=None):
        return {"name": name, "arguments": arguments}


@pytest.mark.asyncio
@pytest.mark.parametrize("capability_count", [100, 1_000, 10_000])
async def test_retrieval_scales_across_capability_tiers(capability_count):
    """Retrieval latency must stay bounded as the registry grows from 100 to 10k capabilities."""
    async with MCPRuntime() as runtime:
        await runtime.register_server("scale", lambda: None)
        capabilities = [
            Tool(
                capability_id=f"scale:tool:{index}",
                server_id="scale",
                name=f"tool_{index}",
                description="searchable capability",
            )
            for index in range(capability_count)
        ]
        await runtime.registry.upsert_many(capabilities)

        started = time.perf_counter()
        matches = await runtime.retrieve("searchable", type=CapabilityType.TOOL, limit=25)
        elapsed = time.perf_counter() - started

        assert len(matches) == min(25, capability_count)
        assert elapsed < 1.0


@pytest.mark.asyncio
async def test_retrieval_scales_to_ten_thousand_capabilities():
    async with MCPRuntime() as runtime:
        await runtime.register_server("scale", lambda: None)
        capabilities = [
            Tool(
                capability_id=f"scale:tool:{index}",
                server_id="scale",
                name=f"tool_{index}",
                description="searchable capability",
            )
            for index in range(10_000)
        ]
        await runtime.registry.upsert_many(capabilities)

        started = time.perf_counter()
        matches = await runtime.retrieve("searchable", type=CapabilityType.TOOL, limit=25)
        elapsed = time.perf_counter() - started

        assert len(matches) == 25
        assert elapsed < 1.0


@pytest.mark.asyncio
async def test_registry_upsert_and_filtered_list_scale_to_ten_thousand_capabilities():
    """upsert_many and list() must stay usable at 10k mixed-type capabilities across servers."""
    async with MCPRuntime() as runtime:
        capabilities: list[Tool | Resource | Prompt] = []
        for index in range(10_000):
            server_id = f"server_{index % 20}"
            kind = index % 3
            if kind == 0:
                capabilities.append(
                    Tool(
                        capability_id=f"{server_id}:tool:{index}",
                        server_id=server_id,
                        name=f"tool_{index}",
                        description="benchmark tool",
                    )
                )
            elif kind == 1:
                capabilities.append(
                    Resource(
                        capability_id=f"{server_id}:resource:{index}",
                        server_id=server_id,
                        name=f"resource_{index}",
                        uri=f"file:///res_{index}.txt",
                        description="benchmark resource",
                    )
                )
            else:
                capabilities.append(
                    Prompt(
                        capability_id=f"{server_id}:prompt:{index}",
                        server_id=server_id,
                        name=f"prompt_{index}",
                        description="benchmark prompt",
                    )
                )

        started = time.perf_counter()
        await runtime.registry.upsert_many(capabilities)
        upsert_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        one_server = await runtime.registry.list(server_id="server_5")
        list_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        only_prompts = await runtime.registry.list(type=CapabilityType.PROMPT)
        type_filter_elapsed = time.perf_counter() - started

        assert len(one_server) == 500
        assert len(only_prompts) > 3_000
        assert upsert_elapsed < 2.0
        assert list_elapsed < 1.0
        assert type_filter_elapsed < 1.0


@pytest.mark.asyncio
async def test_execute_dispatch_stays_fast_against_ten_thousand_other_capabilities():
    """A single execute() call must resolve in near-constant time regardless of registry size."""
    adapter = BenchmarkAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("scale", lambda: adapter)
        noise = [
            Tool(
                capability_id=f"scale:tool:noise_{index}",
                server_id="scale",
                name=f"noise_{index}",
                description="unrelated capability",
            )
            for index in range(10_000)
        ]
        await runtime.registry.upsert_many(noise)
        await runtime.registry.upsert_many(
            [Tool(capability_id="scale:tool:needle", server_id="scale", name="needle")]
        )

        started = time.perf_counter()
        result = await runtime.execute("scale:tool:needle", {"q": "value"})
        elapsed = time.perf_counter() - started

        assert result["name"] == "needle"
        assert adapter.call_count == 1
        assert elapsed < 0.5


@pytest.mark.asyncio
async def test_query_with_refresh_scales_to_ten_thousand_existing_capabilities():
    """query() should skip refreshing already-populated servers even at 10k-capability scale."""
    adapter = BenchmarkAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("scale", lambda: adapter)
        noise = [
            Tool(
                capability_id=f"scale:tool:noise_{index}",
                server_id="scale",
                name=f"noise_{index}",
                description="searchable noise capability",
            )
            for index in range(10_000)
        ]
        await runtime.registry.upsert_many(noise)

        started = time.perf_counter()
        matches = await runtime.query("searchable", refresh_servers=["scale"], limit=10)
        elapsed = time.perf_counter() - started

        assert len(matches) == 10
        assert adapter.connected is False
        assert elapsed < 1.0


@pytest.mark.asyncio
async def test_concurrent_retrieval_throughput_at_ten_thousand_capabilities():
    """Many concurrent retrieve() calls over a 10k registry must complete well within budget."""
    async with MCPRuntime() as runtime:
        await runtime.register_server("scale", lambda: None)
        capabilities = [
            Tool(
                capability_id=f"scale:tool:{index}",
                server_id="scale",
                name=f"tool_{index}",
                description="concurrent searchable capability",
            )
            for index in range(10_000)
        ]
        await runtime.registry.upsert_many(capabilities)

        started = time.perf_counter()
        results = await asyncio.gather(
            *(runtime.retrieve("concurrent", limit=5) for _ in range(50))
        )
        elapsed = time.perf_counter() - started

        assert all(len(result) == 5 for result in results)
        assert elapsed < 2.0
