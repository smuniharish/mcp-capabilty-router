"""Example J: On-demand (lazy) MCP server connection.

Run:
    uv run python -m examples.on_demand_connection

Credential-free: demonstrates that registering a server and discovering its
capabilities does not open a connection -- the underlying adapter is only
constructed and connected the first time an operation actually needs it
(``execute``/``read_resource``/``get_prompt``/``load``/an explicit ``connect``).
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import MCPRuntime


class LazyAdapter:
    """An adapter that reports how many times it has actually been connected."""

    connection_count = 0

    def __init__(self) -> None:
        pass

    async def connect(self):
        LazyAdapter.connection_count += 1

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "ping", "description": "connectivity check"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"pong": True}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    async with MCPRuntime() as runtime:
        # register_server() takes a *factory*: neither the factory nor connect() runs
        # here, so the adapter has not been instantiated or connected yet.
        await runtime.register_server("lazy", lambda: LazyAdapter())
        print("after registration, connections made:", LazyAdapter.connection_count)

        # refresh_server() needs live metadata from the adapter, so this is where the
        # first real connection happens -- discovery itself is what triggers it, not
        # registration.
        await runtime.refresh_server("lazy")
        print("after refresh (first discovery), connections made:", LazyAdapter.connection_count)

        matches = await runtime.retrieve("ping")
        result = await runtime.execute(matches[0].capability_id)
        print("execute result:", result)
        print("connections made after execute (adapter cached):", LazyAdapter.connection_count)


if __name__ == "__main__":
    asyncio.run(main())
