---
hide:
  - navigation
---

# mcp-capability-router

**Give every agent the right MCP tools, resources, and prompts, from any number of
servers, through one resilient runtime.**

mcp-capability-router is an asyncio-first Python library that sits between your
LangChain or LangGraph agents and your MCP servers. It discovers what each server
offers, keeps that catalog current, ranks it against each request, and runs every
server operation through concurrency limits, circuit breakers, retries, rate limits,
and timeouts. An agent sees only the few tools that matter for the current turn,
however many servers and tools you register.

![Architecture](assets/diagrams/architecture-light.png#only-light)
![Architecture](assets/diagrams/architecture-dark.png#only-dark)

<div class="grid cards" markdown>

-   :material-target:{ .lg .middle } **Only the relevant tools**

    ---

    Keyword or embedding retrieval selects the capabilities that match each
    request, so models stay fast, inexpensive, and accurate with thousands of
    tools.

-   :material-sync:{ .lg .middle } **Always current**

    ---

    Discovery runs on registration, on a schedule, on change notifications, or
    when a query finds nothing, and only what changed is written.

-   :material-shield-check-outline:{ .lg .middle } **Resilient by default**

    ---

    Every server operation runs through a concurrency limit, interceptors, a
    circuit breaker, retries, a rate limit, and a timeout.

-   :material-robot-outline:{ .lg .middle } **Built for LangChain**

    ---

    Agent middleware for `create_agent` and Deep Agents, LangChain tools for
    LangGraph, and FastMCP connectivity for every MCP transport.

</div>

## Install

```bash
pip install mcp-capability-router
```

mcp-capability-router requires Python 3.12 or newer.

## A first route

Register a server, let the runtime discover its capabilities, and route a request
to the right tool:

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


@weather.tool
def list_alerts(region: str) -> list[str]:
    """List the active severe-weather alerts of a region."""
    return []


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "weather", weather, refresh=RefreshPolicy(on_register=True)
        )
        [tool] = await runtime.retrieve("What is the forecast for Paris?", limit=1)
        print(tool.capability_id)

        message = await runtime.execute(tool.capability_id, {"city": "Paris"})
        print(message.text)


asyncio.run(main())
```

Running the program prints:

```text
weather:tool:get_forecast
Sunny and 24 degrees in Paris
```

The server here runs in process; a URL, a script path, or an MCP configuration
works the same way. Retrieval ranks the discovered metadata without calling the
server, and the call runs through the resilience pipeline.

## Route tools for an agent

Add the middleware to a LangChain agent, and every model call receives the tools
that match the latest user message:

```python
from langchain.agents import create_agent

from mcp_capability_router import CapabilityRoutingMiddleware

agent = create_agent(
    "openai:gpt-5.4-mini",
    tools=[],
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
)
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "What is the forecast for Paris?"}]}
)
```

## Where to go next

- [Getting started](getting-started.md) builds a complete integration step by step.
- [Concepts](concepts.md) explains capabilities, discovery, retrieval, and the
  resilience pipeline.
- The [guides](guides/index.md) cover each capability in depth.
- The [examples](examples.md) show every feature in a runnable program.
- The [API reference](api/index.md) documents every public name.
