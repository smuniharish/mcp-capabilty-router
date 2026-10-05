# Agent Skills

mcp-capability-router ships an [Agent Skill](https://agentskills.io) that teaches AI
coding agents to integrate and operate the package correctly. It covers registering
servers, choosing refresh policies and retrievers, configuring resilience, routing
tools into LangChain and LangGraph agents, securing tools, observability, testing, and
troubleshooting. Agents load the skill only when a task calls for it.

The skill follows the [Agent Skills specification](https://agentskills.io/specification)
and is published in the repository at
[`mcp-capability-router-skills/skills/mcp-capability-router`](https://github.com/smuniharish/mcp-capabilty-router/tree/master/mcp-capability-router-skills/skills/mcp-capability-router).

## Contents

| Path | Purpose |
| --- | --- |
| `SKILL.md` | The workflow, the rules that keep integrations safe, and a quick reference of the public API. |
| `references/` | Focused guides that the agent reads on demand: servers, retrieval, refresh, resilience, agents, extensions, security, observability, testing, and troubleshooting. |
| `assets/integration_template.py` | A complete, typed integration skeleton that the agent adapts to your project. |

## Install with the skills CLI

The [skills CLI](https://www.skills.sh/docs/cli) installs the skill for the agents it
detects in your project:

```bash
npx skills add https://github.com/smuniharish/mcp-capabilty-router/tree/master/mcp-capability-router-skills/skills/mcp-capability-router
```

Add `-g` to install it for your user instead of the current project, and `-a <agent>`
to choose agents explicitly, for example `-a claude-code -a codex`.

## Install manually

Copy the complete `mcp-capability-router` directory, including `references/` and
`assets/`, into a skills directory that your agent reads:

| Agent | Project | Personal |
| --- | --- | --- |
| [Claude Code](https://code.claude.com/docs/en/skills) | `.claude/skills/` | `~/.claude/skills/` |
| [Codex](https://developers.openai.com/codex/skills) | `.agents/skills/` | `~/.agents/skills/` |
| [Cursor](https://cursor.com/docs/skills) | `.agents/skills/` or `.cursor/skills/` | `~/.agents/skills/` or `~/.cursor/skills/` |
| [GitHub Copilot](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills) | `.github/skills/`, `.agents/skills/`, or `.claude/skills/` | `~/.copilot/skills/` or `~/.agents/skills/` |

The `.agents/skills/` locations work for Codex, Cursor, and GitHub Copilot alike.

## Use the skill

Agents activate the skill automatically when a task matches its description, for
example *"route our MCP servers' tools into the support agent with
mcp-capability-router"*. You can also invoke it explicitly:

| Agent | Invocation |
| --- | --- |
| Claude Code | `/mcp-capability-router` |
| Codex | `$mcp-capability-router`, or select it from `/skills` |
| Cursor | Type `/` in the agent chat and select `mcp-capability-router` |
| GitHub Copilot CLI | `/mcp-capability-router`; run `/skills reload` after installing during a session |

## Keep it current

The skill is versioned with the package, and its `metadata.version` matches the
release it describes. After upgrading mcp-capability-router, reinstall the skill with
the same command, or replace the copied directory.
