"""Measure refresh, dispatch, and pipeline overhead of the runtime.

Usage:
    python benchmarks/bench_runtime.py
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Mapping
from typing import Any

from mcp import types

from mcp_capability_router import MCPRuntime


class CatalogAdapter:
    """An in-memory adapter with a large tool catalog and instant calls."""

    def __init__(self, size: int) -> None:
        self.tools = [
            types.Tool(
                name=f"tool_{index}",
                description=f"Tool number {index}",
                input_schema={"type": "object", "properties": {}},
            )
            for index in range(size)
        ]

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[types.Tool]:
        return self.tools

    async def list_resources(self) -> list[types.Resource]:
        return []

    async def list_prompts(self) -> list[types.Prompt]:
        return []

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> str:
        return name

    async def read_resource(self, uri: str) -> str:
        return uri

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> str:
        return name


async def main() -> None:
    print(f"{'measurement':<40} {'value':>10}")
    for size in (1_000, 10_000):
        async with MCPRuntime() as runtime:
            await runtime.register_server(
                "catalog", lambda size=size: CatalogAdapter(size)
            )
            started = time.perf_counter()
            first = await runtime.refresh_server("catalog")
            initial = time.perf_counter() - started
            started = time.perf_counter()
            second = await runtime.refresh_server("catalog")
            unchanged = time.perf_counter() - started
            if (first.added_count, second.unchanged_count) != (size, size):
                msg = f"unexpected refresh results: {first}, {second}"
                raise RuntimeError(msg)
            label = f"first refresh, {size:,} tools"
            print(f"{label:<40} {initial * 1000:>7.0f} ms")
            label = f"incremental refresh, {size:,} unchanged"
            print(f"{label:<40} {unchanged * 1000:>7.0f} ms")

            samples = []
            for index in range(2_000):
                started = time.perf_counter()
                await runtime.execute(f"catalog:tool:tool_{index % size}")
                samples.append(time.perf_counter() - started)
            median = statistics.median(samples) * 1_000_000
            label = f"execute among {size:,} tools (median)"
            print(f"{label:<40} {median:>7.0f} us")


if __name__ == "__main__":
    asyncio.run(main())
