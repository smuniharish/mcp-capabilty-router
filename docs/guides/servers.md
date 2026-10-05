# Connecting MCP servers

The runtime reaches MCP servers through adapters. `FastMCPAdapter` connects to every
server that [FastMCP](https://gofastmcp.com) can reach, and `register_mcp` registers
one in a single call.

## Choose a target

`register_mcp` accepts anything that a `fastmcp.Client` accepts:

| Target | Connects to |
| --- | --- |
| `"https://example.com/mcp"` | A remote server over Streamable HTTP. URLs ending in `/sse` use SSE. |
| `"./server.py"` or `"./server.js"` | A local Python or Node.js script, launched over stdio. |
| A FastMCP transport | Any transport, such as `NpxStdioTransport`, `UvxStdioTransport`, or `StreamableHttpTransport` with custom headers. |
| An MCP configuration dictionary | The server described by a standard `mcpServers` configuration. |
| A `FastMCP` server | A server in the same process, without network or subprocess. |
| A `fastmcp.Client` | A client that you configured yourself, with its own authentication and handlers. |

```python
from fastmcp.client.transports import NpxStdioTransport, UvxStdioTransport

await runtime.register_mcp("docs", "https://docs.example.com/mcp")
await runtime.register_mcp(
    "files", NpxStdioTransport("@modelcontextprotocol/server-filesystem", ["/data"])
)
await runtime.register_mcp("fetch", UvxStdioTransport("mcp-server-fetch"))
await runtime.register_mcp(
    "tickets",
    {
        "mcpServers": {
            "tickets": {
                "url": "https://tickets.example.com/mcp",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    },
)
```

Register each server under its own ID. Routing, circuit breakers, health, and
metrics are tracked per server ID, and every capability ID starts with the ID of its
server.

## Authenticate

Pass credentials through the target, never through tool arguments. For a bearer
token or OAuth, configure the client or the transport:

```python
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

await runtime.register_mcp("crm", Client("https://crm.example.com/mcp", auth=crm_token))
await runtime.register_mcp(
    "billing",
    StreamableHttpTransport(
        "https://billing.example.com/mcp", headers={"X-Tenant": tenant_id}
    ),
)
await runtime.register_mcp(
    "calendar", Client("https://cal.example.com/mcp", auth="oauth")
)
```

To add credentials to every operation, such as a short-lived token from a secret
store, use a custom adapter factory or an [interceptor](extending.md#interceptors).

## Connection lifecycle

Registration stores the adapter factory and connects to nothing. The runtime creates
the adapter and opens its connection when the first operation needs the server, and
keeps it open for every later operation.

| Call | Effect |
| --- | --- |
| `connect(server_id)` | Opens the connection now, for example to fail fast at startup. |
| `reconnect(server_id)` | Closes the connection and opens a new one with a new adapter. |
| `unregister_server(server_id)` | Stops automatic refreshes, closes the connection, and removes the capabilities of the server. |
| `close()` | Closes every server, background task, and the registry. |

When an operation fails because the connection was lost, the runtime discards the
adapter, and the next operation connects again. A connection opened on first use is
part of the operation that needed it, so it shares that operation's timeout, retries,
and circuit breaker. Explicit `connect` and `reconnect` calls run through the
resilience pipeline as `connect` operations.

## Results

`FastMCPAdapter` returns:

- from `execute`: a LangChain `ToolMessage`. Its `content` holds the content blocks
  of the result, its `text` the text of those blocks, and its `artifact` the
  structured content, as converted by LangChain's `langchain.mcp` module. A tool
  that reports an error raises `ToolExecutionError`.
- from `read_resource`: the MCP resource contents, a list of
  `TextResourceContents` and `BlobResourceContents`.
- from `get_prompt`: the MCP `GetPromptResult`, whose `messages` are ready to send
  to a model.

`langchain.mcp` is currently a beta module of LangChain.

## Write a custom adapter

Any object with the methods of the `MCPAdapter` protocol is an adapter. Register it
with a factory, which the runtime calls on first use and after every reconnect:

```python
from collections.abc import Mapping
from typing import Any

from mcp import types

from mcp_capability_router import MCPAdapter


class CatalogAdapter:
    """Exposes an internal service as MCP capabilities."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def list_tools(self) -> list[types.Tool]:
        return [
            types.Tool(
                name="lookup_product",
                description="Look up a product by SKU.",
                input_schema={
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": ["sku"],
                },
            )
        ]

    async def list_resources(self) -> list[types.Resource]:
        return []

    async def list_prompts(self) -> list[types.Prompt]:
        return []

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        return {"sku": arguments["sku"], "in_stock": True}

    async def read_resource(self, uri: str) -> Any:
        raise NotImplementedError

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> Any:
        raise NotImplementedError


assert isinstance(CatalogAdapter("https://catalog.internal"), MCPAdapter)
await runtime.register_server(
    "catalog", lambda: CatalogAdapter("https://catalog.internal")
)
```

Raise the router's [exceptions](../api/errors.md), such as `ServerConnectionError`
or `ToolExecutionError`, so that the resilience pipeline classifies failures
correctly. To change one behavior of FastMCP servers, subclass `FastMCPAdapter`
instead.
