# Extension points

Use the companion `mcp-capability-router-extend` skill to implement backends.
All contracts are ABCs. Subclass `CapabilityRegistry`, `CapabilityRetriever`,
`Embedder`, `MCPAdapter`, `Interceptor`, or `ResultCacheStore`; an interceptor
can also be a plain async function.

Configure downstream objects directly:

| Library | Object | Entry point |
| --- | --- | --- |
| refresh-engine | `StateStore` | Policy `state_store` or runtime `state_store_factory(server_id)` |
| refresh-engine | `FingerprintStrategy`, `EventPublisher`, handlers, `RefreshConfig` | Policy `fingerprint`, `events`, `event_handlers`, `config` |
| refresh-engine | Async `MetricsSink` | Runtime `metrics` |
| purgatory | `AsyncCircuitBreakerFactory`, Redis unit of work | `ResiliencePolicy.circuit_breaker` |
| tenacity, aiolimiter | `AsyncRetrying`, `AsyncLimiter` | Policy `retry`, `rate_limiter` |
| FastMCP | Client options or configured `Client` | `register_mcp(**client_options)` or target |
| FastMCP | Server options, transforms, providers | `as_mcp_server(**server_options)` |
| qdrant-client | `AsyncQdrantClient` and collection | `QdrantRetriever(client=..., collection_name=...)` |
| OpenTelemetry | Tracer and meter providers | `mcp_capability_router.otel`, `OpenTelemetryMetricsSink` |
| LangChain (extra) | Embeddings, vector store, compressor | `LangChainEmbedder`, `VectorStoreRetriever` |

A policy's store takes precedence over the runtime factory. Partition durable
state by server and pair it with a durable registry. Do not share a single
unpartitioned store across servers. Application-owned objects remain
application-owned. Do not pass client options alongside a prebuilt FastMCP client.

Use `QdrantRetriever` for rank fusion and `ToolResultCache` for read-only
caching, rather than implementing these algorithms again.