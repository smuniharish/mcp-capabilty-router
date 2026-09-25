# Architecture

The router's architecture separates metadata discovery from runtime execution.
Each runtime owns its own registry, caches, locks, and background policy state.
The server factory is registered once, but a real adapter connection is created
only when the application triggers discovery, loading, or execution.

## Core lifecycle

1. `register_server(server_id, factory)` stores the adapter factory and a refresh
   policy.
2. `refresh_server(server_id, mode=...)` connects to the server and reconciles
   metadata for tools, resources, and prompts.
3. `retrieve(...)` or `query(...)` filters and ranks metadata without invoking a
   capability.
4. `load`, `execute`, `read_resource`, or `get_prompt` resolves the selected
   capability and performs the actual call.
5. `close` or the async runtime context manager shuts down all owned resources.

## Registry and retrieval

`Capability` records are immutable metadata snapshots with a stable
`capability_id`, server identity, name, description, metadata, and type.
`InMemoryRegistry` is the default runtime registry, but a custom
`CapabilityRegistry` can back discovery into another store or service.

`DeterministicRetriever` and other retriever implementations rank records based
on metadata and query terms. Retrieval is not execution: it does not call the
MCP server.

## Isolation guarantees

- A runtime is intended to be created per tenant, agent, or policy boundary.
- Registration and refresh are separate from retrieval and execution.
- One slow or failing server should degrade gracefully through the runtime's
  resilience layer rather than block unrelated routes.
- The runtime does not own transport/authentication logic; the application does.


