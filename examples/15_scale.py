"""Route among ten thousand capabilities from twenty servers.

Each server has 500 tools. Registration is instant, refreshes run concurrently,
and a request still reaches the right tool in milliseconds, while a model would
only ever see the handful of tools that retrieval returns.
"""

import asyncio
from collections.abc import Mapping
from typing import Any

from mcp import types

from mcp_capability_router import CapabilityType, MCPRuntime

DOMAINS = ("files", "issues", "invoices", "emails", "calendars")
VERBS = ("list", "read", "create", "update", "delete")


class GeneratedServer:
    """An in-memory MCP adapter with 500 generated tools."""

    def __init__(self, number: int) -> None:
        domain = DOMAINS[number % len(DOMAINS)]
        self.tools = []
        for index in range(500):
            verb = VERBS[index % len(VERBS)]
            self.tools.append(
                types.Tool(
                    name=f"{verb}_{domain}_{index}",
                    description=f"{verb.title()} {domain} in shard {index}.",
                    input_schema={"type": "object", "properties": {}},
                )
            )

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
        return f"{name} done"

    async def read_resource(self, uri: str) -> str:
        return uri

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> str:
        return name


async def main() -> None:
    async with MCPRuntime() as runtime:
        for number in range(20):
            await runtime.register_server(
                f"server-{number:02}", lambda number=number: GeneratedServer(number)
            )
        results = await runtime.refresh()
        total = sum(result.added_count for result in results.values())
        print(f"{len(results)} servers, {total:,} capabilities")

        matches = await runtime.retrieve(
            "delete invoices in shard 44", type=CapabilityType.TOOL, limit=3
        )
        for match in matches:
            print(f"  {match.capability_id}")
        print(await runtime.execute(matches[0].capability_id))


if __name__ == "__main__":
    asyncio.run(main())
