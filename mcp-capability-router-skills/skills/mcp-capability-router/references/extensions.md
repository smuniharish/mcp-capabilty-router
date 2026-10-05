# Extensions

Every extension point is a `typing.Protocol`; implement the methods without
inheriting. The runtime checks registries, retrievers, and interceptors with
`isinstance` when it receives them, and adapters when their factory creates them,
raising `ConfigurationError` on a mismatch.

| Contract | Methods | Supplied with |
| --- | --- | --- |
| `CapabilityRegistry` | `upsert_many`, `remove`, `remove_server`, `get`, `list(*, server_id=None, type=None)`, `close` | `MCPRuntime(registry=...)` |
| `CapabilityRetriever` | `retrieve(query, candidates, *, limit)` | `MCPRuntime(retriever=...)` |
| `MCPAdapter` | `connect`, `close`, `list_tools`, `list_resources`, `list_prompts`, `call_tool`, `read_resource`, `get_prompt` | `register_server(server_id, factory)` |
| `Interceptor` | `__call__(context, call_next, /)` | `MCPRuntime(interceptors=[...])` |

All methods are `async`.

## Registries

- Store and return every field of `Tool`, `Resource`, and `Prompt`, including
  `input_schema`, `output_schema`, `uri`, `mime_type`, `arguments`, `tags`,
  `metadata`, and `depends_on`; records must round-trip equal.
- Be safe under concurrency: refreshes of several servers and retrievals overlap.
- Make `list` fast; it runs before every retrieval. Filter by server and type in the
  database.
- `close` releases only the registry's resources; stored capabilities stay.
- Serialize with `dataclasses.asdict` and rebuild by `type`
  (`"tool"`, `"resource"`, `"prompt"`), converting lists back to `frozenset` and
  prompt arguments to `PromptArgument`.

## Retrievers

- Receive candidates already filtered by type and server.
- Return at most `limit` candidates, best first, and only candidates.
- Keep caches keyed by `capability_id`, and refresh them when a record changes.

Fuse rankings with reciprocal rank fusion:

```python
class HybridRetriever:
    def __init__(self, semantic: CapabilityRetriever) -> None:
        self._retrievers = (KeywordRetriever(), semantic)

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        rankings = await asyncio.gather(
            *(
                r.retrieve(query, candidates, limit=max(limit, 20))
                for r in self._retrievers
            )
        )
        scores: dict[str, float] = {}
        found: dict[str, Capability] = {}
        for ranking in rankings:
            for rank, capability in enumerate(ranking):
                key = capability.capability_id
                scores[key] = scores.get(key, 0.0) + 1 / (60 + rank)
                found[key] = capability
        return [
            found[key] for key in sorted(scores, key=lambda k: (-scores[k], k))[:limit]
        ]
```

## Adapters

- Return MCP SDK types (`mcp.types.Tool`, `Resource`, `Prompt`) from listings;
  return an empty list for kinds the server does not offer.
- Raise the router's exceptions: `ServerConnectionError` for lost connections,
  `ToolExecutionError` for tool errors, `AuthenticationError` for rejected
  credentials, and so on. Unknown exceptions are retried and counted by circuits.
- Make `connect` and `close` idempotent.
- Read credentials in the factory, which runs on first use and after reconnects.

## Interceptors

```python
async def interceptor(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    # context.server_id, context.operation, context.capability, context.arguments
    return await call_next()
```

- Return `await call_next()` exactly once, or raise.
- They run inside the concurrency limit and outside circuits and retries: once per
  operation, also for `connect` and `discover`, where `capability` is `None`.
- Raise `AuthorizationError` to reject; it is not retried and leaves circuits closed.
- Use them for policy, auditing, tracing spans, and per-server rate limits.
