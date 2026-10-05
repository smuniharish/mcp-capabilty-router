# Concepts

This page explains the building blocks of mcp-capability-router and how they work
together.

## Capabilities

An MCP server offers three kinds of capabilities:

| Type | What it is | Used with |
| --- | --- | --- |
| **Tool** | A function that a model can call. | `MCPRuntime.execute` |
| **Resource** | A piece of data that the application can read, identified by a URI. | `MCPRuntime.read_resource` |
| **Prompt** | A prompt template that the application can render with arguments. | `MCPRuntime.get_prompt` |

The runtime records each capability as an immutable `Tool`, `Resource`, or `Prompt`
with its name, title, description, tags, MCP annotations, and type-specific details
such as the input schema of a tool. Every capability has an ID of the form
`<server_id>:<type>:<name>`, where the name of a resource is its URI:

```text
docs:tool:search_docs
docs:resource:docs://guides/getting-started
docs:prompt:summarize
```

Tags come from the `fastmcp.tags` metadata convention that FastMCP servers follow.
Annotations, such as `read_only_hint` and `destructive_hint`, are kept in
`metadata["annotations"]` so that policies can act on them, and the MCP `_meta` of a
capability is kept in `metadata["meta"]`.

## Servers and adapters

A server is registered under an ID with an **adapter factory**. The adapter is the
connection to the server: `FastMCPAdapter` reaches every server that FastMCP can
reach, over Streamable HTTP, SSE, stdio, or in process. `register_mcp` is a shortcut
for registering a `FastMCPAdapter`.

Registration is lazy. The factory is called when an operation first needs the
server, and again after `reconnect` or after the connection is lost. Registering a
hundred servers costs nothing until they are used.

## Registry

The **registry** stores the metadata of every discovered capability.
`InMemoryRegistry` is the default; implement the `CapabilityRegistry` contract to
keep metadata in a database that several processes share. The registry holds only
metadata: no tool runs and no resource is read until the application asks for it.

## Discovery and refresh

**Discovery** lists the tools, resources, and prompts of a server. The runtime runs
discovery through [refresh-engine](https://refresh-engine.readthedocs.io), which
compares each capability with the previous discovery and writes only what was added,
modified, or removed. A failed discovery never removes anything from the registry.

A **refresh policy** decides when a server is refreshed automatically: when it is
registered, when a query finds nothing, on a fixed interval, or when a change
notification arrives. Without a policy, the application refreshes servers explicitly.

![Refresh flow](assets/diagrams/refresh-flow-light.png#only-light)
![Refresh flow](assets/diagrams/refresh-flow-dark.png#only-dark)

## Retrieval

A **retriever** ranks capabilities against a request. Retrieval reads the registry
only; it never calls a server. `KeywordRetriever`, the default, matches words and
identifiers deterministically and needs no model. `EmbeddingRetriever` ranks by
semantic similarity with any LangChain embedding model.

`MCPRuntime.retrieve` ranks the capabilities that are already known.
`MCPRuntime.query` refreshes the servers that allow it when nothing matches, then
ranks again.

## Operations and the resilience pipeline

Everything the runtime does on a server is an **operation**: connecting, discovering,
calling a tool, reading a resource, and rendering a prompt. Every operation runs
through the same pipeline:

![Resilience pipeline](assets/diagrams/resilience-pipeline-light.png#only-light)
![Resilience pipeline](assets/diagrams/resilience-pipeline-dark.png#only-dark)

1. A **concurrency limit** bounds the operations in flight across all servers.
2. **Interceptors** wrap each operation once, for authentication, auditing, or
   policy checks.
3. A **circuit breaker** for each server and operation rejects operations while the
   server keeps failing.
4. A **retry policy** repeats attempts that failed for a reason that can pass.
5. Each attempt waits for the **rate limit**, then runs under a **timeout**.

Failures are classified into categories, such as connection failures, timeouts,
authentication failures, and tool errors. The category decides whether a failure is
retried and whether it counts toward the circuit breaker.

## Health

The **health** of a server is derived from its circuit breakers, as the worst state
among its operations:

| State | Meaning |
| --- | --- |
| `HEALTHY` | No recent failures. |
| `DEGRADED` | Recent operations failed, but the circuit is still closed. |
| `RECOVERING` | The circuit admits a trial call to find out whether the server recovered. |
| `UNHEALTHY` | The circuit is open, and operations are rejected without calling the server. |

## The runtime lifecycle

A runtime owns everything it creates: connections, background refreshes, schedulers,
and circuit breakers. Nothing is shared between runtimes unless you configure it, for
example by passing the same durable registry to several runtimes.

Closing the runtime stops automatic refreshes, closes every connection, and closes the
registry. Capabilities stored in an external registry stay there, so another process
can keep routing to them. `unregister_server` closes one server and removes its
capabilities.
