"""Example H: 10k-style capability simulation + retrieval + optional LLM selection + JIT.

Run:
    uv run python -m examples.capability_scale_simulation

Credential-free: simulates a large MCP server exposing 10,000+ Tools, Resources, and
Prompts, then walks the full pipeline the architecture describes end to end:

    metadata/index -> candidate retrieval -> filtering -> ranking
        -> optional LLM selection -> JIT loading -> active capability

The optional LLM selector is a small deterministic stand-in (an application-supplied
LangChain-compatible model would be dropped in unchanged) so the example stays fast and
reproducible; only the already-retrieved, already-ranked candidate set is ever passed to
it, never the full 16,000-capability registry.
"""

from __future__ import annotations

import asyncio
import time

from mcp_capability_router import CapabilityType, MCPRuntime
from mcp_capability_router.selection import LLMCapabilitySelector


class LargeServerAdapter:
    """An adapter that reports it exposes 10,000 tools, 5,000 resources, 1,000 prompts.

    Discovery itself stays cheap: the adapter returns the metadata description only; no
    capability is "loaded" (materialized) until :meth:`get_tool`/JIT loading requests it.
    """

    def __init__(self, tool_count: int, resource_count: int, prompt_count: int) -> None:
        self.tool_count = tool_count
        self.resource_count = resource_count
        self.prompt_count = prompt_count
        self.materialized: set[str] = set()

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [
            {
                "name": f"tool_{i}",
                "description": "invoice processing tool" if i == 4242 else "generic tool",
            }
            for i in range(self.tool_count)
        ]

    async def list_resources(self):
        return [
            {"uri": f"file:///doc_{i}.txt", "name": f"doc_{i}", "description": "reference document"}
            for i in range(self.resource_count)
        ]

    async def list_prompts(self):
        return [
            {"name": f"prompt_{i}", "description": "generic prompt", "arguments": []}
            for i in range(self.prompt_count)
        ]

    def get_tool(self, name: str) -> str:
        # JIT loading: materializing a tool is only ever done for a selected capability.
        self.materialized.add(name)
        return f"materialized:{name}"

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        return uri

    async def get_prompt(self, name, arguments=None):
        return {"name": name}


class KeywordModel:
    """Stand-in for an application-supplied LangChain-compatible model's ``ainvoke``."""

    async def ainvoke(self, prompt: dict) -> list[str]:
        query = prompt["query"].lower()
        return [
            c["id"]
            for c in prompt["candidates"]
            if any(token in c["description"].lower() for token in query.split())
        ][:3]


async def main() -> None:
    adapter = LargeServerAdapter(tool_count=10_000, resource_count=5_000, prompt_count=1_000)
    async with MCPRuntime() as runtime:
        await runtime.register_server("large", lambda: adapter)

        started = time.perf_counter()
        await runtime.refresh_server("large")
        print(f"discovered 16,000 capabilities in {time.perf_counter() - started:.3f}s")

        # Retrieval + filtering + ranking: never the full 16,000-capability set.
        candidates = await runtime.retrieve(
            "invoice processing", type=CapabilityType.TOOL, limit=25
        )
        print(f"retrieval narrowed 10,000 tools down to {len(candidates)} candidates")

        # Optional LLM selection receives only the narrowed candidate set.
        selector = LLMCapabilitySelector(KeywordModel())
        selected_ids = await selector.select("invoice processing", candidates)
        print("LLM-selected capability ids:", selected_ids)

        # JIT loading only materializes what was actually selected.
        for capability_id in selected_ids:
            loaded = await runtime.load(capability_id)
            print("JIT-loaded:", loaded)

        print(f"total materialized tools on the server adapter: {len(adapter.materialized)}")


if __name__ == "__main__":
    asyncio.run(main())
