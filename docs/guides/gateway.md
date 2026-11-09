# MCP gateway

`as_mcp_server` serves the router as one MCP server. Any MCP client, such as an IDE,
a desktop assistant, or an agent framework that speaks MCP, then reaches every
registered server through the runtime, so the resilience pipeline, interceptors,
caching, and metrics apply to every call.

```python
gateway = runtime.as_mcp_server("support-gateway", max_results=5)
await gateway.run_async(transport="http", host="127.0.0.1", port=8000)
```

`gateway` is a FastMCP server: run it over any FastMCP transport, mount it in an
ASGI application, or connect a FastMCP `Client` to it in process. Keyword arguments
other than `mode` and `max_results` go to `FastMCP`, such as `instructions`, `auth`,
`transforms`, and `providers`.

## Modes

| Mode | The client sees |
| --- | --- |
| `"search"`, the default | Two tools: `search_tools(query)`, which ranks the tools with the runtime's retriever and returns at most `max_results`, and `call_tool(name, arguments)`, which calls a found tool |
| `"catalog"` | Every tool of every server, named `<server_id>_<tool>` |
| `"code"`, experimental | `search`, `get_schema`, and `execute`, which runs Python that calls tools with `await call_tool(name, arguments)` in a sandbox |

Resources and prompts of every server are listed in every mode: prompts named
`<server_id>_<prompt>`, resources under their own URIs. The search mode
keeps the client's context small however many tools are registered; the catalog
mode suits clients that filter tools themselves.

```python
from fastmcp import Client

async with Client(runtime.as_mcp_server("support-gateway")) as client:
    found = await client.call_tool("search_tools", {"query": "refund an invoice"})
    result = await client.call_tool(
        "call_tool",
        {"name": "billing_issue_refund", "arguments": {"invoice_id": "inv-1"}},
    )
```

## Code mode

In code mode a model writes one script that searches tools, reads their schemas, and
chains several calls in one round trip; intermediate results never pass through its
context. It needs the `codemode` extra:

```bash
pip install "mcp-capability-router[codemode]"
```

Code mode is experimental in FastMCP. Without the extra, `as_mcp_server(mode="code")`
raises `ConfigurationError`. Treat the sandbox as defense in depth, not as
authorization: keep write policies in interceptors.

## Security

The gateway can call every tool of every registered server.

- Serve it over HTTP only behind authentication, for example with FastMCP's `auth`.
- Serve one gateway per tenant or trust boundary, from that boundary's runtime.
- Enforce policies in [interceptors](security.md#restrict-tools); they apply to
  gateway calls like to any other.

## Building blocks

`RouterProvider` offers the runtime's capabilities as FastMCP components, and
`RouterSearchTransform` implements the search mode. Add them to a FastMCP server of
your own to combine the router with other tools. See the [API reference](../api/gateway.md).