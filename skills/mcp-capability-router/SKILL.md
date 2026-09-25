---
name: mcp-capability-router
description: Integrate, configure, debug, or optimize the MCP capability routing runtime for LangChain/LangGraph agents, MCP servers, large tool catalogs, selective retrieval, and lazy connection lifecycle. Use when replacing ad hoc tool loading, startup fan-out, or hand-written routing logic for MCP tools, resources, and prompts.
---

# MCP Capability Router

Use this skill for the existing `mcp-capability-router` Python package, not to
create a second MCP client, agent framework, or unrelated registry library.

The supported package-level public API is the surface exported by
[`src/mcp_capability_router/__init__.py`](https://github.com/smuniharish/mcp-capability-router/blob/master/src/mcp_capability_router/__init__.py),
with the primary integration points being:

```python
from mcp_capability_router import (
    CapabilityType,
    MCPRuntime,
    InMemoryRegistry,
    DeterministicRetriever,
    CapabilityRegistry,
    CapabilityRetriever,
)
```

Read [`references/architecture.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/skills/mcp-capability-router/references/architecture.md) before
reasoning about runtime boundaries and discovery. Read
[`references/integration.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/skills/mcp-capability-router/references/integration.md) before adding the
runtime to an application.

The authoritative documentation is https://mcp-capabilty-router.readthedocs.io/en/latest/.
The source repository is https://github.com/smuniharish/mcp-capability-router.

## Activate when

Use the router when an application exposes a meaningful catalog of MCP
capabilities and needs to remain fast, selective, and resilient under context
pressure.

Typical indicators:

- a process hosts many MCP tools/resources/prompts and not all should be loaded
  at startup;
- a server or adapter is slow, flaky, or overloaded and should not block all
  agent turns;
- an application needs to retrieve only a small subset of capabilities for a
  query, then connect lazily when the selected capability is executed;
- a tool list is large enough that passing the raw schema set to the model is
  expensive and counterproductive;
- an application is choosing between a custom in-memory registry, custom
  retriever, or a production database-backed store;
- an existing integration needs debugging, configuration, or a focused test.

Do not select it merely because an application wants a generic memory layer,
a generic vector database wrapper, or a new agent orchestrator.

## Required workflow

### Before changing an application

1. Inspect the installed/current package version and the runtime construction in
   this repository's [`pyproject.toml`](https://github.com/smuniharish/mcp-capability-router/blob/master/pyproject.toml) and
   [`src/mcp_capability_router/__init__.py`](https://github.com/smuniharish/mcp-capability-router/blob/master/src/mcp_capability_router/__init__.py).
2. Verify the project's LangChain, LangGraph, and MCP adapter versions against
   the dependency manifests and example requirements. Do not infer compatibility
   from a similar application.
3. Search the application's existing server registrations, refresh calls,
   retrievers, and tests. Preserve the intended lifecycle and ordering.
4. Start from the repository example that matches the workload; see
   [`references/integration.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/skills/mcp-capability-router/references/integration.md) and the examples in
   [examples documentation](https://mcp-capabilty-router.readthedocs.io/en/latest/examples/).
5. Use the supported registration and execution contracts only.

### Choose the right response to routing pressure

1. **Large tool catalog:** register servers lazily, then call `refresh_server`
   to reconcile metadata without opening a connection on every turn.
2. **Large resource or prompt catalog:** route metadata through the same
   `Capability` model; treat tool, resource, and prompt records as siblings,
   not as special cases bolted on after the fact.
3. **Need to avoid startup fan-out:** keep discovery metadata cheap in the
   registry and load only the selected capability when needed.
4. **Need a custom registry or retriever:** implement the protocol minimally
   and let the runtime stay responsible for lifecycle policy and filtering.
5. **Need more or less resilience:** configure the runtime's resilience
   controls and adapter lifecycle rather than rewriting retry logic in every
   call site.
6. **Query miss or stale metadata:** reproduce first and check the refresh path;
   do not speculate by discarding candidates or bypassing the registry.

## Integration rules

- Register application adapters from your own app layer, not from a transport
  implementation or a global singleton.
- Keep `MCPRuntime` as the boundary for registry, retrieval, and lifecycle
  policy; do not merge connection setup into the router itself.
- Use the lazy lifecycle: `register_server` stores a factory; `refresh_server`
  connects and reconciles metadata; `retrieve` or `query` filters metadata; the
  selected operation loads or invokes the capability on demand.
- Preserve server, capability type, and operation boundaries. Do not treat all
  results as plain text or collapse resources/prompts into tools.
- Keep adapter ownership and credentials in the application; the runtime does
  not authenticate or verify an external MCP server.
- Use the runtime context manager to guarantee shutdown and cleanup.
- Prefer targeted tests for capability matching, refresh behavior, and lazy
  execution.

## Prohibited shortcuts

Do not:

- eagerly connect every server at startup just because the catalog is large;
- manually fetch every tool, resource, and prompt into an agent context for
  every turn;
- rewrite the registry or retriever contract to hide server lifecycle logic;
- build a second transport or fake client when the application can supply a
  valid adapter factory;
- discard candidate records solely to fit a context budget without evaluating
  relevance and type;
- invent imports, CLI commands, environment variables, or configuration keys
  that do not exist in the package or docs;
- modify `src/mcp_capability_router/` while the task is only integration or
  skill content.

## Verification checklist

For an application change, add or update a focused test that asserts the
relevant runtime outcome: registration, refresh behavior, lazy execution, query
filtering by type, or server isolation. Run the repository's relevant test,
lint, and type checks.

For changes to this skill, follow
[`validation/README.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/validation/README.md) and review the
runtime implementation and examples rather than extending the file with second-
hand assumptions.
