# Changelog

All notable changes are recorded here using
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1]

### Added

- The runtime traces every server operation with OpenTelemetry by default. The
  OpenTelemetry API is a core dependency, so tracing needs no extra; spans are
  recorded once the application configures an SDK.
- `MCPRuntime(tracing=...)` chooses the recorded spans with a `TracingMode`:
  `"router"` (the default) records one router span per operation and suppresses
  FastMCP's spans within it, `"fastmcp"` records FastMCP's spans only, `"all"`
  records both, and `"off"` records neither. Each call appears once in a trace.
- `MCPRuntime(tracer_provider=...)` and
  `OpenTelemetryInterceptor(tracer_provider=...)` record spans with an
  application-owned provider instead of the global one.
- `mcp_capability_router.otel.INSTRUMENTATION_NAME`, the scope of the router's
  spans.

### Changed

- Router spans carry the package version in their instrumentation scope.
- Dependencies are updated to their latest releases, including FastMCP 4.1.8 and
  Redis 8.1.
- The PyPI page shows the project logo.

## [1.0.0]

### Added

- A framework-agnostic core: `route_tools` returns awaitable `RoutedTool` objects
  with JSON schemas for any agent framework or application, and `resolve_tool` finds
  the tool that a model called.
- The LangChain and LangGraph integration in
  `mcp_capability_router.integrations.langchain`, through the `langchain` extra:
  routing middleware, LangChain tools, and embeddings for hybrid ranking.
- `QdrantRetriever`, the default retriever: in-process or server Qdrant with BM25,
  dense, and hybrid ranking with reciprocal rank or distribution-based fusion, and an
  `Embedder` ABC for any embedding model. `VectorStoreRetriever` accepts any
  LangChain vector store.
- An MCP gateway: `as_mcp_server` serves every registered server as one FastMCP
  server, in search, catalog, or code mode (through the `codemode` extra).
- FastMCP as the MCP client, with every client option, such as authentication,
  sampling, elicitation, roots, and progress handlers, and application-owned clients.
- Python 3.12 through 3.15 support, uv_build packaging, and Pyrefly type checking.
- ABC contracts for adapters, registries, retrievers, interceptors, and cache stores,
  with reusable async conformance suites in `mcp_capability_router.testing`.
- Refresh-engine 1.0 integration: policy-owned StateStores, per-server store factories,
  application-owned event publishers, async handlers and metrics, and fingerprints.
- Runtime-wide and per-server `ResiliencePolicy`, per-server concurrency limits,
  safe-tool retry gating, and unhealthy-server exclusion with an explicit override.
- Read-only result caching with TTL, bounded LRU storage, single-flight requests,
  per-server invalidation, and a replaceable `ResultCacheStore`.
- OpenTelemetry MCP client spans and refresh-engine metrics through the `otel`
  extra; shared purgatory circuit state through the `redis` extra.
- Examples for SQLite and PostgreSQL durable registries and StateStores, Redis
  sharing, OTLP export, Qdrant servers, hybrid retrieval, caching, the gateway, and
  LangChain and OpenAI SDK agents.
- Zensical documentation, current dependency groups, a core-only CI job, and two
  versioned Agent Skills with executable templates and evaluation cases.

## [0.2.0] - 2026-10-05

### Added

- FastMCP transports, LangChain agent middleware, refresh policies, ranked
  retrieval, classified failures, circuit health, metrics, and runnable examples.

## [0.1.0] - 2026-09-24

### Added

- Initial release.

[Unreleased]: https://github.com/smuniharish/mcp-capabilty-router/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/smuniharish/mcp-capabilty-router/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v1.0.0
[0.2.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v0.2.0
[0.1.0]: https://pypi.org/project/mcp-capability-router/0.1.0/
