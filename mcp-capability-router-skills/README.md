# mcp-capability-router Agent Skill

This directory distributes the [Agent Skill](https://agentskills.io) for
mcp-capability-router. The skill teaches AI coding agents to integrate, configure,
test, and troubleshoot the `mcp_capability_router` package. It contains instructions
and a template only; it adds no runtime code.

| Path | Contents |
| --- | --- |
| [`skills/mcp-capability-router/SKILL.md`](skills/mcp-capability-router/SKILL.md) | Workflow, rules, a verified minimal integration, and the API quick reference. |
| [`skills/mcp-capability-router/references/`](skills/mcp-capability-router/references/) | Focused guides that agents read on demand. |
| [`skills/mcp-capability-router/assets/`](skills/mcp-capability-router/assets/) | A runnable, typed integration template. |
| [`validation/`](validation/README.md) | How the skill is validated. |

The skill follows the [specification](https://agentskills.io/specification): its
`name` matches its directory, and its frontmatter uses only standard fields. It works
unchanged with Claude Code, Codex, Cursor, GitHub Copilot, and other compatible
agents.

## Installation

Install it with the [skills CLI](https://www.skills.sh/docs/cli):

```bash
npx skills add https://github.com/smuniharish/mcp-capabilty-router/tree/master/mcp-capability-router-skills/skills/mcp-capability-router
```

Or copy the complete `skills/mcp-capability-router` directory into a skills directory
of your agent. The
[installation guide](https://mcp-capabilty-router.readthedocs.io/en/latest/agent-skills/)
lists the directories each agent reads.

## Maintenance

The skill is versioned with the package; `metadata.version` in `SKILL.md` matches the
release it describes. When the public API or documented behavior changes, update the
affected skill files in the same change and follow the
[validation guide](validation/README.md).
