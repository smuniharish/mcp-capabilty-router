"""Verify imports, package metadata, and one complete routed operation."""

from __future__ import annotations

import argparse
import asyncio
import json
from importlib.metadata import requires, version


async def verify() -> dict[str, object]:
    from fastmcp import FastMCP

    from mcp_capability_router import MCPRuntime, RefreshPolicy, ResiliencePolicy

    server = FastMCP("setup")

    @server.tool(annotations={"readOnlyHint": True})
    async def echo(text: str) -> str:
        """Echo text."""
        return text

    async with MCPRuntime(resilience=ResiliencePolicy(operation_timeout=10)) as runtime:
        await runtime.register_mcp("setup", server, refresh=RefreshPolicy(on_register=True))
        [tool] = await runtime.route_tools("echo text", limit=1)
        result = await tool({"text": "ready"})
        if result.data != "ready":
            msg = f"unexpected tool result: {result!r}"
            raise RuntimeError(msg)
    return {
        "ok": True,
        "version": version("mcp-capability-router"),
        "requirements": requires("mcp-capability-router"),
        "summary": "All checks passed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    report = asyncio.run(verify())
    print(json.dumps(report) if arguments.json else report["summary"])


if __name__ == "__main__":
    main()
