"""Keep capabilities up to date as servers change.

Shows refresh on registration, refresh on a query miss, event-driven refresh,
and targeted refreshes with refresh-engine selectors.
"""

import asyncio

from common import crm_server
from refresh_engine import EventKind, RefreshEvent, TagSelector

from mcp_capability_router import MCPRuntime, RefreshPolicy


async def main() -> None:
    server = crm_server()
    changes: asyncio.Queue[str] = asyncio.Queue()
    refreshed = asyncio.Event()

    def on_event(event: RefreshEvent) -> None:
        if event.kind is EventKind.REFRESH_COMPLETED:
            refreshed.set()

    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "crm",
            server,
            refresh=RefreshPolicy(
                on_query_miss=True, change_events=changes, event_handlers=(on_event,)
            ),
        )
        matches = await runtime.query("search customers", limit=1)
        print(f"query miss refreshed the server: {matches[0].capability_id}")

        def merge_customers(source_id: str, target_id: str) -> str:
            """Merge two customer records into one."""
            return f"merged {source_id} into {target_id}"

        server.add_tool(merge_customers)
        refreshed.clear()
        await changes.put("tools changed")
        await refreshed.wait()
        [merge] = await runtime.retrieve("merge two customers", limit=1)
        print(f"change event discovered: {merge.capability_id}")

        result = await runtime.refresh_server(
            "crm", selector=TagSelector("tool", key="type")
        )
        print(
            f"tools only: status={result.status} mode={result.request.mode} "
            f"refreshed={result.refreshed_count}"
        )
        result = await runtime.refresh_server("crm", resource_ids=[merge.capability_id])
        print(f"one capability: refreshed={result.refreshed_count}")
        result = await runtime.refresh_server("crm")
        print(f"nothing changed: unchanged={result.unchanged_count}")


if __name__ == "__main__":
    asyncio.run(main())
