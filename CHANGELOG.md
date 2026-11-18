# Changelog

All notable changes are recorded here using
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## [2.0.1]

### Changed

- Simplified public architecture diagrams and lifecycle explanations while retaining
  integration and operational contracts.
- Clarified lazy connections and the default capture of tool content in traces.
- Aligned package metadata and installation guidance with the supported Python
  3.12–3.14 range required by RetrievalLoom.
- Rechecked declared dependencies against stable PyPI releases and corrected skill
  compatibility metadata.
- Documented the unresolved Deep Agents and refresh-engine dependency conflict.
- Made the OpenTelemetry example's concurrent sibling spans print in a stable order.

## [2.0.0]

### Changed

- **Breaking:** `LoomRetriever` replaces `QdrantRetriever` as the default
  retriever. It ranks with a [RetrievalLoom](https://pypi.org/project/retrievalloom/)
  engine: BM25 without arguments, BM25 and dense rankings fused by reciprocal rank
  fusion with an `Embedder`, and optionally reordered by a RetrievalLoom reranker.
  Existing keyword matching behavior is retained.
- **Breaking:** `RetrievalMode` and `Fusion` are removed. The ranking methods and
  their fusion are configured with a RetrievalLoom `EngineConfig` through
  `LoomRetriever(config=...)`.
- **Breaking:** Python 3.15 is no longer supported.
- The retriever conformance suite in `mcp_capability_router.testing` closes the
  retriever after each test.
- Example 18 is now `18_durable_index.py`: a capability index kept in a data
  directory, or in a Qdrant server, that a restarted process does not embed again.
- Examples 08 and 18 load a LangChain embedding model or a local sentence-transformers
  model, and example 08 an optional cross-encoder reranker.
- `qdrant-client` is no longer a direct dependency; RetrievalLoom installs it.
- Minimum dependency versions are raised to their latest compatible releases:
  fastmcp 4.2.1, httpx2 2.16.2, refresh-engine 1.0.1, langchain-core 1.8.2,
  zensical 0.1.2, deepagents 0.7.39, langchain-openai 1.8.1, langgraph 1.2.22,
  openai 3.55.0, and the build backend uv-build 0.13.9.
- The architecture and retrieval documentation describe the runtime's behavior at
  the level that integrations need, and the refresh flow diagram is simplified.

### Added

- The Agent Skills guide lists the skills that RetrievalLoom, refresh-engine,
  FastMCP, and LangChain publish, and how to install them.
- `LoomRetriever(reranker=...)` reorders the fused matches, for example with a
  cross-encoder.
- `LoomRetriever(resources=EngineResources(data_dir=...))` keeps the index in files
  across restarts.
- A `models` dependency group with sentence-transformers and CPU-only PyTorch for
  the examples, benchmarks, and live tests that use local models.

### Migration

| 1.x | 2.0 |
| --- | --- |
| `QdrantRetriever()` | `LoomRetriever()` |
| `QdrantRetriever(embedder=e)` | `LoomRetriever(embedder=e)` |
| `QdrantRetriever(embedder=e, mode="dense")` | `LoomRetriever(embedder=e, config=...)` with keyword ranking disabled |
| `QdrantRetriever(client=c, collection_name=n)` | `LoomRetriever(components=Components(vector_store=QdrantVectorStore(client=c)), collection=n)` |
| `max_points=...` | `max_documents=...` |
| `prefetch_limit=...` | `fetch_limit=...` |
| `fusion=...`, `rrf_k=...` | `config=EngineConfig(...)` |

The RetrievalLoom engine starts with the first query and takes a second or two to
inspect the host, so create one runtime per process rather than per request.
Indexes written by `QdrantRetriever` are not read by `LoomRetriever`; capabilities
are indexed again on first sight.

## [1.0.2]

### Added

- Router tool spans capture arguments and results by default. Set
  `capture_tool_content=False` on `MCPRuntime` or an explicitly supplied
  `OpenTelemetryInterceptor` to omit them.

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

[2.0.0]: https://github.com/smuniharish/mcp-capabilty-router/compare/v1.0.2...v2.0.0
[1.0.2]: https://github.com/smuniharish/mcp-capabilty-router/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/smuniharish/mcp-capabilty-router/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v1.0.0
[0.2.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v0.2.0
[0.1.0]: https://pypi.org/project/mcp-capability-router/0.1.0/
