# Discovery and refresh

The registry holds a copy of what each server offers. Refreshing a server discovers
its capabilities again and reconciles the registry: new capabilities are stored,
changed ones are replaced, and removed ones are deleted.

Refreshes run through [refresh-engine](https://refresh-engine.readthedocs.io), one
engine per server. refresh-engine fingerprints every capability, so a refresh writes
only what changed, and it never deletes anything after a failed discovery.

![Refresh flow](../assets/diagrams/refresh-flow-light.png#only-light)
![Refresh flow](../assets/diagrams/refresh-flow-dark.png#only-dark)

## Refresh manually

`refresh_server` refreshes one server and returns the refresh-engine result.
`refresh` refreshes every server concurrently:

```python
result = await runtime.refresh_server("docs")
print(result.status, result.added_count, result.modified_count, result.deleted_count)

results = await runtime.refresh()
```

`refresh_server` raises `RefreshError` when the refresh fails as a whole, for example
because discovery failed; the error is chained to the cause and carries the failed
result. Capabilities that could not be stored are reported in `result.errors` with
status `PARTIAL`, without raising. `refresh` runs every refresh to completion and
then raises an `ExceptionGroup` of the `RefreshError`s, if any.

## Refresh automatically

A `RefreshPolicy` decides when a server is refreshed without being asked:

```python
from mcp_capability_router import RefreshPolicy

policy = RefreshPolicy(on_register=True, on_query_miss=True, interval=300)
await runtime.register_mcp("docs", "https://docs.example.com/mcp", refresh=policy)
```

| Setting | Refreshes |
| --- | --- |
| `on_register` | Before `register_server` returns. If this refresh fails, the registration fails. |
| `on_query_miss` | When `query` finds no match. |
| `interval` | Every `interval` seconds, on a fixed schedule. |
| `change_events` | Whenever an item arrives on a queue or an async iterable. |

Refreshes triggered by query misses, intervals, and change events never raise: their
failures are logged on the `mcp_capability_router` logger, and the next trigger tries
again.

### Refresh on a query miss

With `on_query_miss`, a request for something that no known capability matches
refreshes the server and retrieves again. This finds tools that a server added since
the last refresh, at the cost of latency on misses only:

```python
matches = await runtime.query("merge two customer records", limit=3)
```

To refresh specific servers on a miss without setting the policy, pass
`refresh_servers=["crm"]` to `query`. When `server_id` is given, only that server is
refreshed.

### Refresh on change notifications

`change_events` accepts an `asyncio.Queue` or any async iterable. Each item triggers a
refresh; items that arrive while a refresh runs trigger one more refresh, not one
each.

MCP servers announce changes with `list_changed` notifications. Forward them to the
queue with a FastMCP message handler:

```python
import asyncio

from fastmcp import Client
from fastmcp.client.messages import MessageHandler
from mcp import types

from mcp_capability_router import RefreshPolicy


class CatalogChanges(MessageHandler):
    """Forwards the list-changed notifications of a server to a queue."""

    def __init__(self, queue: asyncio.Queue[object]) -> None:
        super().__init__()
        self._queue = queue

    async def on_tool_list_changed(
        self, message: types.ToolListChangedNotification
    ) -> None:
        self._queue.put_nowait(message)

    async def on_resource_list_changed(
        self, message: types.ResourceListChangedNotification
    ) -> None:
        self._queue.put_nowait(message)

    async def on_prompt_list_changed(
        self, message: types.PromptListChangedNotification
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

Notifications arrive while the connection is open; `on_register` opens it right away.
The same queue can receive events from elsewhere, such as a deployment webhook.

## Refresh part of a server

Refresh specific capabilities by ID, or select them with a refresh-engine selector.
Capabilities expose their `type` and `tags` to selectors:

```python
from refresh_engine import TagSelector

await runtime.refresh_server("crm", resource_ids=["crm:tool:search_customers"])
await runtime.refresh_server("crm", selector=TagSelector("tool", key="type"))
await runtime.refresh_server("crm", selector=TagSelector("billing"))
```

## Refresh modes

| Mode | Refreshes |
| --- | --- |
| `INCREMENTAL` | What was added, modified, or removed, and capabilities whose dependencies changed. The default. |
| `FULL` | Every discovered capability, whether it changed or not, plus removals; useful when something other than this runtime may have changed the registry. |
| `DEPENDENCY_AWARE` | The incremental changes, plus every capability that transitively depends on one. |
| `TARGETED` | Only the given IDs or selector, whether they changed or not. Used automatically when they are given. |

Pass a mode to `refresh_server` or `refresh`, or set `RefreshPolicy.mode` for
automatic refreshes, which cannot be targeted.

## Tune the refresh engine

`RefreshPolicy.config` takes a refresh-engine `RefreshConfig` with the concurrency,
overlap, failure, retry, and timeout settings of the server's engine.
`RefreshPolicy.event_handlers` receive the refresh lifecycle events, such as
refresh-engine's `StructlogEventHandler`. A policy can be shared by any number of
servers.

## Restarts and shared registries

Each registration keeps the fingerprints of its last refresh in memory. Its first
refresh therefore stores every capability that the server offers, and removes the
capabilities of that server that an earlier registration stored and the server no
longer offers. Later refreshes write only what changed.

With the default in-memory registry, a new process starts empty. To keep capabilities
across restarts, or to share them between processes, use a durable registry; see
[Extending the router](extending.md#registries). Let one process refresh each server
of a shared registry, and keep in mind that `unregister_server` removes the server's
capabilities for every process that shares the registry. When other processes may
change a server's capabilities, schedule `RefreshMode.FULL` refreshes to restore them.

## Dependencies between capabilities

A server can declare that a capability depends on others by listing their IDs in the
`depends_on` key of the capability's MCP `_meta`. The IDs are available as
`Capability.depends_on`, and refresh-engine refreshes dependencies first.
