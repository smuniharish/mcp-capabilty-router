"""Cache read-only results, coalesce concurrent calls, and invalidate by server."""

import asyncio

from fastmcp import FastMCP

from mcp_capability_router import (
    InMemoryResultCacheStore,
    MCPRuntime,
    RefreshPolicy,
    ToolResultCache,
)


async def main() -> None:
    calls = 0
    server = FastMCP("inventory")

    @server.tool(annotations={"readOnlyHint": True})
    async def stock(sku: str) -> str:
        """Read the available stock of a product."""
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return f"{sku}: 42"

    store = InMemoryResultCacheStore(max_entries=100)
    cache = ToolResultCache(ttl=60, store=store)
    async with MCPRuntime(interceptors=[cache]) as runtime:
        await runtime.register_mcp("inventory", server, refresh=RefreshPolicy(on_register=True))
        results = await asyncio.gather(
            *(runtime.execute("inventory:tool:stock", {"sku": "A1"}) for _ in range(10))
        )
        assert len({id(result) for result in results}) == 10
        assert all(result.data == "A1: 42" for result in results)
        print(f"10 concurrent calls: {calls} server call, {len(store)} cached result")
        await runtime.execute("inventory:tool:stock", {"sku": "A1"})
        print(f"cached call: still {calls} server call")
        await cache.invalidate("inventory")
        await runtime.execute("inventory:tool:stock", {"sku": "A1"})
        print(f"after invalidation: {calls} server calls")
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
