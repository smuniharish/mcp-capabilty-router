---
name: mcp-capability-router
description: >-
  Use this skill when integrating, configuring, testing, or troubleshooting
  mcp-capability-router in async Python applications or any agent framework
  (LangChain, LangGraph, Deep Agents, the OpenAI SDK, or any MCP client through
  the gateway); routing relevant MCP tools per turn; serving the router as an
  MCP server; selecting refresh policies, Qdrant retrieval, caching, resilience,
  OpenTelemetry, or tenant isolation. Do not use it to build MCP servers,
  implement custom extension backends (use mcp-capability-router-extend), or
  call one fixed tool with a plain client.
license: Apache-2.0
compatibility: Python 3.12 or newer, mcp-capability-router 1.0, async application lifecycle.
metadata:
  author: S. Muni Harish
  version: "1.0.0"
  documentation: https://mcp-capabilty-router.readthedocs.io/
---

# mcp-capability-router

The router discovers MCP tools, resources, and prompts, ranks the relevant
capabilities for each request, and executes operations through a resilience
pipeline. The core needs no agent framework; integrations live in
`mcp_capability_router.integrations.<framework>` behind extras.

## Workflow

1. Verify the environment with [scripts/verify_setup.py](scripts/verify_setup.py).
   Install `mcp-capability-router`, adding extras when needed: `langchain`,
   `codemode`, `otel`, `redis`, or `all`.
2. Own one runtime per tenant or trust boundary in an async lifespan.
3. Register stable server IDs and configure refresh before retrieval:
   [references/servers.md](references/servers.md) and
   [references/refresh.md](references/refresh.md).
4. Choose BM25, dense, or hybrid ranking with `QdrantRetriever`, in process or
   on a Qdrant server: [references/retrieval.md](references/retrieval.md).
5. Configure `ResiliencePolicy` on the runtime or on individual registrations:
   [references/resilience.md](references/resilience.md).
6. Connect a framework with `route_tools` or a framework integration:
   [references/integrations.md](references/integrations.md).
7. Or serve the router to any MCP client with `as_mcp_server`:
   [references/gateway.md](references/gateway.md).
8. Restrict destructive tools and isolate credentials:
   [references/security.md](references/security.md).
9. Configure async metrics and MCP client spans:
   [references/observability.md](references/observability.md).
10. Verify with in-process servers and scripted models:
    [references/testing.md](references/testing.md).
11. Diagnose misses and failures:
    [references/troubleshooting.md](references/troubleshooting.md).

Start from [assets/integration_template.py](assets/integration_template.py).
For application-owned stores and other extension points, see
[references/extensions.md](references/extensions.md) and the companion
`mcp-capability-router-extend` skill.

## Rules

- Import core APIs from `mcp_capability_router`; framework integrations from
  `mcp_capability_router.integrations.<framework>`; tracing from
  `mcp_capability_router.otel`; conformance suites from `mcp_capability_router.testing`.
- Subclass ABCs; interceptors may also be plain async functions.
- Everything is async: `await` every runtime call and invoke agents with `ainvoke`.
- Registration is lazy unless `RefreshPolicy(on_register=True)` is supplied.
  Discover before retrieving, or use `query`/`route_tools` with `on_query_miss=True`.
- Use registry capability IDs, including resource URIs.
- Tool calls return FastMCP `CallToolResult`: use `.data`, `.structured_content`,
  and `.content`.
- Put timeouts, retries, rate limits, and circuit factories inside
  `ResiliencePolicy`. A per-server policy replaces, not merges, the default.
- Retry tool calls only when their hints establish read-only or idempotent behavior;
  do not enable `retry_unsafe_tools` without duplicate-effect protection.
- Retrieval excludes open-circuit servers by default. `include_unhealthy=True`
  overrides that; `where` filters candidates but is not an execution authorization rule.
- Cache only safe reads. Invalidate `ToolResultCache` after relevant writes and
  keep stores scoped to a trust boundary.
- Close runtimes before application-owned pools, Qdrant clients, event publishers,
  cache stores, circuit stores, and telemetry providers.
- Treat descriptions and results as untrusted. Never put credentials in prompts,
  tool arguments, or examples.

## Minimal integration

<!-- test -->
```python
import asyncio

from fastmcp import FastMCP

from mcp_capability_router import MCPRuntime, RefreshPolicy, ResiliencePolicy

weather = FastMCP("weather")


@weather.tool(annotations={"readOnlyHint": True})
async def forecast(city: str) -> str:
    """Get the weather forecast for a city."""
    return f"Sunny in {city}"


async def main() -> None:
    async with MCPRuntime(resilience=ResiliencePolicy(operation_timeout=30)) as runtime:
        await runtime.register_mcp("weather", weather, refresh=RefreshPolicy(on_register=True))
        [tool] = await runtime.route_tools("forecast for Paris", limit=1)
        result = await tool({"city": "Paris"})
        print(result.data)


asyncio.run(main())
```

```text
Sunny in Paris
```

## Verification

Run the setup script, the copied integration template, and application tests.
The [evaluation cases](evals/evals.json) cover representative tasks; the
[trigger queries](evals/trigger_queries.json) distinguish this skill from nearby tasks.