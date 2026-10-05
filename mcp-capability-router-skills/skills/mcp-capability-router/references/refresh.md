# Refresh

Discovery lists a server's capabilities into the registry. The runtime runs it through
refresh-engine, one engine per server, which writes only what was added, modified, or
removed. A failed discovery never removes capabilities.

## Choose a policy

`RefreshPolicy` decides when a server refreshes without being asked:

| Setting | Use it when |
| --- | --- |
| `on_register=True` | The server must be ready when registration returns. A failed refresh fails the registration and leaves nothing registered. |
| `on_query_miss=True` | Requests may need tools that were added since the last refresh. |
| `interval=seconds` | As a safety net; every refresh lists the whole server. |
| `change_events=queue_or_async_iterable` | The server or another system announces changes. |

Without a policy, the application must call `refresh_server` or `refresh`.

```python
from mcp_capability_router import RefreshPolicy

policy = RefreshPolicy(on_register=True, on_query_miss=True, interval=900)
await runtime.register_mcp("docs", "https://docs.example.com/mcp", refresh=policy)
```

Refreshes triggered by query misses, intervals, and change events never raise; they
log failures as warnings on the `mcp_capability_router` logger.

## Forward list_changed notifications

```python
import asyncio

from fastmcp import Client
from fastmcp.client.messages import MessageHandler
from mcp import types


class CatalogChanges(MessageHandler):
    def __init__(self, queue: asyncio.Queue[object]) -> None:
        super().__init__()
        self._queue = queue

    async def on_tool_list_changed(
        self, message: types.ToolListChangedNotification
    ) -> None:
        self._queue.put_nowait(message)


changes: asyncio.Queue[object] = asyncio.Queue()
client = Client(
    "https://plugins.example.com/mcp", message_handler=CatalogChanges(changes)
)
await runtime.register_mcp(
    "plugins", client, refresh=RefreshPolicy(on_register=True, change_events=changes)
)
```

Notifications arrive only while the session is open; `on_register` opens it. Items
that arrive during a refresh trigger one more refresh, not one each.

## Manual and targeted refreshes

```python
from refresh_engine import RefreshMode, TagSelector

result = await runtime.refresh_server("crm")
await runtime.refresh_server("crm", resource_ids=["crm:tool:search_customers"])
await runtime.refresh_server("crm", selector=TagSelector("tool", key="type"))
await runtime.refresh_server("crm", mode=RefreshMode.FULL)
results = await runtime.refresh()
```

- `refresh_server` returns a refresh-engine `RefreshResult` (`status`, `added_count`,
  `modified_count`, `deleted_count`, `unchanged_count`, `errors`). It raises
  `RefreshError` when the refresh fails as a whole; the error is chained to the
  discovery failure and carries `result`.
- Capabilities expose `type` and `tags` to refresh-engine selectors.
- Modes: `INCREMENTAL` (default), `FULL` (rewrite everything), `DEPENDENCY_AWARE`, and
  `TARGETED` (implied by `resource_ids` or `selector`; not allowed in policies).
- `refresh()` refreshes all servers concurrently and raises an `ExceptionGroup` of
  `RefreshError`s after all of them finish.

## Restarts and several processes

- Each registration keeps its refresh fingerprints in memory. Its first refresh stores
  every capability and removes the server's capabilities that an earlier registration
  stored and the server no longer offers; later refreshes write only changes.
- The default registry lives in memory. Pass a durable `registry` to the runtime to
  keep capabilities across restarts or share them between processes, and let one
  process refresh each server.
- Closing a runtime leaves a durable registry's contents in place;
  `unregister_server` removes the server's capabilities for every process.
- When other processes may change a server's capabilities, schedule
  `RefreshMode.FULL` refreshes with `RefreshPolicy(mode=RefreshMode.FULL, interval=...)`.

## Tuning

`RefreshPolicy.config` takes a refresh-engine `RefreshConfig` (concurrency, overlap,
failure, retry, and timeout of the server's engine). `event_handlers` receive refresh
lifecycle events such as `REFRESH_COMPLETED`.
