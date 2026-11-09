"""Serve the router as one MCP server that any MCP client can use.

`MCPRuntime.as_mcp_server` returns a FastMCP server that offers the tools,
resources, and prompts of every registered server through the runtime, so the
resilience pipeline, interceptors, and metrics apply to every client. In the
default search mode, clients see two tools: `search_tools`, which ranks the
tools with the runtime's retriever, and `call_tool`, which calls a found tool.
The catalog mode lists every tool instead.

The example connects to the gateway in process. Run it with `--serve` to serve
the gateway over Streamable HTTP at http://127.0.0.1:8000/mcp for any MCP client,
such as an IDE, a desktop assistant, or another agent framework.
"""

import asyncio
import sys

from common import billing_server, crm_server, docs_server
from fastmcp import Client
from mcp.types import TextContent

from mcp_capability_router import MCPRuntime, RefreshPolicy


async def main(serve: bool = False) -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)
        gateway = runtime.as_mcp_server("support-gateway", max_results=2)
        if serve:
            await gateway.run_async(transport="http", host="127.0.0.1", port=8000)
            return

        async with Client(gateway) as client:
            print(f"tools: {[tool.name for tool in await client.list_tools()]}")
            found = await client.call_tool("search_tools", {"query": "refund an invoice"})
            names = [tool["name"] for tool in found.data]
            print(f"search_tools found: {names}")
            result = await client.call_tool(
                "call_tool",
                {
                    "name": "billing_issue_refund",
                    "arguments": {"invoice_id": "inv-1", "amount": 50},
                },
            )
            print(f"call_tool returned: {result.structured_content}")
            resources = await client.list_resources()
            print(f"resources: {[resource.uri for resource in resources]}")
            prompt = await client.get_prompt(
                "crm_follow_up", {"customer_name": "Globex", "topic": "renewal"}
            )
            content = prompt.messages[0].content
            if isinstance(content, TextContent):
                print(f"prompt: {content.text}")

        async with Client(runtime.as_mcp_server(mode="catalog")) as client:
            print(f"catalog mode lists {len(await client.list_tools())} tools")


if __name__ == "__main__":
    asyncio.run(main(serve="--serve" in sys.argv))
