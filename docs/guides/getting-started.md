# Getting started

This guide takes an application from installation to its first routed MCP call. The runtime is
not an MCP client or agent framework: your application supplies an adapter, model, and policy.

## Install

The supported development workflow uses [uv](https://docs.astral.sh/uv/):

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run pyrefly check
uv run mkdocs build
```

For runtime use:

```powershell
uv add mcp-capability-router
uv add mcp-capability-router --optional mcp
```

For the examples in this repository:

```powershell
uv sync --extra mcp --extra agents --extra openai --extra swarm
```

## Configure secrets safely

Use environment variables or your secret manager. Never put keys in source, documentation,
command history, screenshots, or committed `.env` files:

```powershell
$env:MODEL_PROVIDER = "openai-compatible"
$env:MODEL_NAME = "your-model"
$env:MODEL_BASE_URL = "https://your-endpoint/v1"
$env:MODEL_API_KEY = "set-this-in-your-secret-manager"
```

The checked-in `.env.example` contains placeholders only. The router never logs model keys,
authorization headers, or MCP credentials.

## Minimal application

Register an adapter factory rather than a raw MCP transport. Registration is lazy: it stores
metadata and does not connect until discovery, loading, or execution requires the server.

```python
from mcp_capability_router import MCPRuntime

async with MCPRuntime(max_concurrency=8) as runtime:
    await runtime.register_server("docs", adapter_factory)
    await runtime.refresh_server("docs")
    matches = await runtime.retrieve("search documents", limit=3)
    if matches:
        result = await runtime.execute(matches[0].capability_id, {"query": "routing"})
```

The factory must produce an object with async `connect`, `close`, `list_tools`,
`list_resources`, `list_prompts`, `call_tool`, `read_resource`, and `get_prompt` methods.
Duck-typing that shape is enough; subclassing the optional `MCPAdapterBase` abstract base
class is not required but gives you an enforced template, since a subclass that forgets a
method fails loudly at instantiation time instead of silently no-op-ing the first time the
runtime calls it. `examples/real_filesystem_mcp.py` is a complete executable real-server
smoke test, and `examples/public_api_overrides.py`'s `FakeAdapter` shows the `MCPAdapterBase`
subclassing style.

## Capability lifecycle

1. `register_server` stores a server factory.
2. `refresh_server` connects once and reconciles Tools, Resources, and Prompts.
3. `retrieve` filters and ranks metadata without loading every capability.
4. The application applies policy or an LLM to the small candidate set.
5. `load`, `execute`, `read_resource`, or `get_prompt` performs the selected operation.
6. `close` disconnects only resources owned by that runtime.

Use `async with MCPRuntime(...)` so shutdown is deterministic.

## Real MCP adapter hook

Keep transport and credentials in the application. The exact adapter constructor depends on the
`langchain-mcp-adapters` release and transport, so consult that package's documentation:

```python
# Application code; illustrative hook, not run by the docs build.
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/safe/root"],
            "transport": "stdio",
        }
    }
)

# Register the official client directly; the runtime owns its generic bridge:
await runtime.register_mcp_client("filesystem", client, client_server_name="filesystem")
```

Do not hard-code tokens, file paths, or server commands in a deployed application. The router
does not authenticate or verify an external MCP server.

For executable direct-client smoke tests using the official Everything, Git, and Fetch MCP
server launchers, including their prerequisites and safety boundaries, see
[Examples](../examples/overview.md#run-the-official-server-smoke-tests).

## LangChain and LangGraph hooks

Use retrieved records as input to an application-owned model or tool-selection step:

```python
# LangChain hook: keep model construction and credentials in your application.
from langchain_core.messages import HumanMessage

selected = await runtime.retrieve("summarize a report")
decision = await model.ainvoke([HumanMessage(content=str(selected))])


# LangGraph hook: a node can call retrieve/execute and return state updates.
async def route_node(state):
    matches = await runtime.query(state["request"], refresh_servers=["filesystem"])
    return {"candidates": [item.capability_id for item in matches]}
```

These snippets describe integration boundaries. The repository's Filesystem and Playwright
examples exercise real local MCP servers; model-backed examples require the application's own
model configuration and are not part of normal CI.
