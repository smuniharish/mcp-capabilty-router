# Architecture overview

mcp-capability-router separates **what** an agent can use, which MCP servers describe,
from **how** it is found and used, which the runtime owns.

![Architecture](../assets/diagrams/architecture-light.png#only-light)
![Architecture](../assets/diagrams/architecture-dark.png#only-dark)

## Responsibilities

The application provides:

- the **servers** to route to, as FastMCP targets or custom adapters;
- a **refresh policy** for each server;
- optionally, a durable **registry**, a **retriever**, **interceptors**, a resilience
  configuration, and a **metrics sink**.

The runtime provides:

- **connection management**: lazy connections, one session per server, reconnection
  after a lost connection, and orderly shutdown;
- **discovery and reconciliation**: listing every server's capabilities and writing
  only what changed, through refresh-engine;
- **retrieval**: ranking capability metadata against requests without calling servers;
- the **resilience pipeline**: concurrency limits, interceptors, circuit breakers,
  retries, rate limits, and timeouts around every server operation;
- **failure classification**, **health**, and **metrics**;
- **agent integration**: middleware and LangChain tools that route calls through the
  runtime.

## Design principles

**Compose the ecosystem.** The router builds on proven libraries instead of
reimplementing them: FastMCP for every MCP transport, LangChain for tools, middleware,
embeddings, vector search, and MCP tool conversion, refresh-engine for change
detection, tenacity for retries, purgatory for circuit breakers, and aiolimiter for
rate limits. The router contributes what none of them does: routing, lifecycle, and
failure semantics across many servers.

**Metadata first, connections on demand.** Discovery stores metadata; retrieval reads
only metadata. A server is contacted only when an operation needs it, so registering
many servers is cheap, and routing never waits for the network.

**Isolation by ownership.** A runtime owns its servers, connections, registry, caches,
circuit breakers, and background tasks. Nothing is shared between runtimes unless the
application passes the same durable registry or circuit storage to them.

**Classified failures.** Every failure is mapped to a category. The category decides
whether an operation is retried and whether it counts toward a circuit breaker, so a
rejected tool call is never repeated and never takes a healthy server out of
service.

**Explicit contracts.** Registries, retrievers, adapters, and interceptors are
structural protocols, checked when they are supplied. Every public name is exported
from the package root.

**Deterministic by default.** The default retriever, registry, and pipeline involve no
model and no randomness, so routing can be tested exactly and explained.

## Guarantees

1. Retrieval never calls a server.
2. A failed discovery never removes capabilities from the registry. After a
   successful refresh that is not targeted, the registry holds exactly the
   capabilities that the server offers, as long as no other process changes them.
3. Every server operation runs through the resilience pipeline, and every interceptor
   sees each operation once, however many attempts it takes.
4. Failures that cannot pass on another attempt are never retried and never count
   toward a circuit breaker.
5. A registration that fails, or is undone by an unregistration or a shutdown, leaves
   nothing registered, and a server ID is reused only after its previous server is
   fully closed.
6. Every background task and connection has an owner and stops when its server is
   unregistered or its runtime closes; a closed server is never reconnected.
7. Tool arguments reach the server unchanged, and routed tool failures and timeouts
   reach the model as error messages instead of aborting the agent run.

These guarantees are verified by unit, integration, and property-based tests,
including a stateful test that compares the registry with an independent model across
generated sequences of operations, and a property test that checks that refreshes
converge the registry to what the server offers across generated changes,
re-registrations, and leftovers of earlier registrations.

## Complexity

For *N* candidate capabilities and *T* query words, keyword retrieval takes *O(N·T)*
time per query; each capability's index is built once and reused until the
capability changes. Discovery and change detection take *O(N)* time per server.
Executing an operation adds constant overhead to the server call.

See [Request lifecycle](lifecycle.md) for the steps of each operation.
