# Architecture overview

```mermaid
flowchart LR
  App[LangChain / LangGraph application] --> Runtime[MCPRuntime]
  Runtime --> Registry[Capability registry]
  Runtime --> Route[Retrieve / query]
  Runtime --> Life[Lazy server lifecycle]
  Life --> Adapter[Application-owned adapter]
  Adapter --> MCP[MCP server]
  Route --> JIT[Load or execute selected capability]
```

Each runtime instance owns its servers, registry, caches, locks, semaphores, and background
tasks. No mutable process-wide singleton is used. Metadata discovery is separate from loading:
many records can remain in the registry while only a handful are selected for an agent.

## Request lifecycle

```mermaid
sequenceDiagram
  participant App
  participant Runtime
  participant Registry
  participant Adapter
  participant Server
  App->>Runtime: register_server(id, factory)
  Note over Runtime,Adapter: No connection is made
  App->>Runtime: refresh_server(id)
  Runtime->>Adapter: connect()
  Adapter->>Server: list tools/resources/prompts
  Runtime->>Registry: upsert metadata and remove stale IDs
  App->>Runtime: retrieve(query)
  Runtime->>Registry: list metadata
  Registry-->>Runtime: ranked capabilities
  App->>Runtime: execute(capability_id)
  Runtime->>Adapter: call_tool(...)
  Adapter->>Server: MCP request
  Server-->>App: result
```

## Isolation and extension points

* Create one `MCPRuntime` per tenant, agent, or policy boundary; do not share mutable runtimes
  between unrelated applications.
* Pass an implementation of `CapabilityRegistry` when metadata must live in a database or another
  process. The protocol is intentionally small.
* Implement the async adapter shape, or wrap an adapter from `langchain-mcp-adapters`. The router
  never opens a transport itself.
* `retrieve` is deterministic term matching. Applications can apply a model, policy, or graph
  node after retrieval and before execution.
