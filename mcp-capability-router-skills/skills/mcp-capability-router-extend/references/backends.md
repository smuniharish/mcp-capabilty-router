# Backend contracts

| Contract | Required async methods |
| --- | --- |
| `CapabilityRegistry` | `upsert_many`, `remove`, `remove_server`, `get`, `list` |
| `CapabilityRetriever` | `retrieve(query, candidates, *, limit)` |
| `MCPAdapter` | `connect`, `close`, three list methods, `call_tool`, `read_resource`, `get_prompt` |
| `Interceptor` | `__call__(context, call_next, /)` |
| `ResultCacheStore` | `get`, `set(key, value, ttl)`, `clear(prefix="")` |
| refresh-engine `StateStore` | `load_all`, `transaction` |
| refresh-engine `StateTransaction` | `apply_changes(puts, deletes, /)` |
| refresh-engine `FingerprintStrategy` | `fingerprint(snapshot, /)` |

`CapabilityRegistry.get_many` defaults to repeated `get`; override for efficient
batching. `close` defaults to a no-op on registries and cache stores. Contract
suites run async scenarios inside synchronous tests; factories must return fresh,
empty instances. Create loop-bound pools inside the factory's scenario loop.

Serialize every capability type, schemas, tags, dependencies, annotations, and
metadata. Unknown IDs return `None`; empty operations are safe. Removal is
idempotent. Runtime shutdown must not truncate durable tables.

State transactions atomically apply both puts and deletes. Preserve every
`ResourceState` field, including fingerprint algorithm and value, version,
cheap indicator, metadata, dependencies, and timezone-aware refresh timestamp.
Use `(server_id, resource_id)` keys when servers share a table.

Supply configured LangChain `VectorStore` and compressors to `EmbeddingRetriever`,
a purgatory factory to `ResiliencePolicy`, and a configured FastMCP `Client` or
constructor options to `register_mcp`. Close shared pools and clients after their
consumers. The router does not require an XAI dependency.
