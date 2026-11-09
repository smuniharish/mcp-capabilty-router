# Extending the router

Subclass the relevant abstract base class and implement its async methods.
Registries and retrievers are checked when the runtime is constructed; adapters
are checked when their factories run. Invalid objects raise `ConfigurationError`.
Interceptors may be an `Interceptor` subclass or a plain async function.

| Extension | Contract | Supplied with |
| --- | --- | --- |
| Capability metadata | `CapabilityRegistry` | `MCPRuntime(registry=...)` |
| Candidate rankings | `CapabilityRetriever` | `MCPRuntime(retriever=...)` |
| Server transport | `MCPAdapter` | `register_server(server_id, factory)` |
| Operation middleware | `Interceptor` or async function | `MCPRuntime(interceptors=[...])` |
| Cached tool results | `ResultCacheStore` | `ToolResultCache(store=...)` |
| Refresh state | refresh-engine `StateStore` | Policy or runtime store factory |

## Registries

A `CapabilityRegistry` implements `upsert_many`, `remove`, `remove_server`, `get`,
and `list`. The default `get_many` calls `get` for each ID; override it with a
batched query for database-backed stores. The default `close` is a no-op.

Store every field of `Tool`, `Resource`, and `Prompt`, including schemas, hints,
dependencies, and metadata. Support concurrent reads and writes. Make `list`
fast: it runs before retrieval. Close connections owned by your registry without
deleting durable records. Shared pools remain application-owned.

The [SQLite](../examples.md#a-durable-registry-on-sqlite) and
[PostgreSQL](../examples.md#a-registry-shared-through-postgresql) examples provide
complete implementations, including refresh StateStores. Only one process should
refresh a given server in a shared registry.

## Retrievers

Subclass `CapabilityRetriever` and implement
`async retrieve(query, candidates, *, limit)`. Return no more than `limit` records,
best first, and only records from the supplied candidates. Candidates are already
filtered by server, type, predicate, and health.

For weighted fusion, use the built-in implementation:

```python
from mcp_capability_router import (
    EmbeddingRetriever,
    HybridRetriever,
    KeywordRetriever,
    MCPRuntime,
)

retriever = HybridRetriever(
    [KeywordRetriever(), EmbeddingRetriever(embeddings)],
    weights=[1, 2],
    fetch_k=50,
)
runtime = MCPRuntime(retriever=retriever)
```

See [Retrieval](retrieval.md) for vector-store and reranker customization.

## Adapters

Subclass `MCPAdapter`; see [Write a custom adapter](servers.md#write-a-custom-adapter).
Factories take no arguments and may return an adapter directly or awaitably.
`FastMCPAdapter` can be subclassed when only one transport behavior needs changing.
Raise the router's classified exceptions so retry and circuit policies work.

## Interceptors

An interceptor receives an `OperationContext` and `call_next`, returning the result
or raising an exception. It runs once around the whole operation, outside retries
and circuit breaking but inside concurrency limits.

```python
import logging
import time
from typing import Any

from mcp_capability_router import CallNext, Interceptor, MCPRuntime, OperationContext

audit_log = logging.getLogger("audit")


class Audit(Interceptor):
    async def __call__(self, context: OperationContext, call_next: CallNext, /) -> Any:
        started = time.perf_counter()
        try:
            return await call_next()
        finally:
            audit_log.info(
                "%s on %s took %.3fs",
                context.operation,
                context.server_id,
                time.perf_counter() - started,
            )


runtime = MCPRuntime(interceptors=[Audit()])
```

Use `AuthorizationError` to reject a call. Use the built-in
`OpenTelemetryInterceptor` for tracing and `ToolResultCache` for read-only caching;
see [Observability](observability.md) and [Customization](customization.md).

## Conformance tests

The async suites in `mcp_capability_router.testing` exercise registries,
retrievers, adapters, and result-cache stores. Run them on each custom
implementation before connecting it to a runtime; see [Testing](testing.md).
