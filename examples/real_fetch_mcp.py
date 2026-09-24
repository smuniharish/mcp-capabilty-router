"""Run the official Fetch MCP server through a direct client and the router.

Prerequisites:
    uv/uvx on PATH and outbound HTTPS access to https://example.com/.
    uv sync --extra mcp

Run:
    uv run python -m examples.real_fetch_mcp

This smoke test invokes the server's ``fetch`` tool against example.com. Fetch can access
network-reachable addresses, so do not substitute private or credential-bearing URLs.
"""

from __future__ import annotations

from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime

from .mcp_smoke_support import require_command, run_smoke, select_tool


async def main() -> None:
    require_command(
        "uvx", "Install uv from https://docs.astral.sh/uv/getting-started/installation/."
    )
    client = MultiServerMCPClient(
        {
            "fetch": {
                "command": "uvx",
                "args": ["--system-certs", "mcp-server-fetch", "--ignore-robots-txt"],
                "transport": "stdio",
            }
        },
        handle_tool_errors=False,
    )

    async with MCPRuntime() as runtime:
        await runtime.register_mcp_client("fetch", client)
        await runtime.refresh_server("fetch")
        tool = select_tool(await runtime.retrieve("fetch", server_id="fetch"), "fetch")
        print(
            await runtime.execute(
                tool.capability_id,
                {"url": "https://example.com/", "max_length": 500},
            )
        )


if __name__ == "__main__":
    run_smoke(main())
