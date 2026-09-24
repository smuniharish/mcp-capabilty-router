"""Run the official Everything MCP server through a direct client and the router.

Prerequisites:
    Node.js with npm/npx on PATH.
    uv sync --extra mcp

Run:
    uv run python -m examples.real_everything_mcp

This smoke test invokes the server's non-mutating ``echo`` tool. It downloads the official
package through npx when it is not already cached.
"""

from __future__ import annotations

from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime

from .mcp_smoke_support import (
    npx_launcher,
    require_command,
    run_smoke,
    select_tool,
)


async def main() -> None:
    require_command("npx", "Install Node.js from https://nodejs.org/ and reopen the terminal.")
    command, args = npx_launcher("@modelcontextprotocol/server-everything")
    client = MultiServerMCPClient(
        {"everything": {"command": command, "args": args, "transport": "stdio"}},
        handle_tool_errors=False,
    )

    async with MCPRuntime() as runtime:
        await runtime.register_mcp_client("everything", client)
        await runtime.refresh_server("everything")
        tool = select_tool(await runtime.retrieve("echo", server_id="everything"), "echo")
        print(await runtime.execute(tool.capability_id, {"message": "router smoke test"}))


if __name__ == "__main__":
    run_smoke(main())
