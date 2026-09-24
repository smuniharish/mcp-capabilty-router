"""Dynamic server registration driven by a tool/graph result.

Run:
    uv run python -m examples.dynamic_registration

This example is credential-free: it uses small in-process adapters so the pattern
can be verified deterministically. It demonstrates registering new MCP servers at
runtime, based on the result of a previous tool call (or, equivalently, a prior
LangGraph node's output) rather than static configuration supplied up front.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import MCPRuntime


class DirectoryAdapter:
    """A "directory" server whose tool lists other MCP servers to connect to."""

    def __init__(self, downstream_specs):
        self._downstream_specs = downstream_specs

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "list_downstream_servers", "description": "list available MCP servers"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"servers": self._downstream_specs}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class DownstreamAdapter:
    def __init__(self, prefix: str):
        self.prefix = prefix

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": f"{self.prefix}_search", "description": "search records"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    directory = DirectoryAdapter(
        downstream_specs=[
            {"server_id": "reports", "prefix": "reports"},
            {"server_id": "billing", "prefix": "billing"},
        ]
    )
    async with MCPRuntime() as runtime:
        await runtime.register_server("directory", lambda: directory)
        await runtime.refresh_server("directory")

        discovery = await runtime.retrieve("list_downstream_servers")
        result = await runtime.execute(discovery[0].capability_id)

        # Each server named by the tool result is registered dynamically, at
        # runtime - this is the graph/tool-driven registration pattern.
        for spec in result["servers"]:
            adapter = DownstreamAdapter(spec["prefix"])
            await runtime.register_server(spec["server_id"], lambda adapter=adapter: adapter)
            await runtime.refresh_server(spec["server_id"])

        for server_id in ("reports", "billing"):
            matches = await runtime.retrieve("search", server_id=server_id)
            print(server_id, "->", [match.name for match in matches])


if __name__ == "__main__":
    asyncio.run(main())
