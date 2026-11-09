# Gateway

`runtime.as_mcp_server(name, *, mode="search", max_results=5, **server_options)`
returns a FastMCP server that serves every registered server through the
runtime, so resilience, interceptors, caching, and metrics apply to every client.

| Mode | Client sees |
| --- | --- |
| `"search"` (default) | `search_tools(query)`, ranked by the runtime's retriever, and `call_tool(name, arguments)` |
| `"catalog"` | Every tool of every server, named `<server_id>_<tool>` |
| `"code"` (experimental, `codemode` extra) | `search`, `get_schema`, and `execute`, which runs Python calling `await call_tool(name, arguments)` in a sandbox |

Resources and prompts are listed in every mode.

```python
from fastmcp import Client

gateway = runtime.as_mcp_server("support-gateway", max_results=3)
async with Client(gateway) as client:  # in process
    found = await client.call_tool("search_tools", {"query": "refund an invoice"})
    result = await client.call_tool(
        "call_tool", {"name": "billing_issue_refund", "arguments": {"invoice_id": "inv-1"}}
    )

await gateway.run_async(transport="http", host="127.0.0.1", port=8000)  # served
```

- `server_options` go to `FastMCP`: `instructions`, `transforms` (such as
  `Namespace`), `providers`, auth, and so on.
- Serve over HTTP only behind authentication; the gateway can call every
  registered tool. Prefer one gateway per trust boundary.
- Code mode raises `ConfigurationError` without the `codemode` extra. Treat the
  sandbox as defense in depth, not as authorization: keep write policies in
  interceptors.
- Building blocks: `RouterProvider` (the runtime's capabilities as FastMCP
  components) and `RouterSearchTransform` (search mode).