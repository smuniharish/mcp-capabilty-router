# Agent Skills

This repository ships a canonical Agent Skills distribution for coding agents and IDE integrations.
The skill is intentionally lightweight: it points agents at the repo's public runtime contract,
its documented integration flow, and the authoritative examples instead of duplicating runtime
logic.

The canonical skill file is:

- [`skills/mcp-capability-router/SKILL.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/skills/mcp-capability-router/SKILL.md)

The package documentation is hosted at:

- https://mcp-capabilty-router.readthedocs.io/en/latest/

The source repository is:

- https://github.com/smuniharish/mcp-capability-router

## Why use an Agent Skill?

`mcp-capability-router` is a runtime and routing layer for MCP tools, resources, and prompts.
A coding agent that is asked to integrate or debug it should follow the verified public API and
lifecycle model rather than guessing at adapter shape, registration patterns, or registry
contracts.

Use the skill when a task involves:

- registering or refreshing MCP servers;
- integrating with LangChain or LangGraph;
- routing a large MCP tool catalog to the smallest relevant subset;
- debugging lazy connection behavior or refresh/retrieval issues;
- designing a custom registry or retriever without rewriting runtime policy.

Do not use it for unrelated model-memory or agent-framework work. The skill is scoped to the
existing router runtime and its supported integration boundaries.

## What the skill tells agents

The skill is a directory-scoped `SKILL.md` file with the required YAML frontmatter and concise
instructions. It points agents to the authoritative runtime surface, examples, and design rules:

- keep the runtime as the boundary for discovery, retrieval, and lifecycle policy;
- register adapter factories rather than global transport or server state;
- keep model orchestration, authentication, and transport setup in the application layer;
- prefer lazy discovery and selective retrieval instead of eagerly loading a full tool catalog;
- use the repo examples and docs rather than duplicating MCP client logic.

## Canonical workflow

The canonical skill follows this workflow:

1. Read the runtime contract in the package entrypoint and the supported API surface.
2. Inspect the current integration points and existing app code before changing behavior.
3. Start from the matching example in the docs or examples folder.
4. Preserve the runtime's lazy lifecycle and selective retrieval model.
5. Validate the change with a focused test or the package's standard docs/test checks.

## Related documentation

- [Getting started](getting-started.md)
- [Architecture overview](../architecture/overview.md)
- [Concepts](../concepts/overview.md)
- [Agent integrations](agent-integrations.md)
- [Examples overview](../examples/overview.md)

## Repository validation note

The repository also contains a validation guide at
[`validation/README.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/validation/README.md),
which documents the structural and source-accuracy checks used to keep the skill aligned with the
runtime implementation and docs.
