---
name: mcp-capability-router-extend
description: >-
  Use this skill when implementing custom mcp-capability-router registries,
  retrievers, adapters, interceptors, result-cache stores, or refresh-engine
  StateStores; integrating application-owned database pools, vector stores,
  event publishers, or fingerprints; and running extension conformance tests.
  Do not use it for ordinary router configuration or agent integration
  (use mcp-capability-router), building MCP servers, or unrelated database work.
license: Apache-2.0
compatibility: Python 3.12 or newer, mcp-capability-router 1.0, async backend APIs.
metadata:
  author: S. Muni Harish
  version: "1.0.1"
  documentation: https://mcp-capabilty-router.readthedocs.io/
---

# Extending mcp-capability-router

## Workflow

1. Identify the existing downstream customization point before writing a wrapper:
   [references/backends.md](references/backends.md).
2. Subclass the appropriate ABC and implement every required async method.
   Start with [assets/registry_template.py](assets/registry_template.py).
3. Specify connection ownership, tenant/server partitioning, transactions,
   serialization, and shutdown explicitly. Preserve all capability fields.
4. Wire the object through its public entry point. StateStore policy values
   override runtime factories; configured clients cannot take client options again.
5. Run the matching suite from `mcp_capability_router.testing`.
   [assets/test_registry_contract.py](assets/test_registry_contract.py) demonstrates
   this for a registry.
6. Exercise real backends, restart recovery, concurrent operations, and failures;
   use the repository's SQLite, PostgreSQL, Redis, and OTLP examples.

## Invariants

- Use ABC subclassing, not shape-only objects. Only interceptors also accept plain
  async functions.
- Factories take no arguments for adapters, and a server ID for StateStores;
  either may return an awaitable.
- Use one round trip for registry `get_many` when your backend supports it.
- Return only supplied candidates from retrievers and respect `limit`.
- `close` releases owned connections, not durable data or application-owned pools.
- Durable registry and refresh state must be kept together; partition state per server.
- Keep cache stores scoped to trust boundaries. Use safe serialization and TTLs;
  never deserialize arbitrary executable objects.
- Do not reimplement tenacity, purgatory, aiolimiter, Qdrant rank fusion, or cache single-flight.
- Errors must propagate in the router's classified hierarchy; never replace a failed
  discovery with an empty catalog.

## Evaluation

[Evaluation cases](evals/evals.json) cover backend extensions.
[Trigger queries](evals/trigger_queries.json) separate implementation work from configuration.
