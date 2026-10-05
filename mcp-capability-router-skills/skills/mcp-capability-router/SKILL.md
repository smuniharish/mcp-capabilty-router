---
name: mcp-capability-router
description: Integrate, configure, test, and troubleshoot mcp-capability-router, the asyncio Python library (imported as mcp_capability_router) that discovers the tools, resources, and prompts of many MCP servers, keeps that catalog current, retrieves the few capabilities that match each request, and calls them through a resilience pipeline with concurrency limits, interceptors, circuit breakers, retries, rate limits, and timeouts. Use when connecting LangChain, LangGraph, or Deep Agents agents to MCP servers; giving agents only the relevant MCP tools per turn; registering servers over HTTP, SSE, stdio, or in process; choosing refresh policies or keyword versus embedding retrieval; configuring resilience, health, or metrics; isolating tenants or restricting destructive tools; writing custom registries, retrievers, adapters, or interceptors; or debugging why a capability was not found, routed, or called.
license: Apache-2.0
metadata:
  author: S. Muni Harish
  version: "0.2.0"
  documentation: https://mcp-capabilty-router.readthedocs.io
---

# mcp-capability-router

mcp-capability-router sits between agents and MCP servers. An `MCPRuntime`:

- **registers** servers lazily, by ID, through FastMCP or a custom adapter;
- **discovers** their tools, resources, and prompts into a registry, writing only what
  changed;
- **retrieves** the capabilities that match a request from the registry, without
  calling any server;
- **runs** every server operation through one resilience pipeline;
- **routes** tools into LangChain agents with `CapabilityRoutingMiddleware`.

## When to use it

Use mcp-capability-router when:

- an agent needs tools from several MCP servers, or from servers with many tools, and
  should see only the relevant ones each turn;
- MCP calls need timeouts, retries, circuit breakers, rate limits, health, or metrics;
- the catalog of tools changes and must stay current without restarts;
- tenants or agents must be isolated from each other's servers.

Do not use it to build an MCP server (use FastMCP), or to call one fixed tool of one
server, where a plain `fastmcp.Client` suffices.

## Workflow

1. **Check the version.** This skill describes mcp-capability-router 0.2, which
   requires Python 3.12 or newer. Run
   `python -c "import mcp_capability_router; print(mcp_capability_router.__version__)"`,
   or install it with `pip install mcp-capability-router`. Projects on 0.1 must follow
   the upgrade notes in the
   [changelog](https://mcp-capabilty-router.readthedocs.io/en/latest/changelog/) first.
2. **Create one runtime** per tenant, agent, or trust boundary, in the application's
   lifespan, with `async with MCPRuntime(...)`.
3. **Register the servers**, each under a stable ID:
   [references/servers.md](references/servers.md).
4. **Choose refresh policies** so that the catalog is discovered and stays current:
   [references/refresh.md](references/refresh.md).
5. **Choose a retriever**: [references/retrieval.md](references/retrieval.md).
6. **Configure resilience**: a timeout, a retry policy with `is_retryable`, circuit
   breakers, and rate limits: [references/resilience.md](references/resilience.md).
7. **Connect the agent** with `CapabilityRoutingMiddleware`, `as_tool`, or direct calls
   from LangGraph nodes: [references/agents.md](references/agents.md).
8. **Secure it**: credentials, tenant isolation, and restrictions on destructive
   tools: [references/security.md](references/security.md).
9. **Observe it**: metrics, logs, and health:
   [references/observability.md](references/observability.md).
10. **Test it** with in-process servers and scripted models:
    [references/testing.md](references/testing.md).

Start new integrations from [assets/integration_template.py](assets/integration_template.py).
For custom registries, retrievers, adapters, or interceptors, read
[references/extensions.md](references/extensions.md). When something behaves
unexpectedly, use [references/troubleshooting.md](references/troubleshooting.md).

## Rules

Each rule prevents failed routes, leaked data, or calls that never recover.

1. **Import only from `mcp_capability_router`.** Every public name is exported there;
   never import from submodules or `_`-prefixed modules.
2. **Never hand-roll what the runtime does.** Do not write retry loops, circuit
   breakers, tool-loading code, or MCP clients around the runtime; configure the
   runtime instead.
3. **Discover before retrieving.** Registration connects to nothing and discovers
   nothing. Use `RefreshPolicy(on_register=True)`, call `refresh_server`, or use
   `query` with `on_query_miss`; otherwise retrieval finds nothing.
4. **Use capability IDs from the registry.** IDs have the form
   `<server_id>:<type>:<name>`; the name of a resource is its URI.
5. **Set `operation_timeout` and retry with `retry_if_exception(is_retryable)`.**
   Never retry tool execution, authentication, or invalid-request failures.
6. **Use one runtime per trust boundary**, and pass credentials through targets or
   adapter factories, never through tool arguments or prompts.
7. **Invoke agents asynchronously** with `ainvoke` or `astream`; the middleware is
   asynchronous.
8. **Close runtimes**, preferably with `async with`, so that connections, schedulers,
   and background tasks stop.
9. **Treat server content as untrusted.** Tool descriptions and results can carry
   prompt injection; register only trusted servers and restrict tools that change
   data.

## Minimal integration

<!-- test -->
```python
import asyncio

from fastmcp import FastMCP

from mcp_capability_router import MCPRuntime, RefreshPolicy

weather = FastMCP("weather")


@weather.tool
def get_forecast(city: str) -> str:
    """Get the weather forecast for a city."""
    return f"Sunny and 24 degrees in {city}"


async def main() -> None:
    async with MCPRuntime(operation_timeout=30) as runtime:
        await runtime.register_mcp(
            "weather", weather, refresh=RefreshPolicy(on_register=True)
        )
        [tool] = await runtime.retrieve("forecast for Paris", limit=1)
        message = await runtime.execute(tool.capability_id, {"city": "Paris"})
        print(tool.capability_id, "->", message.text)


asyncio.run(main())
```

```text
weather:tool:get_forecast -> Sunny and 24 degrees in Paris
```

## API quick reference

| API | Purpose |
| --- | --- |
| `MCPRuntime(*, registry=None, retriever=None, max_concurrency=16, operation_timeout=None, retry=None, rate_limiter=None, circuit_breaker=None, interceptors=(), metrics=None)` | The runtime; defaults to `InMemoryRegistry`, `KeywordRetriever`, one attempt, and in-memory circuits of 5 failures and 30 seconds per server. |
| `await runtime.register_mcp(server_id, target, *, refresh=None)` | Register a server that FastMCP reaches: URL, script path, MCP configuration, `FastMCP` server, transport, or `fastmcp.Client`. |
| `await runtime.register_server(server_id, factory, *, refresh=None)` | Register a custom `MCPAdapter` factory. |
| `await runtime.unregister_server(server_id)`, `connect(server_id)`, `reconnect(server_id)` | Manage a server's lifecycle. |
| `await runtime.refresh_server(server_id, *, mode=None, resource_ids=(), selector=None)` | Discover and reconcile one server; returns a refresh-engine `RefreshResult`, raises `RefreshError`. |
| `await runtime.refresh(*, mode=None)` | Refresh every server; returns results by server ID, raises an `ExceptionGroup` of `RefreshError`s. |
| `await runtime.retrieve(query, *, type=None, server_id=None, limit=20)` | Rank known capabilities without calling servers. |
| `await runtime.query(query, *, type=None, server_id=None, limit=20, refresh_servers=())` | Retrieve, refreshing servers first when nothing matches. |
| `await runtime.execute(capability_id, arguments=None)` | Call a tool; a `ToolMessage` with `content`, `text`, and a structured `artifact` for FastMCP. |
| `await runtime.read_resource(capability_id)`, `get_prompt(capability_id, arguments=None)` | Read a resource; render a prompt with string arguments. |
| `await runtime.as_tool(capability_id, *, name=None)` | A LangChain tool that calls a routed tool. |
| `await runtime.resolve(capability_id)`, `health(server_id)`, `close()` | Look up a capability; read a server's `HealthState`; close everything. |
| `runtime.registry`, `runtime.retriever`, `runtime.servers`, `runtime.closed` | Read-only properties. |
| `RefreshPolicy(*, on_register=False, on_query_miss=False, interval=None, change_events=None, mode=None, config=None, event_handlers=())` | When and how a server refreshes automatically; one policy can serve several servers. |
| `CapabilityRoutingMiddleware(runtime, *, limit=5, server_id=None)` | LangChain agent middleware that routes tools per model call. |
| `KeywordRetriever()`, `EmbeddingRetriever(embeddings, *, reranker=None, fetch_k=20, max_documents=50_000)` | Retrievers. |
| `InMemoryRegistry()`, `FastMCPAdapter(target)` | The default registry; the FastMCP adapter. |
| `MCPAdapter`, `CapabilityRegistry`, `CapabilityRetriever`, `Interceptor`, `Operation`, `OperationContext` | Extension contracts. |
| `Capability`, `Tool`, `Resource`, `Prompt`, `PromptArgument`, `CapabilityType`, `HealthState`, `make_capability_id(server_id, type, name)` | Capability records and enumerations. |
| `FailureCategory`, `categorize_failure(error)`, `is_retryable(error)` | Failure classification. |

Exceptions derive from `MCPCapabilityRouterError`: `ConfigurationError`,
`ServerNotFoundError`, `CapabilityNotFoundError`, `CapabilityTypeError`,
`RuntimeClosedError`, `RefreshError`, `CircuitOpenError`, and `ServerError` with
`ServerConnectionError`, `AuthenticationError`, `AuthorizationError`,
`ServerUnavailableError`, `RateLimitError`, `ProtocolError`, `DiscoveryError`,
`InvalidRequestError`, `ToolExecutionError`, `ResourceReadError`, and
`PromptRetrievalError`. Timeouts raise the built-in `TimeoutError`.

## References

| Reference | Read it when |
| --- | --- |
| [servers.md](references/servers.md) | Registering servers, authenticating, or managing connections. |
| [refresh.md](references/refresh.md) | Discovering capabilities and keeping them current. |
| [retrieval.md](references/retrieval.md) | Choosing or tuning how capabilities are ranked. |
| [resilience.md](references/resilience.md) | Configuring timeouts, retries, circuit breakers, rate limits, or interceptors. |
| [agents.md](references/agents.md) | Connecting LangChain agents, Deep Agents, multi-agent systems, or LangGraph workflows. |
| [extensions.md](references/extensions.md) | Writing a registry, retriever, adapter, or interceptor. |
| [security.md](references/security.md) | Isolating tenants, handling credentials, or restricting tools. |
| [observability.md](references/observability.md) | Adding metrics, logs, events, or health checks. |
| [testing.md](references/testing.md) | Testing an integration. |
| [troubleshooting.md](references/troubleshooting.md) | Diagnosing errors or unexpected routing. |

The full documentation is at <https://mcp-capabilty-router.readthedocs.io>.
