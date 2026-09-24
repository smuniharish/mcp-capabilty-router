"""Automatic refresh policies exercised against a real MCP server.

Run:
    uv sync --extra mcp
    uv run python -m examples.refresh_strategies

The official Everything MCP server is launched through the real
``MultiServerMCPClient``. The application only declares a ``RefreshPolicy``;
``MCPRuntime`` owns query-miss decisions, event listeners, interval tasks,
refresh deduplication, and lifecycle cancellation. ``RefreshPolicy.mode`` selects the
underlying ``refresh_engine.RefreshMode`` these automatic triggers run under (the
time-based policy below uses ``INCREMENTAL`` to only re-touch capabilities that
actually changed).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from langchain_mcp_adapters.client import MultiServerMCPClient
from refresh_engine import RefreshMode

from mcp_capability_router import MCPRuntime, RefreshPolicy

from .mcp_smoke_support import npx_launcher, require_command, run_smoke


class DiscoveryMetrics:
    """Count real discovery operations so automatic refreshes are observable."""

    def __init__(self) -> None:
        self.discoveries: dict[str, int] = {}

    async def record(
        self,
        event: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        values = attributes or {}
        if event == "operation.success" and values.get("operation") == "discover":
            server_id = str(values["server_id"])
            self.discoveries[server_id] = self.discoveries.get(server_id, 0) + 1


async def wait_for_discoveries(
    metrics: DiscoveryMetrics,
    server_id: str,
    expected: int,
) -> None:
    for _ in range(500):
        if metrics.discoveries.get(server_id, 0) >= expected:
            return
        await asyncio.sleep(0.01)
    raise RuntimeError(f"Expected {expected} automatic discoveries for {server_id!r}")


async def main() -> None:
    require_command("npx", "Install Node.js from https://nodejs.org/ and reopen the terminal.")
    command, args = npx_launcher("@modelcontextprotocol/server-everything")
    client = MultiServerMCPClient(
        {
            "everything": {
                "command": command,
                "args": args,
                "transport": "stdio",
            }
        },
        handle_tool_errors=False,
    )
    metrics = DiscoveryMetrics()
    change_events: asyncio.Queue[object] = asyncio.Queue()

    async with MCPRuntime(metrics=metrics) as runtime:
        await runtime.register_mcp_client(
            "query-driven",
            client,
            client_server_name="everything",
            refresh=RefreshPolicy(on_query_miss=True),
        )

        # No refresh hint: query() automatically discovers the policy-enabled server.
        query_matches = await runtime.query("echo")
        print("query-driven:", [capability.name for capability in query_matches])
        print("query-driven discoveries:", metrics.discoveries["query-driven"])

        await runtime.register_mcp_client(
            "event-driven",
            client,
            client_server_name="everything",
            refresh=RefreshPolicy(on_register=True, change_events=change_events),
        )
        await change_events.put(object())
        await wait_for_discoveries(metrics, "event-driven", 2)
        event_matches = await runtime.retrieve("echo", server_id="event-driven")
        print("event-driven:", [capability.name for capability in event_matches])
        print("event-driven discoveries:", metrics.discoveries["event-driven"])

        await runtime.register_mcp_client(
            "time-based",
            client,
            client_server_name="everything",
            refresh=RefreshPolicy(on_register=True, interval=0.05, mode=RefreshMode.INCREMENTAL),
        )
        await wait_for_discoveries(metrics, "time-based", 2)
        interval_matches = await runtime.retrieve("echo", server_id="time-based")
        print("time-based:", [capability.name for capability in interval_matches])
        print("time-based discoveries:", metrics.discoveries["time-based"])


if __name__ == "__main__":
    run_smoke(main())
