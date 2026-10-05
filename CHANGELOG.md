# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-05

This release rebuilds the router on FastMCP, LangChain, refresh-engine, tenacity,
purgatory, and aiolimiter, for every MCP transport, LangChain agent middleware, and a
smaller, clearer API. It contains breaking changes; read the
[upgrade notes](#upgrading-from-010) first.

### Added

- Support for Python 3.13 and 3.14.
- `MCPRuntime.register_mcp`, which registers any server that FastMCP can reach: URLs
  over Streamable HTTP or SSE, Python and Node.js scripts, MCP configurations,
  in-process `FastMCP` servers, transports, and preconfigured clients.
  `FastMCPAdapter` and the `FastMCPTarget` type support it.
- `CapabilityRoutingMiddleware`, which gives LangChain agents, including Deep Agents
  and multi-agent systems, the tools that match each turn, and
  `MCPRuntime.as_tool`, which turns a routed tool into a LangChain tool. Failures and
  timeouts of routed tools reach the model as error messages.
- Refresh policies with `on_register`, `on_query_miss`, `interval`, and
  `change_events` triggers, refresh modes, selectors, and event handlers, through
  refresh-engine. A failed discovery never removes capabilities, and the first
  refresh of a registration removes capabilities that the server no longer offers
  from durable registries.
- A configurable resilience pipeline around every server operation:
  `max_concurrency`, `interceptors`, circuit breakers per server and operation with
  purgatory, shareable through Redis, retries with tenacity, rate limits with
  aiolimiter, and `operation_timeout`.
- Failure classification with `FailureCategory`, `categorize_failure`, and
  `is_retryable`, and an exception hierarchy rooted at `MCPCapabilityRouterError`.
- `HealthState` and `MCPRuntime.health`, derived from the circuit breakers.
- Metrics for every operation, retry, and circuit transition, and refresh-engine's
  refresh metrics, through any refresh-engine `MetricsSink`.
- `KeywordRetriever`, which matches words, identifiers, prefixes, and shared stems,
  ranks exact matches above partial ones, and weighs rare words more.
- `EmbeddingRetriever`, which ranks with any LangChain embedding model, embeds each
  capability once, bounds its vectors, and accepts any LangChain document compressor
  as a reranker.
- Capability records with titles, tags, MCP annotations and metadata, dependencies,
  tool input and output schemas, resource MIME types, and prompt arguments.
- Type information for the package, an Agent Skill, a documentation site, and
  examples whose output is verified in continuous integration.

### Changed

- **Breaking:** Python 3.12 or newer is required, and the runtime dependencies are
  `aiolimiter`, `anyio`, `fastmcp`, `httpx2`, `langchain[mcp]`, `langchain-core`,
  `mcp`, `numpy`, `purgatory`, `refresh-engine`, and `tenacity`. The optional
  dependency groups are gone; everything the router needs is always installed.
- **Breaking:** every public name is imported from `mcp_capability_router`.
  Extension points are protocols, and the abstract base classes are gone.
- **Breaking:** `register_mcp_client()` is replaced by `register_mcp()`, and
  `register_server()` takes an adapter factory and an optional `RefreshPolicy`.
- **Breaking:** `connect()` and `reconnect()` return `None`. `refresh()` returns the
  result of each server and raises an `ExceptionGroup` of `RefreshError`s when some
  servers fail.
- **Breaking:** `execute()` returns a LangChain `ToolMessage` for FastMCP servers,
  `read_resource()` the MCP resource contents, and `get_prompt()` the MCP prompt
  result.
- **Breaking:** capability IDs have the form `<server_id>:<type>:<name>`, and server
  IDs are limited to letters, digits, hyphens, and underscores.
- Importing the package no longer imports FastMCP or the MCP SDK.

### Removed

- `LangChainMCPAdapter`; use `register_mcp()` or `FastMCPAdapter`.
- `DeterministicRetriever`; use `KeywordRetriever`.
- `CapabilityEmbedder`, `CapabilityReranker`, and `RerankingRetriever`; use
  `EmbeddingRetriever` with a LangChain embedding model and an optional reranker.
- `CircuitBreaker`, `CircuitState`, and `with_timeout`; configure the runtime's
  `circuit_breaker` and `operation_timeout` instead.
- `MetricsHook` and `MetricsHookBase`; pass a refresh-engine `MetricsSink` as
  `metrics`.
- `CapabilityRegistryBase`, `CapabilityRetrieverBase`, and `MCPAdapterBase`;
  implement the `CapabilityRegistry`, `CapabilityRetriever`, and `MCPAdapter`
  protocols.
- `MCPRuntime.load()`.

### Upgrading from 0.1.0

| 0.1.0 | 0.2.0 |
| --- | --- |
| `pip install "mcp-capability-router[mcp]"` | `pip install mcp-capability-router` |
| `await runtime.register_mcp_client(...)` | `await runtime.register_mcp(server_id, target)` |
| `LangChainMCPAdapter(...)` | `FastMCPAdapter(target)` |
| `DeterministicRetriever()` | `KeywordRetriever()` |
| `RerankingRetriever(...)` | `EmbeddingRetriever(embeddings, reranker=...)` |
| `CircuitBreaker(...)` | `MCPRuntime(circuit_breaker=AsyncCircuitBreakerFactory(...))` |
| `with_timeout(...)` | `MCPRuntime(operation_timeout=...)` |
| `MetricsHook` | `MCPRuntime(metrics=...)` with a refresh-engine `MetricsSink` |
| Subclassing `*Base` classes | Implementing the matching protocol |

## [0.1.0] - 2026-09-24

Initial release.

[Unreleased]: https://github.com/smuniharish/mcp-capabilty-router/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v0.2.0
[0.1.0]: https://pypi.org/project/mcp-capability-router/0.1.0/
