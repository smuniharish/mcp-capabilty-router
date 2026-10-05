# mcp-capability-router

[![PyPI](https://img.shields.io/pypi/v/mcp-capability-router)](https://pypi.org/project/mcp-capability-router/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-capability-router)](https://pypi.org/project/mcp-capability-router/)
[![CI](https://github.com/smuniharish/mcp-capabilty-router/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/smuniharish/mcp-capabilty-router/actions/workflows/ci.yml)
[![Documentation](https://readthedocs.org/projects/mcp-capabilty-router/badge/?version=latest)](https://mcp-capabilty-router.readthedocs.io/en/latest/)
[![License](https://img.shields.io/pypi/l/mcp-capability-router)](https://github.com/smuniharish/mcp-capabilty-router/blob/HEAD/LICENSE)

**Give every agent the right MCP tools, resources, and prompts, from any number of
servers, through one resilient runtime.**

mcp-capability-router is an asyncio-first Python library that sits between your
LangChain or LangGraph agents and your MCP servers. It discovers what each server
offers, keeps that catalog current, ranks it against each request, and runs every
server operation through concurrency limits, circuit breakers, retries, rate limits,
and timeouts. An agent sees only the few tools that matter for the current turn,
however many servers and tools you register.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/smuniharish/mcp-capabilty-router/HEAD/docs/assets/diagrams/architecture-dark.png">
  <img alt="Applications and agents use the MCPRuntime, which discovers, ranks, and calls the capabilities of MCP servers through a resilience pipeline" src="https://raw.githubusercontent.com/smuniharish/mcp-capabilty-router/HEAD/docs/assets/diagrams/architecture-light.png">
</picture>

## Features

- **Only the relevant tools.** Retrieval selects the capabilities that match each
  request, so models stay fast, inexpensive, and accurate with thousands of tools.
  Keyword retrieval needs no model; embedding retrieval works with any LangChain
  embedding model and reranker.
- **Every MCP server.** Streamable HTTP, SSE, stdio, MCP configurations, and
  in-process servers through [FastMCP](https://gofastmcp.com), with lazy connections
  and automatic reconnection.
- **Always current.** Discovery runs on registration, on a schedule, on
  `list_changed` notifications, or when a query finds nothing, and writes only what
  changed, through [refresh-engine](https://refresh-engine.readthedocs.io).
- **Resilient by default.** Concurrency limits, interceptors, circuit breakers per
  server and operation, retries, rate limits, and timeouts, built on
  [purgatory](https://pypi.org/project/purgatory/),
  [tenacity](https://tenacity.readthedocs.io), and
  [aiolimiter](https://aiolimiter.readthedocs.io). Failures are classified, so a
  rejected tool call is never repeated and never opens a circuit.
- **Built for LangChain.** Agent middleware for `create_agent`, Deep Agents, and
  multi-agent systems, LangChain tools for LangGraph, and compatibility with
  LangChain's human-in-the-loop middleware.
- **Isolated and observable.** One runtime per tenant shares nothing with others.
  Health states, metrics for every operation, and standard logging.
- **Typed and extensible.** Fully type-annotated, with protocols for registries,
  retrievers, adapters, and interceptors.

## Installation

mcp-capability-router requires Python 3.12 or newer.

```bash
pip install mcp-capability-router
```

## Quick start

Register a server, let the runtime discover its capabilities, and route a request to
the right tool:

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

```text
weather:tool:get_forecast
Sunny and 24 degrees in Paris
```

The server here runs in process; a URL, a script path, or an MCP configuration works
the same way.

## Route tools for an agent

Add the middleware to a LangChain agent, and every model call receives the tools that
match the latest user message. Tool calls run through the runtime:

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

Continue with the
[getting started guide](https://mcp-capabilty-router.readthedocs.io/en/latest/getting-started/)
to add resilience, refresh policies, and observability.

## Performance

The router's overhead is small next to real MCP calls: keyword retrieval ranks 10,000
capabilities in about 10 milliseconds, and an operation passes through the whole
resilience pipeline in a few microseconds. See
[Performance](https://mcp-capabilty-router.readthedocs.io/en/latest/guides/performance/)
for the measurements and tuning advice.

## Documentation

The [documentation](https://mcp-capabilty-router.readthedocs.io/en/latest/) covers:

- [Getting started](https://mcp-capabilty-router.readthedocs.io/en/latest/getting-started/)
  and [concepts](https://mcp-capabilty-router.readthedocs.io/en/latest/concepts/)
- [Guides](https://mcp-capabilty-router.readthedocs.io/en/latest/guides/) for every
  feature, including a
  [production checklist](https://mcp-capabilty-router.readthedocs.io/en/latest/guides/production/)
- [Runnable examples](https://mcp-capabilty-router.readthedocs.io/en/latest/examples/),
  from a quick start to LangGraph workflows, Deep Agents, and PostgreSQL registries
- The [API reference](https://mcp-capabilty-router.readthedocs.io/en/latest/api/)
- The [architecture](https://mcp-capabilty-router.readthedocs.io/en/latest/architecture/overview/)
  and its guarantees

## Agent Skills

Coding agents such as Claude Code, Codex, Cursor, and GitHub Copilot can use the
mcp-capability-router
[Agent Skill](https://mcp-capabilty-router.readthedocs.io/en/latest/agent-skills/) to
integrate the library correctly:

```bash
npx skills add https://github.com/smuniharish/mcp-capabilty-router/tree/master/mcp-capability-router-skills/skills/mcp-capability-router
```

## Contributing

Contributions are welcome. Read the
[contributing guide](https://github.com/smuniharish/mcp-capabilty-router/blob/HEAD/CONTRIBUTING.md),
and report vulnerabilities as described in the
[security policy](https://github.com/smuniharish/mcp-capabilty-router/blob/HEAD/SECURITY.md).
Notable changes are listed in the
[changelog](https://github.com/smuniharish/mcp-capabilty-router/blob/HEAD/CHANGELOG.md).

## License

mcp-capability-router is licensed under the
[Apache License 2.0](https://github.com/smuniharish/mcp-capabilty-router/blob/HEAD/LICENSE).
