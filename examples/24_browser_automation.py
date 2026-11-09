"""Route to a browser automation server: the Playwright MCP server.

Large servers expose many tools; Playwright's offers about 25. The router lets
a request reach the right one without showing the whole list to a model. The
example launches the Playwright MCP server over stdio with npx, routes two
requests to its tools, opens a page, and reads its title.

Requires Node.js with npx on PATH, network access for the first download, and
a browser that Playwright can drive, such as `chrome`, `msedge`, `firefox`, or
`chromium` (install it with `npx playwright install chromium`):

    MCP_ROUTER_EXAMPLE_BROWSER=chromium
"""

import asyncio
import os
import tempfile

from fastmcp.client.transports import NpxStdioTransport
from mcp import types

from mcp_capability_router import CapabilityType, MCPRuntime, RefreshPolicy, ResiliencePolicy

PAGE = "data:text/html,<title>Release notes</title><h1>1.0.0</h1>"


async def main(browser: str) -> None:
    with tempfile.TemporaryDirectory() as output:
        server = NpxStdioTransport(
            "@playwright/mcp@latest",
            ["--headless", "--isolated", "--browser", browser, "--output-dir", output],
        )
        async with MCPRuntime(resilience=ResiliencePolicy(operation_timeout=180)) as runtime:
            await runtime.register_mcp("browser", server, refresh=RefreshPolicy(on_register=True))
            tools = await runtime.registry.list(type=CapabilityType.TOOL)
            print(f"discovered {len(tools)} tools")
            for request in ("navigate to a URL", "take a screenshot of the page"):
                [match] = await runtime.retrieve(request, type=CapabilityType.TOOL, limit=1)
                print(f"{request!r} -> {match.name}")
            result = await runtime.execute("browser:tool:browser_navigate", {"url": PAGE})
            text = "\n".join(
                block.text for block in result.content if isinstance(block, types.TextContent)
            )
            title = next(line for line in text.splitlines() if line.startswith("- Page Title:"))
            print(title.removeprefix("- ").strip())
            await runtime.execute("browser:tool:browser_close", {})


if __name__ == "__main__":
    asyncio.run(main(os.environ["MCP_ROUTER_EXAMPLE_BROWSER"]))
