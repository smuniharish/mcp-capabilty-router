"""Real Filesystem MCP smoke test through langchain-mcp-adapters.

Prerequisites:
    Node.js and npm/npx available on PATH.
    uv sync --extra mcp

Run:
    uv run python -m examples.real_filesystem_mcp

The script starts the official filesystem MCP server through stdio, discovers its tools, and
routes one selected tool through this package. It uses a temporary directory and no credentials.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "router-note.txt").write_text("router smoke test", encoding="utf-8")
        async with MCPRuntime() as runtime:
            client = MultiServerMCPClient(
                {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(root)],
                        "transport": "stdio",
                    }
                }
            )
            await runtime.register_mcp_client("filesystem", client)
            await runtime.refresh_server("filesystem")
            matches = await runtime.retrieve("read file", limit=1)
            if not matches:
                raise RuntimeError("Filesystem MCP returned no matching tools")
            print("selected:", matches[0].name)
            print(await runtime.execute(matches[0].capability_id, {"path": "router-note.txt"}))


if __name__ == "__main__":
    asyncio.run(main())
