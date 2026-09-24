"""Non-running configuration hooks for real application integrations.

These functions are deliberately illustrative: install and configure the external packages in
your application, then adapt their session methods to the MCPAdapter protocol.
"""

from mcp_capability_router import MCPRuntime


def make_mcp_client_config(root: str) -> dict:
    """Return application-owned config for a stdio filesystem MCP server."""
    return {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", root],
            "transport": "stdio",
        }
    }


async def register_real_adapter(runtime: MCPRuntime, adapter_factory) -> None:
    """Hook for an adapter built with langchain-mcp-adapters."""
    await runtime.register_server("filesystem", adapter_factory)
    await runtime.refresh_server("filesystem")


# LangChain: pass await runtime.retrieve(...) to your configured model's tool-selection prompt.
# LangGraph: call runtime.query(...) and runtime.execute(...) inside an async graph node.
