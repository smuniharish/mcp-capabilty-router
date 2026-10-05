"""Properties of refreshes: the registry converges to what the server offers."""

from __future__ import annotations

import asyncio

from hypothesis import given
from hypothesis import strategies as st
from refresh_engine import RefreshMode

from mcp_capability_router import InMemoryRegistry, MCPRuntime
from tests.support import FakeAdapter, mcp_tool, tool

NAMES = st.sampled_from(["alpha", "beta", "gamma", "delta", "epsilon"])
CATALOGS = st.dictionaries(NAMES, st.sampled_from(["first", "second"]), max_size=5)
MODES = st.sampled_from(
    [None, RefreshMode.INCREMENTAL, RefreshMode.FULL, RefreshMode.DEPENDENCY_AWARE]
)
STEPS = st.lists(st.tuples(CATALOGS, MODES, st.booleans()), min_size=1, max_size=6)


@given(stale=st.lists(NAMES, max_size=3), steps=STEPS)
def test_refreshes_converge_the_registry_to_the_server(
    stale: list[str], steps: list[tuple[dict[str, str], RefreshMode | None, bool]]
) -> None:
    async def scenario() -> None:
        registry = InMemoryRegistry()
        # Entries left by an earlier process, for this server and for another one.
        await registry.upsert_many(
            [*(tool("s", f"old_{name}") for name in stale), tool("other", "keep")]
        )
        adapter = FakeAdapter()
        async with MCPRuntime(registry=registry) as runtime:
            await runtime.register_server("s", lambda: adapter)
            for catalog, mode, reregister in steps:
                adapter.tools = [
                    mcp_tool(name, description) for name, description in catalog.items()
                ]
                if reregister:
                    await runtime.unregister_server("s")
                    await runtime.register_server("s", lambda: adapter)
                await runtime.refresh_server("s", mode=mode)
                stored = await registry.list(server_id="s")
                assert {item.name: item.description for item in stored} == catalog
                assert await registry.get("other:tool:keep") is not None

    asyncio.run(scenario())
