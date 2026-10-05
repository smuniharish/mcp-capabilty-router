"""Route a request to the right tool of an MCP server.

Registers an MCP server, discovers its capabilities, retrieves the tool that
matches a request, and calls it.
"""

import asyncio

from common import crm_server

from mcp_capability_router import MCPRuntime, RefreshPolicy


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "crm", crm_server(), refresh=RefreshPolicy(on_register=True)
        )
        [match] = await runtime.retrieve("find a customer by name", limit=1)
        print(f"best match: {match.capability_id}")

        result = await runtime.execute(match.capability_id, {"query": "acme"})
        print(f"result: {result.artifact['structured_content']['result']}")


if __name__ == "__main__":
    asyncio.run(main())
