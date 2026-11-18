# Agent Skills

mcp-capability-router ships two [Agent Skills](https://agentskills.io) that teach AI
coding agents to integrate and operate the package correctly. It covers registering
servers, choosing refresh policies and retrievers, configuring resilience, routing
tools into LangChain and LangGraph agents, securing tools, observability, testing, and
troubleshooting. Agents load the skill only when a task calls for it.

Use `mcp-capability-router` for integration and operation, and
`mcp-capability-router-extend` for custom registries, retrievers, adapters,
interceptors, and downstream storage. Each includes versioned instructions,
executable assets, task evaluations, and balanced training/validation trigger queries.

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
npx skills add smuniharish/mcp-capabilty-router --skill mcp-capability-router --skill mcp-capability-router-extend
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

Run `uv run pytest tests/skill` to validate both skills, their linked assets and
evaluation fixtures, setup checks, and executable registry contract template.

## Skills for related packages

Several packages that mcp-capability-router builds on, or integrates with, publish
their own Agent Skills. They are maintained by those projects, installed separately,
and optional: install only the ones for the parts of the stack you work on.

| Package | Used for | Skills | Install |
| --- | --- | --- | --- |
| [RetrievalLoom](https://github.com/smuniharish/retrievalloom) | Retrieval behind `LoomRetriever` | `retrievalloom`, `retrievalloom-extend` | `npx skills add smuniharish/retrievalloom` |
| [refresh-engine](https://github.com/smuniharish/refresh-engine) | Change detection during refreshes | `refresh-engine`, `refresh-engine-extend` | `npx skills add https://github.com/smuniharish/refresh-engine/tree/master/refresh-engine-skills/skills/refresh-engine` |
| [FastMCP](https://gofastmcp.com/getting-started/ai-assisted-development) | MCP transports and servers | `fastmcp-server`, `fastmcp-client-cli` | `npx skills add PrefectHQ/fastmcp --skill fastmcp-server` |
| [LangChain](https://github.com/langchain-ai/langchain-skills) | The `langchain` extra, LangGraph, and Deep Agents | `langchain-build-agent`, `langchain-agent-tracing`, `langchain-agent-monitoring`, `langchain-eval-engineering` | `npx skills add langchain-ai/langchain-skills --skill '*'` |
| [Pydantic](https://github.com/pydantic/pydantic) | Pydantic model design | `pydantic` | `npx skills add pydantic/pydantic --skill pydantic` |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MCP SDK testing conventions | `test-quality` | `npx skills add modelcontextprotocol/python-sdk --skill test-quality` |

Pass `--skill` to choose individual skills, and `-g` to install them for your user.
The refresh-engine command installs its core skill; replace the final `refresh-engine`
with `refresh-engine-extend` for the extension skill. To install FastMCP's CLI skill,
replace `fastmcp-server` with `fastmcp-client-cli`. LangChain also distributes its
skills as a plugin for Claude Code, Codex, and Deep Agents Code; see its README for the
plugin commands. These skills are optional agent instructions, not Python dependencies.
Each project documents the versions its skills target, so update them alongside the
package.
