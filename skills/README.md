# MCP Capability Router Agent Skills

This directory is the canonical Agent Skills distribution for `mcp-capability-router`.
It contains procedural guidance for coding agents that need to integrate,
configure, test, or debug the existing runtime without inventing a second
routing layer or a duplicate MCP client.

It is not a Python package and does not add runtime behavior.

| Component | Location | Purpose |
| --- | --- | --- |
| Runtime package | [`src/mcp_capability_router/`](https://github.com/smuniharish/mcp-capability-router/tree/master/src/mcp_capability_router) | Published Python package and supported public API. |
| Canonical skill | [`skills/mcp-capability-router/`](https://github.com/smuniharish/mcp-capability-router/tree/master/skills/mcp-capability-router) | Agent-oriented instructions and concise reference material. |
| Skill validation | [`validation/`](https://github.com/smuniharish/mcp-capability-router/tree/master/validation) | Validation procedure and activation/task matrix. |

## Agent Skills format

The canonical skill follows the Agent Skills `SKILL.md` format: a
Directory-scoped Markdown instruction file with required `name` and
`description` YAML frontmatter. Its `name` matches its containing directory
(`mcp-capability-router`), and only the specification's required frontmatter
is used for portability.

Compatible agents should load
[`skills/mcp-capability-router/SKILL.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/skills/mcp-capability-router/SKILL.md)
when working on MCP capability routing, lazy server registration, selection of
relevant tools/resources/prompts, or runtime-isolated resource lifecycle.

The canonical sources of truth for runtime behavior are the official docs at
https://mcp-capabilty-router.readthedocs.io/en/latest/ and the repository at
https://github.com/smuniharish/mcp-capability-router.

This repository intentionally provides no host-specific adapter copies.

## Maintaining the distribution

When the runtime's supported API, integrations, or documented behavior changes:

1. Update the canonical skill and only the reference material affected by that
   verified change.
2. Link to the corresponding implementation, tests, examples, or docs; do not
   duplicate runtime logic.
3. Run the process in [`validation/README.md`](https://github.com/smuniharish/mcp-capability-router/blob/master/validation/README.md).
4. Do not add platform-specific copies of the skill text. Add thin metadata only
   when a host's official docs require it.
