"""Real Playwright MCP routing example.

Run:
    uv run python -m examples.basic_runtime

Prerequisites:
    Node.js/npm available on PATH, browsers installed for @playwright/mcp
    (``npx -y @playwright/mcp install-browser chromium``), and ``uv sync --extra mcp``.

Navigates to local, self-contained HTML pages (not an external URL) so the example
succeeds deterministically regardless of outbound network policy in the runner's
environment; swap the ``file://`` URLs below for real pages once real navigation is
desired.

Note: each ``runtime.execute(...)`` call here invokes the routed ``StructuredTool``
through ``langchain-mcp-adapters``' default (non-persistent) session handling, so
browser state such as the currently open page is not guaranteed to carry over between
separate ``execute()`` calls. This example therefore demonstrates two independent,
self-contained navigations rather than a navigate-then-snapshot chain; applications
that need one continuous browser session across tool calls should hold their own
persistent ``client.session(...)`` and route through it instead of two independent
``execute()`` calls.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime

_PAGE_A = "<html><body><h1>router smoke test A</h1></body></html>"
_PAGE_B = "<html><body><h1>router smoke test B</h1></body></html>"


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        page_a = Path(directory) / "smoke-a.html"
        page_b = Path(directory) / "smoke-b.html"
        page_a.write_text(_PAGE_A, encoding="utf-8")
        page_b.write_text(_PAGE_B, encoding="utf-8")

        async with MCPRuntime() as runtime:
            client = MultiServerMCPClient(
                {
                    "playwright": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "@playwright/mcp@latest",
                            "--browser",
                            "chromium",
                            "--headless",
                            "--allow-unrestricted-file-access",
                        ],
                        "transport": "stdio",
                    }
                }
            )
            await runtime.register_mcp_client(
                "playwright",
                client,
                client_server_name="playwright",
            )
            await runtime.refresh_server("playwright")

            navigate_candidates = await runtime.retrieve("navigate", limit=20)
            navigate = [item for item in navigate_candidates if item.name == "browser_navigate"]
            if not navigate:
                raise RuntimeError("Playwright MCP did not expose a navigation capability")
            print("selected:", navigate[0].name)

            print(await runtime.execute(navigate[0].capability_id, {"url": page_a.as_uri()}))
            print(await runtime.execute(navigate[0].capability_id, {"url": page_b.as_uri()}))


if __name__ == "__main__":
    asyncio.run(main())
