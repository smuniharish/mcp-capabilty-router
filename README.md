# MCP Capability Router

[![CI](https://github.com/smuniharish/mcp-capabilty-router/actions/workflows/ci.yml/badge.svg)](https://github.com/smuniharish/mcp-capabilty-router/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-mkdocs--material-blueviolet)](docs/index.md)

**An async-first, runtime-isolated capability routing layer for LangChain, LangGraph, and
`langchain-mcp-adapters`.**

Model Context Protocol (MCP) servers can expose hundreds or thousands of tools, resources, and
prompts. Loading all of that into an agent's context on every turn is slow, expensive, and drowns
out the model's ability to pick the right capability. `mcp-capability-router` sits between your
agent and your MCP servers: it discovers and indexes capability metadata cheaply, retrieves only
the handful relevant to a query, and connects to a server lazily -- only when an operation
actually needs it.

## Why this exists

Connect an agent to a handful of MCP servers and the naive approach -- fetch every tool, resource,
and prompt from every server at startup and hand the whole catalog to the model -- works fine.
Connect it to a dozen servers, or a handful of servers that each expose hundreds of tools, and that
same approach quietly breaks in three ways at once:

1. **Every turn pays for capabilities that are never used.** Tool schemas alone can dwarf the
   actual conversation, burning context budget and latency before the model has read a single
   user message, and a bigger tool list makes the model *worse* at picking the right one, not
   better.
2. **Every server connection becomes a shared point of failure.** One slow or flaky MCP server,
   connected at startup, blocks or degrades every agent that touches the process -- and most
   teams end up hand-rolling retry loops, circuit breakers, and rate limiters around each
   server's adapter, ad hoc, in application code that has nothing to do with agent logic.
3. **The registry and the transport get welded together.** Swapping an in-memory tool list for
   Postgres, or a keyword search for vector retrieval, means touching the same code that owns
   connections, retries, and health -- so most implementations never get swapped at all.

`mcp-capability-router` exists to make the *scalable* path the default path, without reinventing
MCP transport or agent orchestration:

- **Discover cheaply, load lazily.** Registering a server stores a factory, not a connection.
  Discovery indexes metadata for tools, resources, and prompts -- all three as first-class,
  equally-routable capabilities -- so a registry can hold thousands of records while an agent
  turn only ever touches the handful `retrieve()` actually returns. A server connection is opened
  only when `execute`, `read_resource`, or `get_prompt` needs one.
- **Borrow resilience instead of reinventing it.** Retry, rate limiting, circuit breaking,
  bulkheads, timeouts, and fallbacks are wired in by default, on top of maintained libraries --
  [`refresh-engine`](https://pypi.org/project/refresh-engine/) for per-server discovery
  reconciliation, [`tenacity`](https://pypi.org/project/tenacity/) for retries, and
  [`aiolimiter`](https://pypi.org/project/aiolimiter/) for rate limiting -- so one misbehaving
  server degrades gracefully instead of taking the whole agent down, and nobody has to hand-write
  that logic per adapter again.
- **Keep every seam swappable.** The capability registry, the retriever, and the metrics hook are
  small, explicit protocols, isolated from connection and lifecycle handling. Start with the
  built-in in-memory registry and keyword retriever, then drop in Postgres, Qdrant, Ollama
  embeddings, or Prometheus later -- with zero changes to `MCPRuntime` or the resilience pipeline.
- **Stay a router, not a runtime.** This project owns capability discovery, retrieval, and
  lifecycle policy only. Transport, authentication, and the MCP client itself stay with
  `langchain-mcp-adapters` or your own adapter; model calls and agent orchestration stay with
  LangChain, LangGraph, `langgraph-swarm`, or DeepAgents. Nothing here competes with those layers.

## Installation

This package is not yet published to PyPI. Install it from source:

```bash
git clone https://github.com/smuniharish/mcp-capabilty-router.git
cd mcp-capabilty-router
pip install .
```

Optional extras add integration-specific dependencies as needed:

```bash
pip install ".[mcp]"       # langchain-mcp-adapters
pip install ".[langgraph]" # LangGraph
pip install ".[agents]"    # LangChain create_agent, DeepAgents
pip install ".[swarm]"     # langgraph-swarm
```

Requires Python 3.12.

## Quickstart

```python
import asyncio
from mcp_capability_router import CapabilityType, MCPRuntime

async def main():
    async with MCPRuntime() as runtime:
        await runtime.register_server("filesystem", my_filesystem_adapter_factory)
        await runtime.refresh_server("filesystem")

        candidates = await runtime.retrieve("read a file", type=CapabilityType.TOOL, limit=5)
        result = await runtime.execute(candidates[0].capability_id, {"path": "notes.txt"})
        print(result)

asyncio.run(main())
```

See [Getting started](docs/guides/getting-started.md) for wiring in a real
`langchain-mcp-adapters` client, and [Examples](docs/examples/overview.md) for runnable scripts
covering real MCP servers, LangGraph/DeepAgents/`langgraph-swarm` integrations, and pluggable
registries, retrievers, and metrics backends.

## Documentation

Full documentation -- architecture, concepts, guides, operations, API reference, and
troubleshooting -- lives in [`docs/`](docs/index.md) and is built with MkDocs Material.

## Contributing

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run mkdocs build
```

## License

Apache License 2.0 -- see [LICENSE](LICENSE).

