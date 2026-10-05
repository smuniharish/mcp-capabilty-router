# Extending the router

Every extension point is a structural protocol: implement the methods, and the object
fits, without inheriting from anything. The runtime checks registries, retrievers, and
interceptors with `isinstance` when it receives them, and adapters when their factory
creates them, so a missing method raises `ConfigurationError` early instead of failing
in the middle of an operation.

| Extension | Contract | Supplied with |
| --- | --- | --- |
| Where capability metadata lives | `CapabilityRegistry` | `MCPRuntime(registry=...)` |
| How capabilities are ranked | `CapabilityRetriever` | `MCPRuntime(retriever=...)` |
| How a server is reached | `MCPAdapter` | `register_server(server_id, factory)` |
| What happens around every operation | `Interceptor` | `MCPRuntime(interceptors=[...])` |

## Registries

A registry stores capability records and answers lookups:

```python
from collections.abc import Iterable, Sequence

from mcp_capability_router import Capability, CapabilityRegistry, CapabilityType


class DatabaseRegistry:
    async def upsert_many(self, capabilities: Iterable[Capability]) -> None: ...

    async def remove(self, capability_id: str) -> None: ...

    async def remove_server(self, server_id: str) -> None: ...

    async def get(self, capability_id: str) -> Capability | None: ...

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> Sequence[Capability]: ...

    async def close(self) -> None: ...


assert isinstance(DatabaseRegistry(), CapabilityRegistry)
```

A durable registry lets capabilities survive restarts and lets several processes
share them: one process refreshes, and every process retrieves. Keep these rules:

- Store every field of a record, including the type-specific fields of `Tool`,
  `Resource`, and `Prompt`, and return equal records.
- Make every method safe to call concurrently: refreshes of different servers and
  retrievals run at the same time.
- Make `list` fast; it runs before every retrieval. Cache, or filter in the database
  by server and type.
- `close` releases the registry's own resources. The runtime calls it when the
  runtime closes, and leaves stored capabilities in place.

The [SQLite](../examples.md#a-durable-registry-on-sqlite) and
[PostgreSQL](../examples.md#a-registry-shared-through-postgresql) examples show
complete durable registries.

## Retrievers

A retriever ranks the candidates that the runtime passes to it. The candidates are
already filtered by type and server. This retriever fuses keyword and semantic
rankings with reciprocal rank fusion:

```python
import asyncio
from collections.abc import Sequence

from mcp_capability_router import (
    Capability,
    CapabilityRetriever,
    EmbeddingRetriever,
    KeywordRetriever,
    MCPRuntime,
)


class HybridRetriever:
    """Fuses keyword and semantic rankings with reciprocal rank fusion."""

    def __init__(self, semantic: CapabilityRetriever, *, depth: int = 20) -> None:
        self._retrievers = (KeywordRetriever(), semantic)
        self._depth = depth

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        depth = max(limit, self._depth)
        rankings = await asyncio.gather(
            *(
                retriever.retrieve(query, candidates, limit=depth)
                for retriever in self._retrievers
            )
        )
        scores: dict[str, float] = {}
        found: dict[str, Capability] = {}
        for ranking in rankings:
            for rank, capability in enumerate(ranking):
                key = capability.capability_id
                scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
                found[key] = capability
        best = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
        return [found[key] for key in best]


runtime = MCPRuntime(retriever=HybridRetriever(EmbeddingRetriever(embeddings)))
```

Return at most `limit` capabilities, best first, and only capabilities from
`candidates`.

## Adapters

An adapter connects the runtime to one server. See
[Write a custom adapter](servers.md#write-a-custom-adapter).

## Interceptors

An interceptor is an async callable that receives the operation context and a
`call_next` function. It must return the result of `await call_next()` or raise:

```python
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp_capability_router import MCPRuntime, OperationContext

audit_log = logging.getLogger("audit")


async def audit(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    started = time.perf_counter()
    try:
        return await call_next()
    finally:
        target = context.capability.capability_id if context.capability else "-"
        audit_log.info(
            "%s on %s (%s) took %.3fs",
            context.operation,
            context.server_id,
            target,
            time.perf_counter() - started,
        )


runtime = MCPRuntime(interceptors=[audit])
```

The context carries the server ID, the operation, and, for tool calls, resource reads,
and prompt renders, the capability and its arguments. Interceptors run in order, inside
the concurrency limit and outside the circuit breaker and retries, so each one sees an
operation once. Typical uses:

- **Policy**: raise `AuthorizationError` to reject an operation; it is not retried and
  does not count toward the circuit breaker. See
  [Isolation and security](security.md#restrict-tools).
- **Auditing**: record who called which tool with which arguments.
- **Tracing**: open a span around `call_next()`:

```python
from opentelemetry import trace

tracer = trace.get_tracer("mcp_capability_router")


async def traced(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    with tracer.start_as_current_span(
        f"mcp.{context.operation}", attributes={"mcp.server_id": context.server_id}
    ):
        return await call_next()
```
