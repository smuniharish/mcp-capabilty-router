# MCP Capability Router Agent Skill validation

This directory documents the repeatable validation process for the canonical
skill. It is intentionally not a second runtime test suite and does not provide
host-specific package metadata.

The Agent Skills specification defines `name` and `description` as the required
frontmatter. No official validator is specified, so validation combines
structural checks with source-backed content review.

For this package, the canonical documentation is the hosted docs at
https://mcp-capabilty-router.readthedocs.io/en/latest/ and the source repo is
https://github.com/smuniharish/mcp-capability-router.

## Structural validation

For every change:

1. Confirm [`../skills/mcp-capability-router/SKILL.md`](../skills/mcp-capability-router/SKILL.md)
   exists and starts with YAML frontmatter.
2. Confirm `name` is exactly `mcp-capability-router` (the directory name), uses
   only lowercase letters and hyphens, and is at most 64 characters.
3. Confirm `description` is non-empty, under 1024 characters, and states both
   the capability and when to activate it.
4. Confirm only `name` and `description` appear in frontmatter unless a host's
   current requirement justifies more.
5. Resolve every relative Markdown target in the skill and its references; no
   target may point to a deleted file.
6. Confirm the distribution contains one canonical knowledge source and no
   duplicate platform-specific skill text.
7. Search the distribution for stale project names, made-up CLI commands,
   credential handling mistakes, or unrelated runtime patterns.

## Source-accuracy review

Review every code snippet and factual claim against its source:

| Claim area | Source of truth |
| --- | --- |
| Public import surface and package version | [`src/mcp_capability_router/__init__.py`](../src/mcp_capability_router/__init__.py) |
| Runtime lifecycle and lazy connections | [`src/mcp_capability_router/runtime.py`](../src/mcp_capability_router/runtime.py) |
| Registry contract and metadata model | [`src/mcp_capability_router/registry.py`](../src/mcp_capability_router/registry.py), [`src/mcp_capability_router/models.py`](../src/mcp_capability_router/models.py) |
| Retrieval, filtering, and ranking behavior | [`src/mcp_capability_router/retrieval.py`](../src/mcp_capability_router/retrieval.py) |
| Resilience, metrics, timeouts, and circuit-breaker behavior | [`src/mcp_capability_router/resilience/circuit_breaker.py`](../src/mcp_capability_router/resilience/circuit_breaker.py), [`src/mcp_capability_router/resilience/timeout.py`](../src/mcp_capability_router/resilience/timeout.py) |
| Supported integrations and adapter shape | [`src/mcp_capability_router/integrations/langchain_mcp.py`](../src/mcp_capability_router/integrations/langchain_mcp.py), [`src/mcp_capability_router/server.py`](../src/mcp_capability_router/server.py) |
| User-facing workflow and examples | [`README.md`](../README.md), [`docs/guides/getting-started.md`](../docs/guides/getting-started.md), [`docs/examples/overview.md`](../docs/examples/overview.md) |

If a behavior is not backed by implementation, tests, or authoritative docs,
omit it from the skill rather than infer an API.

## Agent-task matrix

The following matrix was reviewed against the canonical
[`SKILL.md`](../skills/mcp-capability-router/SKILL.md), its references, the
runtime implementation, and the examples/tests in this repository.

| Task | Activates | Grounded route | Avoids |
| --- | --- | --- | --- |
| “Add routing to a large MCP tool catalog.” | Yes | `references/integration.md` and the runtime registration + refresh + retrieve flow. | Inventing a separate transport or ad hoc tool list. |
| “Reduce startup cost by avoiding eager MCP connections.” | Yes | Lazy registration and discovery guidance. | Connecting every server at startup. |
| “Use only the capabilities relevant to a query.” | Yes | Retrieval and `CapabilityType` guidance. | Loading every tool/resource/prompt for every request. |
| “Help me integrate this runtime into LangChain or LangGraph.” | Yes | `references/integration.md` plus `MCPRuntime` and adapter shape guidance. | Hard-coding connection logic into agent code. |
| “Why did a server reconnect or fail during refresh?” | Yes | Resilience and lifecycle guidance. | Guessing around retries, rate limits, or timeout placement. |
| “Add a custom registry or retriever.” | Yes | Registry and retrieval contract references. | Editing the runtime to hard-code a new backend. |
| “Select a tool or resource by type and server.” | Yes | `CapabilityType` and runtime query/filter guidance. | Mixing capability types or treating all records as plain tools. |
| “Configure production runtime boundaries.” | Yes | Runtime, registry, and adapter isolation guidance. | Sharing a mutable runtime across unrelated applications. |

## Repository validation

Skill-only work should at least run the structural/link/source review above and
review the resulting Git diff. If runtime files change, run the repository's
CI-equivalent checks as documented in the project's standard development workflow:
`uv run pytest`, `uv run ruff check .`, `uv run pyrefly check`, and the docs
build if the change affects documentation or examples.
