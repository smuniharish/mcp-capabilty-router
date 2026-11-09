"""Let a model write code that calls MCP tools, in a sandbox (experimental).

In code mode, the gateway offers three tools: `search`, which ranks the tools
with the runtime's retriever, `get_schema`, which returns the parameters of
named tools, and `execute`, which runs Python that calls tools with
`await call_tool(name, arguments)` in a sandbox. A model that writes one script
can chain several calls in one round trip, and intermediate results never pass
through its context.

Code mode is experimental in FastMCP. Requires the `codemode` extra:
`pip install "mcp-capability-router[codemode]"`.
"""

import asyncio

from common import billing_server, crm_server
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent

from mcp_capability_router import MCPRuntime, RefreshPolicy

CODE = """
customers = await call_tool("crm_search_customers", {"query": "acme"})
customer = customers["result"][0]
invoices = await call_tool("billing_list_invoices", {"customer_id": customer["id"]})
return {"customer": customer["name"], "invoices": [i["id"] for i in invoices["result"]]}
"""


def text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def main() -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        async with Client(runtime.as_mcp_server(mode="code", max_results=3)) as client:
            print(f"tools: {[tool.name for tool in await client.list_tools()]}")
            found = await client.call_tool("search", {"query": "invoices of a customer"})
            print(f"search found:\n{text(found)}")
            result = await client.call_tool("execute", {"code": CODE})
            print(f"execute returned: {text(result)}")


if __name__ == "__main__":
    asyncio.run(main())
