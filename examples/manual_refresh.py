"""Example K: Manual (application-triggered) refresh, without any background scheduler.

Run:
    uv run python -m examples.manual_refresh

Credential-free: demonstrates that the router never refreshes a server on its own
schedule. Applications decide exactly when to call ``refresh_server``/``refresh`` --
e.g. from a CLI command, an admin endpoint, or a LangGraph node -- and nothing changes
in the registry until that call happens.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import MCPRuntime


class VersionedAdapter:
    """An adapter whose tool list changes across versions, controlled by the test."""

    def __init__(self) -> None:
        self.version = 1

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        if self.version == 1:
            return [{"name": "search_v1", "description": "search records (v1)"}]
        return [
            {"name": "search_v1", "description": "search records (v1)"},
            {"name": "search_v2", "description": "search records (v2, faster)"},
        ]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    adapter = VersionedAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("catalog", lambda: adapter)
        await runtime.refresh_server("catalog")
        print(
            "capabilities after first manual refresh:",
            [c.name for c in await runtime.retrieve("search")],
        )

        # The server adapter now exposes a new tool, but nothing in the registry
        # changes until the application explicitly asks for a refresh again.
        adapter.version = 2
        print(
            "capabilities before the *next* manual refresh (stale by design):",
            [c.name for c in await runtime.retrieve("search")],
        )

        await runtime.refresh_server("catalog")
        print(
            "capabilities after second manual refresh:",
            [c.name for c in await runtime.retrieve("search")],
        )

        # ``mode=`` exposes refresh-engine's own RefreshMode values for one-off calls:
        # INCREMENTAL only re-touches capabilities that actually changed since the last
        # refresh, instead of FULL's default re-touch-everything reconciliation.
        from refresh_engine import RefreshMode

        result = await runtime.refresh_server("catalog", mode=RefreshMode.INCREMENTAL)
        print("incremental refresh status:", result.status)


if __name__ == "__main__":
    asyncio.run(main())
