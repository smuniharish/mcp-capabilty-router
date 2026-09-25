# Integration

Use the runtime at the application boundary. Keep agent orchestration,
transport setup, credentials, and model calls in the application while the
router owns capability metadata, selection, and lifecycle policy.

## Minimal application flow

```python
from mcp_capability_router import MCPRuntime

async with MCPRuntime(max_concurrency=8) as runtime:
    await runtime.register_server("docs", adapter_factory)
    await runtime.refresh_server("docs")

    matches = await runtime.retrieve("search documents", limit=5)
    if matches:
        result = await runtime.execute(matches[0].capability_id, {"query": "routing"})
        print(result)
```

This pattern is the supported design: register a factory, refresh metadata, then
select only the relevant capability before invoking it.

## Adapter shape

The application-supplied adapter must expose the async methods used by the
runtime, typically including the MCP operations for listing tools/resources/
prompts and invoking/calling the selected capability. The runtime is not itself a
client; it adapts the application-owned transport.

## Common integration points

- `register_server` for server factories and adapters;
- `refresh_server` for metadata reconciliation;
- `retrieve`/`query` for capability selection;
- `execute`/`read_resource`/`get_prompt` for actual calls;
- `close` or `async with MCPRuntime(...)` for teardown.

## Use with LangChain and LangGraph

Keep the model and orchestration code outside the router. The runtime returns
capability records that an application can send through a model or policy step:

```python
selected = await runtime.retrieve("read config for the build pipeline", limit=3)
# apply a model or application policy before execution
```

The repo's examples cover local MCP server smoke tests and LangGraph/DeepAgents
integration patterns. Use those examples as the source of truth before building a
custom adapter or policy layer.

## Useful source files

- [Getting started](https://mcp-capabilty-router.readthedocs.io/en/latest/guides/getting-started/)
- [Concepts](https://mcp-capabilty-router.readthedocs.io/en/latest/concepts/overview/)
- [`src/mcp_capability_router/server.py`](https://github.com/smuniharish/mcp-capability-router/blob/master/src/mcp_capability_router/server.py)
- [`src/mcp_capability_router/runtime.py`](https://github.com/smuniharish/mcp-capability-router/blob/master/src/mcp_capability_router/runtime.py)
- [Examples](https://mcp-capabilty-router.readthedocs.io/en/latest/examples/)
