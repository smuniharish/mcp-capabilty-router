# Validating the Agent Skill

Validate the skill whenever it, the public API, or documented behavior changes.
Continuous integration runs the automated checks on every pull request.

## Automated checks

Run these from the repository root:

```bash
uvx --from skills-ref==0.1.1 agentskills validate mcp-capability-router-skills/skills/mcp-capability-router
uv run python scripts/check_docs.py
uv run ruff check mcp-capability-router-skills
uv run pyrefly check
```

- `agentskills validate`, from the `skills-ref` package, is the reference validator of
  the [Agent Skills specification](https://agentskills.io/specification). It checks
  the frontmatter, the name, and the directory layout.
- `scripts/check_docs.py` compiles every Python block, runs the blocks marked
  `<!-- test -->` and compares their output, runs the template in `assets/`, rejects
  imports of non-public names, checks that `metadata.version` matches the package, and
  resolves every link.
- `ruff` and `pyrefly` lint and type-check the template.

## Review checklist

1. `SKILL.md` stays under 500 lines, and its `description` states what the skill does
   and when to use it, in at most 1024 characters.
2. `metadata.version` matches `mcp_capability_router.__version__`.
3. Every reference is linked from `SKILL.md` and is reachable in one step.
4. Every signature, default, and behavior matches its source of truth:

    | Claim | Source of truth |
    | --- | --- |
    | Public names | `mcp_capability_router.__all__` in `src/mcp_capability_router/__init__.py` |
    | Signatures, defaults, and documented behavior | The docstrings in `src/mcp_capability_router/`, rendered in the [API reference](https://mcp-capabilty-router.readthedocs.io/en/latest/api/) |
    | Routing, refresh, and resilience semantics | The [guides](https://mcp-capabilty-router.readthedocs.io/en/latest/guides/) and the tests in `tests/` |
    | Runnable patterns | `examples/` and their expected output in `examples/output/` |

5. The skill describes only public behavior. It never mentions private modules,
   unreleased features, or credentials.

## Activation scenarios

Use these requests to check that an agent selects the skill and follows the right
reference. Each answer must use the public API and avoid the listed mistake.

| Request | Expected route | Must avoid |
| --- | --- | --- |
| "Our agent has 300 MCP tools; give it only the relevant ones." | `SKILL.md` workflow, the template, and `agents.md`: `CapabilityRoutingMiddleware` | Binding every tool, or hand-written tool filtering. |
| "Connect the GitHub and filesystem MCP servers to our LangGraph app." | `servers.md`: `register_mcp` with URLs and stdio transports | Writing an MCP client, or connecting at import time. |
| "New tools on the plugin server should appear without a restart." | `refresh.md`: `change_events` with a FastMCP message handler, or `on_query_miss` | Restarting the process, or refreshing on every request. |
| "The CRM server is flaky; stop hammering it when it is down." | `resilience.md`: timeout, `is_retryable` retries, circuit breakers, and health | Retry loops around `execute`, or retrying `ToolExecutionError`. |
| "Agents must never delete records without approval." | `security.md`: a policy interceptor or `HumanInTheLoopMiddleware` | Relying on the system prompt alone. |
| "Store the tool catalog in PostgreSQL for all replicas." | `extensions.md`: a `CapabilityRegistry` that round-trips every field | Lossy serialization, or a registry per request. |
| "Write tests for routing without calling OpenAI." | `testing.md`: in-process FastMCP servers and a scripted `GenericFakeChatModel` | Mocking runtime internals. |
| "Why does retrieve return nothing?" | `troubleshooting.md`: discovery never ran, or no shared words | Disabling retrieval, or binding every tool. |
