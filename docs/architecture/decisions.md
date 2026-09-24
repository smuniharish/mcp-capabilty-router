# Architecture decision records

## ADR-001: adapter-owned MCP connectivity

**Context.** Applications already choose their MCP transport, authentication configuration, and
client implementation. Reimplementing those concerns in the router would introduce a second MCP
client stack and split ownership of connection failures and credentials.

**Decision.** The runtime delegates transport, authentication, and protocol details to
`langchain-mcp-adapters` or an application-provided adapter. It owns registration, discovery
reconciliation, retrieval, loading, and lifecycle coordination. A
`MultiServerMCPClient` can be registered directly with `register_mcp_client`; no
Playwright-, filesystem-, or transport-specific client exists in this package.

**Consequences.** The router stays interoperable with the official adapter and does not own
server processes, credentials, or an MCP protocol implementation. Applications must configure
and diagnose their selected client and transport.

## ADR-002: capabilities are first-class

**Context.** MCP exposes tools, resources, and prompts. Treating only tools as routable loses
useful server functionality; flattening their behavior risks calling an operation with the wrong
semantics.

**Decision.** Tools, resources, and prompts share the `Capability` contract but retain
type-specific semantics. Retrieval and registry operations accept all three types, while
execution APIs guard the requested capability type.

**Consequences.** Selection can use one metadata and retrieval model, while `execute`,
`read_resource`, and `get_prompt` remain explicit about the requested operation.

## ADR-003: instance-scoped mutable state

**Context.** A process can host multiple agents or tenants that must not share cached
capabilities, connections, limits, or health state.

**Decision.** Registries, loaders, refresh tasks, circuit breakers, locks, and health are owned
by a runtime instance. There are no process-global caches or connection managers.

**Consequences.** Tests are deterministic and independent application boundaries can coexist in
one process. Callers must create and close a runtime for each intended isolation boundary.

## ADR-004: lazy connection and explicit refresh

**Context.** Connecting to every configured server at startup is expensive and may expose a
large, irrelevant capability set to an agent.

**Decision.** Server registration stores a factory only. Discovery is explicit and a successful
refresh reconciles metadata with the latest server response.

**Consequences.** Startup remains lazy and agents can retrieve a small candidate set instead of
receiving every configured capability. A failed discovery leaves the last successfully
reconciled metadata intact; applications must schedule refreshes appropriate to their servers.
