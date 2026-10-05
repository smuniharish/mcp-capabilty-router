# Servers

## Register a server

`register_mcp(server_id, target, *, refresh=None)` accepts anything a
`fastmcp.Client` accepts:

| Target | Connects to |
| --- | --- |
| `"https://host/mcp"` | Streamable HTTP; URLs ending in `/sse` use SSE. |
| `"./server.py"`, `"./server.js"` | A local script over stdio. |
| `NpxStdioTransport(package, args)`, `UvxStdioTransport(tool)`, `StreamableHttpTransport(url, headers=...)` | A FastMCP transport from `fastmcp.client.transports`. |
| `{"mcpServers": {...}}` | A standard MCP configuration. |
| `FastMCP(...)` | An in-process server; ideal for tests. |
| `fastmcp.Client(...)` | A client with its own `auth`, `timeout`, or `message_handler`. |

```python
from fastmcp import Client
from fastmcp.client.transports import NpxStdioTransport

from mcp_capability_router import MCPRuntime, RefreshPolicy

async with MCPRuntime(operation_timeout=30) as runtime:
    policy = RefreshPolicy(on_register=True)
    await runtime.register_mcp(
        "docs", Client("https://docs.example.com/mcp", auth=token), refresh=policy
    )
    await runtime.register_mcp(
        "files",
        NpxStdioTransport("@modelcontextprotocol/server-filesystem", ["/data"]),
        refresh=policy,
    )
```

## Server IDs

- 1 to 64 letters, digits, hyphens, or underscores, starting with a letter or digit;
  `ConfigurationError` otherwise.
- Unique per runtime; registering an ID twice raises `ConfigurationError`.
- Prefer hyphens to underscores: routed tool names are `<server_id>_<tool>`, and IDs
  such as `crm` and `crm_eu` make some names ambiguous.
- Register each server under its own ID, even when one MCP configuration lists
  several; routing, circuits, health, and metrics are per ID.

## Connections

- Registration stores a factory and connects to nothing. The first operation creates
  the adapter and opens its session, which then stays open.
- `connect(server_id)` opens it now, for example to fail fast at startup.
- A lost connection discards the adapter; the next operation reconnects.
  `reconnect(server_id)` forces a new adapter.
- `unregister_server(server_id)` stops automatic refreshes, closes the connection, and
  removes the server's capabilities.

## Results of FastMCPAdapter

| Call | Returns |
| --- | --- |
| `execute` | A LangChain `ToolMessage`: `content` blocks, `text`, and the structured content in `artifact["structured_content"]`. FastMCP wraps non-object results as `{"result": ...}`. |
| `read_resource` | A list of `mcp.types.TextResourceContents` and `BlobResourceContents`. |
| `get_prompt` | `mcp.types.GetPromptResult`; prompt arguments must be strings. |

A tool that reports an error raises `ToolExecutionError`. HTTP 401 raises
`AuthenticationError`, 403 `AuthorizationError`, 429 `RateLimitError`, and 5xx
`ServerUnavailableError`.

## Custom adapters

Implement the `MCPAdapter` protocol (`connect`, `close`, `list_tools`,
`list_resources`, `list_prompts`, `call_tool`, `read_resource`, `get_prompt`) with
MCP SDK types for listings, and register a factory:

```python
await runtime.register_server("catalog", lambda: CatalogAdapter(base_url))
```

The factory runs on first use and after every reconnect, so it can read fresh
credentials. Raise the router's exceptions so that failures are classified. To change
one behavior of FastMCP servers, subclass `FastMCPAdapter`.
