"""Route to official MCP servers launched over stdio.

Starts the official Filesystem MCP server with npx, scoped to a temporary
directory, then retrieves and calls its file-reading tool. The same call works
for any server that FastMCP can launch or reach: a script path, a URL, or an MCP
configuration dictionary.

Requires Node.js with npx on PATH and network access for the first download:

    MCP_ROUTER_EXAMPLE_NODE=1
"""

import asyncio
import tempfile
from pathlib import Path

from fastmcp.client.transports import NpxStdioTransport

from mcp_capability_router import CapabilityType, MCPRuntime, RefreshPolicy


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        note = Path(directory) / "release-notes.md"
        note.write_text("# 0.2.0\nRouted through MCP.", encoding="utf-8")
        server = NpxStdioTransport(
            "@modelcontextprotocol/server-filesystem", [directory]
        )
        async with MCPRuntime(operation_timeout=120) as runtime:
            await runtime.register_mcp(
                "filesystem", server, refresh=RefreshPolicy(on_register=True)
            )
            tools = await runtime.registry.list(type=CapabilityType.TOOL)
            print(f"discovered {len(tools)} tools")
            [match] = await runtime.retrieve(
                "read the text of a file", type=CapabilityType.TOOL, limit=1
            )
            print(f"selected: {match.name}")
            message = await runtime.execute(match.capability_id, {"path": str(note)})
            print(message.content[0]["text"])


if __name__ == "__main__":
    asyncio.run(main())
