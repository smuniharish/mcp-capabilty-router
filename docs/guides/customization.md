# Downstream customization

The router accepts application-owned downstream objects instead of hiding their
configuration behind another settings layer.

## Extension inventory

| Dependency | Customization | Router entry point |
| --- | --- | --- |
| refresh-engine | `StateStore`, including durable stores | `RefreshPolicy.state_store` or `MCPRuntime.state_store_factory` |
| refresh-engine | Async `FingerprintStrategy` | `RefreshPolicy.fingerprint` |
| refresh-engine | `EventPublisher`, async handlers | `RefreshPolicy.events` and `event_handlers` |
| refresh-engine | Concurrency, overlap, failures, retries, timeouts | `RefreshPolicy.config` (`RefreshConfig`) |
| refresh-engine | Async `MetricsSink` | `MCPRuntime(metrics=...)` |
| purgatory | Thresholds, TTL, exclusions, unit of work | `ResiliencePolicy.circuit_breaker` |
| tenacity | Attempt limits, waits, retry callbacks and predicates | `ResiliencePolicy.retry` (`AsyncRetrying`) |
| aiolimiter | Quotas and periods | `ResiliencePolicy.rate_limiter` (`AsyncLimiter`) |
| FastMCP | Auth, timeout, roots, sampling, elicitation, progress and message handlers | `register_mcp(..., **client_options)` or a prebuilt `Client` |
| FastMCP | Server name, instructions, auth, transforms, providers | `as_mcp_server(..., **server_options)` |
| qdrant-client | `AsyncQdrantClient`, collection, fusion, BM25 parameters | `QdrantRetriever(client=..., collection_name=..., fusion=...)` |
| Any embedding model | `Embedder` subclass | `QdrantRetriever(embedder=...)` |
| LangChain (`langchain` extra) | Embeddings, `VectorStore`, document compressor | `LangChainEmbedder`, `VectorStoreRetriever` |
| LangChain (`langchain` extra) | Model, tool policy, agent middleware | Application-owned agent plus `CapabilityRoutingMiddleware` |
| OpenTelemetry | Tracer, meter, providers and exporters; which spans are recorded | `MCPRuntime(tracing=..., tracer_provider=...)`, `OpenTelemetryInterceptor`, and refresh-engine metrics sink |

`mcp`, `httpx2`, and `anyio` support transport types and error handling. These are
implementation dependencies rather than independently configurable services. Logging uses the standard Python logger.

## Ownership

The runtime closes its registry and retriever, adapters from registered factories,
and clients it creates. A prebuilt FastMCP `Client`, `AsyncQdrantClient`, external vector store,
refresh StateStore, event publisher, cache store, circuit factory, Redis client,
or telemetry provider remains application-owned. Close these after all runtimes
using them have stopped. An `AsyncExitStack` is useful for shared resources.

## FastMCP client options

```python
await runtime.register_mcp(
    "catalog",
    "https://catalog.example.com/mcp",
    timeout=30,
    roots=["/srv/catalog"],
)
```

Keyword options are forwarded to FastMCP's `Client` constructor without narrowing its
extension surface. Do not combine client options with a prebuilt `Client`:
configure that client directly instead.

## Result caching

```python
from mcp_capability_router import InMemoryResultCacheStore, MCPRuntime, ToolResultCache

store = InMemoryResultCacheStore(max_entries=1024)
cache = ToolResultCache(ttl=60, store=store)
runtime = MCPRuntime(interceptors=[cache])
await cache.invalidate("catalog")
```

Only read-only tools are cached by default. Override `cacheable` only for tools
whose results can safely be reused. Errors and `None` are not cached. Concurrent
identical calls share one in-flight request, and every caller receives its own copy
of the result. The cache runs outside circuit breaking, allowing a cached
read while the server is down.

Subclass `ResultCacheStore` to replace storage; the Redis
[example](../examples.md#redis-shared-state) uses JSON serialization and Redis TTLs.
Scope caches to a tenant or trust boundary and invalidate after relevant writes.
Neither TTL nor caching provides an authorization boundary.
