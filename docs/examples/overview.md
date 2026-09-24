# Examples

The examples prioritize real MCP connectivity. The Filesystem MCP smoke test starts the official
server over stdio and routes a selected tool through the runtime. Unit tests still use small
in-process adapters because deterministic failure and concurrency tests should not depend on
external processes.

A second group of examples is deterministic and credential-free by design: they use small
in-process adapters (the same pattern as the unit tests) to demonstrate dynamic server
registration, refresh strategies, custom registries, and combined Tool/Resource/Prompt
workflows without any external process or network access.

| Example area | Tools | Resources | Prompts | Dynamic | Refresh | Resilience |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `real_filesystem_mcp.py` | ✓ |  |  |  | ✓ | ✓ |
| `basic_runtime.py` (Playwright MCP) | ✓ |  |  |  | ✓ | ✓ |
| `real_everything_mcp.py` | ✓ |  |  |  | ✓ | ✓ |
| `real_git_mcp.py` | ✓ |  |  |  | ✓ | ✓ |
| `real_fetch_mcp.py` | ✓ |  |  |  | ✓ | ✓ |
| `real_multi_mcp_single_agent.py` (filesystem + git MCP, 1 agent) | ✓ |  |  |  | ✓ | ✓ |
| `real_multi_capability_selection.py` (Everything MCP, multiple tools + resources) | ✓ | ✓ |  |  | ✓ | ✓ |
| `langgraph_network.py` | ✓ |  |  | ✓ | ✓ | ✓ |
| `create_agent_routing.py` | ✓ |  |  |  | ✓ | ✓ |
| `deepagents_network.py` | ✓ |  |  |  | ✓ | ✓ |
| `langgraph_swarm_network.py` | ✓ |  |  | ✓ | ✓ | ✓ |
| `real_multi_agent_multi_mcp.py` (filesystem MCP -> agent A, git MCP -> agent B) | ✓ |  |  | ✓ | ✓ | ✓ |
| `dynamic_registration.py` | ✓ |  |  | ✓ | ✓ |  |
| `refresh_strategies.py` | ✓ |  |  |  | ✓ |  |
| `custom_registry.py` | ✓ |  |  |  | ✓ |  |
| `combined_workflow.py` | ✓ | ✓ | ✓ |  | ✓ |  |
| `resource_selection.py` |  | ✓ |  |  | ✓ |  |
| `prompt_selection.py` |  |  | ✓ |  | ✓ |  |
| `tools_and_resources.py` | ✓ | ✓ |  |  | ✓ |  |
| `capability_scale_simulation.py` | ✓ |  |  |  | ✓ |  |
| `on_demand_connection.py` | ✓ |  |  |  | ✓ |  |
| `manual_refresh.py` | ✓ |  |  |  | ✓ |  |
| `multi_runtime_isolation.py` | ✓ |  |  |  | ✓ | ✓ |
| `resilience_breaker_retry_timeout.py` | ✓ |  |  |  | ✓ | ✓ |
| `resilience_bulkhead_rate_limit.py` | ✓ |  |  |  | ✓ | ✓ |
| `langgraph_dynamic_discovery.py` | ✓ |  |  | ✓ | ✓ |  |
| `end_to_end_full_stack.py` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `public_api_overrides.py` (real Filesystem MCP for the final combined demo) | ✓ |  |  |  | ✓ | ✓ |

None of the examples above call an external database, vector store, or metrics backend -- MCP
connectivity is the only external dependency, and several rows above don't even need that.

`real_multi_mcp_single_agent.py` and `real_multi_capability_selection.py` go beyond the
single-server, single-capability smoke tests above: the former registers two real MCP servers
(Filesystem + Git) into one runtime and lets a single `create_agent` agent use tools from both at
once; the latter retrieves and uses *several* tools and *several* resources from one real server
(the Everything MCP server) in a single workflow, instead of narrowing straight to one match.
`real_multi_agent_multi_mcp.py` shows the complementary shape: two different agents, each scoped
to its own real MCP server (`server_id="filesystem"` vs. `server_id="git"`), cooperating through a
LangGraph network.

## Pluggability proof examples

These examples are **not** MCP servers and have no MCP capability types of their own. They prove
that `MCPRuntime`'s internal collaborators -- the capability registry, the retriever's embedding
function, and the metrics hook -- are swappable protocols, by substituting a real backing service
for the in-memory/no-op default with zero changes to `MCPRuntime` or the routing pipeline. Each
one still registers and routes an ordinary in-process fake MCP adapter; the thing being swapped is
purely internal plumbing, so a Tools/Resources/Prompts column would be misleading here.

| Example | Protocol swapped | Real infrastructure used | What it proves |
|---|---|---|---|
| `postgres_registry.py` | `CapabilityRegistry` | Podman-hosted Postgres | Capability metadata persists in a real database instead of an in-process dict; a second, independent registry connection re-reads the same rows. |
| `vector_retrieval_qdrant.py` | `CapabilityRetriever` | Podman-hosted Qdrant | Retrieval ranking runs against a real vector index instead of in-process term matching. |
| `embedding_ollama.py` | `CapabilityRetriever`'s `embed_fn` | Podman-hosted Ollama | The embedding function itself is swappable independently of the vector store backend. |
| `metrics_prometheus.py` | `MetricsHook` | Podman-hosted Prometheus + Grafana | Runtime operations emit real metrics scraped by Prometheus and visualized in a live Grafana dashboard. |
| `metrics_prometheus_real_llm.py` | `MetricsHook` | Podman-hosted Prometheus + Grafana, real LLM agent | A richer `ObservabilityMetricsHook` -- per-server health, capabilities discovered by type, refresh outcomes, and operation latency, not just a flat counter -- driven by a real `create_agent` LLM agent calling a real Filesystem MCP tool, not scripted traffic. |
| `reranking_bm25.py` | `CapabilityRetriever` (composed via `RerankingRetriever`/`CapabilityReranker`) | None (pure-Python BM25 Okapi) | A first-stage retriever's candidates can be re-scored by an independent second-stage reranker with no runtime changes; a neural cross-encoder is a drop-in alternative `CapabilityReranker` in unrestricted environments. |

Walkthroughs, exact commands, and captured real output for all five live in
[Agent integrations](../guides/agent-integrations.md).

## Overriding every public API's defaults

`public_api_overrides.py` is a reference for developers who want to know *which* parameters on
every public class/method have defaults, and *how* to override them -- rather than duplicating
one API at a time, it walks the full public surface in nine standalone demo functions, run
in sequence by `main()`:

| # | Demo | Parameters overridden |
|---|---|---|
| 1 | `registry_override_demo` | `MCPRuntime(registry=...)` with a custom `CapabilityRegistryBase` subclass |
| 2 | `retriever_and_reranker_override_demo` | `MCPRuntime(retriever=...)` via `RerankingRetriever(first_stage, reranker, overfetch_limit=...)` |
| 3 | `metrics_override_demo` | `MCPRuntime(metrics=...)` with a custom `MetricsHook` |
| 4 | `interceptor_override_demo` | `MCPRuntime(interceptors=...)` with a custom interceptor chain |
| 5 | `retry_and_rate_limiter_override_demo` | `MCPRuntime(retry=..., rate_limiter=...)` with real `tenacity.AsyncRetrying`/`aiolimiter.AsyncLimiter` objects |
| 6 | `concurrency_and_timeout_override_demo` | `MCPRuntime(max_concurrency=..., operation_timeout=...)` |
| 7 | `register_and_refresh_policy_override_demo` | `register_server(metadata=..., refresh=RefreshPolicy(on_register=, mode=, config=, store=))` |
| 8 | `explicit_refresh_and_query_override_demo` | `refresh_server(mode=, resource_ids=)` and `query(type=, limit=, server_id=, refresh_servers=, mode=)` |
| 9 | `real_llm_end_to_end_demo` | Combines every override above into a single `MCPRuntime`, then drives a real `create_agent` LLM agent against the real Filesystem MCP server to prove the fully-customized runtime still selects and executes a tool correctly |

Demos 1-8 are deterministic and credential-free (in-process fake adapters, no network access).
Demo 9 needs the `mcp`, `agents`, and `openai` extras plus `EXPLABS_API_KEY` (and optionally
`EXPLABS_BASE_URL`/`EXPLABS_MODEL`) in `.env`, and launches the official Filesystem MCP server
with `npx`. Run all nine in order with:

```powershell
uv run python -m examples.public_api_overrides
```

The in-process `FakeAdapter` used by demos 1-8 subclasses the optional `MCPAdapterBase`
abstract base class rather than only structurally satisfying the `MCPAdapter` protocol, and
`CountingRegistry` (demo 1) does the same for `CapabilityRegistryBase` -- both showing the
enforced-subclass style side by side with `RecordingMetrics` (demo 3), which satisfies
`MetricsHook` structurally with no inheritance at all, to make explicit that either style is
a fully supported way to implement a plugin.

## Integration matrix

| Scenario | Runnable locally | Adapter boundary | Suggested application hook |
|---|:---:|---|---|
| Real Filesystem MCP tools | Yes, with Node.js | `langchain-mcp-adapters` | `MCPRuntime.register_server` |
| Real Everything MCP tool | Yes, with Node.js and network access for npx | `langchain-mcp-adapters` | `MCPRuntime.register_mcp_client` |
| Real Git MCP tool | Yes, with uv/uvx and Git | `langchain-mcp-adapters` | `MCPRuntime.register_mcp_client` |
| Real Fetch MCP tool | Yes, with uv/uvx and outbound HTTPS access | `langchain-mcp-adapters` | `MCPRuntime.register_mcp_client` |
| One real MCP server | No credentials supplied | `langchain-mcp-adapters` | `MCPRuntime.register_server` |
| Model-assisted selection | No model configured | LangChain model | `retrieve` -> `model.ainvoke` |
| Stateful agent workflow | No graph configured | LangGraph node | `query`/`execute` in a node |
| Dynamic server registration from a tool result | Yes, credential-free | in-process fake adapter | `MCPRuntime.register_server` after a prior `execute` |
| Query-driven refresh | Yes, with Node.js | real Everything MCP via `MultiServerMCPClient` | `RefreshPolicy(on_query_miss=True)` + ordinary `MCPRuntime.query(...)` |
| Event-driven refresh | Yes, with Node.js | real Everything MCP via `MultiServerMCPClient` | `RefreshPolicy(change_events=queue)`; runtime owns the listener |
| Time-based refresh | Yes, with Node.js | real Everything MCP via `MultiServerMCPClient` | `RefreshPolicy(interval=..., mode=RefreshMode.INCREMENTAL)`; runtime owns and cancels the `refresh_engine.AsyncScheduler` |
| Custom registry | Yes, credential-free | `CapabilityRegistry` protocol | `MCPRuntime(registry=...)` |
| Combined Tool + Resource + Prompt workflow | Yes, credential-free | in-process fake adapter | `retrieve`/`execute`/`read_resource`/`get_prompt` |

Registry/retrieval/metrics pluggability (Postgres, Qdrant, Ollama, Prometheus) is covered
separately in the [Pluggability proof examples](#pluggability-proof-examples) table above, since
those examples swap an internal `MCPRuntime` collaborator rather than an MCP server.

## Run the executable real-server smoke test

```powershell
uv run python -m examples.real_filesystem_mcp
```

`examples/real_integrations.py` contains configuration hooks only. It intentionally does not
claim that an external server, model, or graph was tested.

## Run the official-server smoke tests

Each script constructs `MultiServerMCPClient` directly, passes it to
`MCPRuntime.register_mcp_client`, refreshes its server, and runs one selected tool. They are
not run by the documentation build or normal test suite. Run them yourself when their stated
prerequisites are available.

```powershell
uv run python -m examples.real_everything_mcp
uv run python -m examples.real_git_mcp
uv run python -m examples.real_fetch_mcp
```

### Everything

`examples/real_everything_mcp.py` launches the official
[`@modelcontextprotocol/server-everything`](https://github.com/modelcontextprotocol/servers/tree/main/src/everything)
package with `npx -y`; on Windows it uses the launcher's documented `cmd /c npx` wrapper. It
needs Node.js with `npx` on `PATH`, network access for a first-time package download, and the
project's `mcp` extra (`uv sync --extra mcp`). The script calls only the `echo` tool.

### Git

`examples/real_git_mcp.py` launches the official
[`mcp-server-git`](https://github.com/modelcontextprotocol/servers/tree/main/src/git) package
with `uvx`. It needs `uvx` and Git on `PATH`, and the project's `mcp` extra. It initializes a
temporary repository and calls only `git_status`; it neither stages nor commits changes.

### Fetch

`examples/real_fetch_mcp.py` launches the official
[`mcp-server-fetch`](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch)
package with `uvx`. It needs `uvx`, the project's `mcp` extra, and outbound HTTPS access to
`https://example.com/`; the script fetches only that public URL. The server can access
network-reachable addresses, so never substitute private-network or credential-bearing URLs.
The fixed smoke invocation passes the server's documented `--ignore-robots-txt` option to avoid
an unrelated preliminary robots.txt request; do not use that option when your application must
honor robots.txt.

All three scripts check for missing local launchers and print a concise prerequisite error.
They configure the client to raise MCP tool errors, so launch, package-installation, and server
errors remain visible and return a nonzero status rather than being silently treated as
successful smoke tests.

### Example output

All five MCP smoke tests below run against real MCP servers (not simulated):

```text
uv run python -m examples.real_filesystem_mcp
[{'type': 'text', 'text': 'router smoke test', ...}]

uv run python -m examples.basic_runtime   # Playwright MCP
selected: browser_navigate
[{'type': 'text', 'text': "### Ran Playwright code\n```js\nawait page.goto('file:///.../smoke-a.html');\n```\n### Page\n- Page URL: file:///.../smoke-a.html\n...", ...}]
[{'type': 'text', 'text': "### Ran Playwright code\n```js\nawait page.goto('file:///.../smoke-b.html');\n```\n### Page\n- Page URL: file:///.../smoke-b.html\n...", ...}]

uv run python -m examples.real_everything_mcp
[{'type': 'text', 'text': 'Echo: router smoke test', ...}]

uv run python -m examples.real_git_mcp
[{'type': 'text', 'text': 'Repository status:\nOn branch master\n\nNo commits yet\n\n...', ...}]

uv run python -m examples.real_fetch_mcp
[{'type': 'text', 'text': 'Failed to fetch robots.txt https://example.com/robots.txt due to a connection issue', ...}]
```

Filesystem, Playwright, Everything, and Git execute their tool successfully. The Fetch server
starts and makes an outbound HTTP attempt, but on networks that intercept outbound TLS,
`mcp-server-fetch`'s own HTTP client may not trust the interception certificate for the
`robots.txt` preflight request -- a network constraint, not a router or adapter defect. On a
machine with standard outbound HTTPS access, the fetch call succeeds the same way the other four
do.

!!! note "Known environment-specific exceptions"
    A few examples depend on external services or network conditions outside the router's
    control:

    - `real_fetch_mcp.py` fails on networks that TLS-intercept outbound HTTPS, as described above.
    - `postgres_registry.py`, `vector_retrieval_qdrant.py`, `embedding_ollama.py` require the
      Podman-hosted Postgres/Qdrant/Ollama instances documented in
      [Pluggability proofs](#pluggability-proofs-registry-embeddings-and-metrics) below; without
      them running, each fails with a plain connection-refused error.
    - `langgraph_swarm_network.py` depends on OpenAI-compatible `messages.role` handling in the
      configured LLM backend; some backends reject `name` on non-tool messages during the
      `langgraph-swarm` handoff sequence (`Invalid value for 'messages.2': name is valid only for
      tool messages`), which is a backend/`langchain-openai` serialization compatibility issue
      unrelated to `MCPRuntime` or the resilience pipeline.

    `uvx`-launched servers (Git, Fetch) may require `--system-certs` depending on your local
    certificate setup; omit that argument if your environment does not need it.

### Multi-server, multi-agent, and multi-capability selection

Three additional real-MCP scenarios go beyond one-server / one-capability smoke tests:


```text
uv run python -m examples.real_multi_mcp_single_agent
capabilities discovered across servers: ['filesystem', 'git']
- **router-note.txt:** Contains: "multi-server single-agent smoke test"
- **Git repository (...):** On the `master` branch, with no commits yet and no files
  currently staged or tracked.

uv run python -m examples.real_multi_agent_multi_mcp
file_agent (filesystem MCP): router-note.txt says: "multi-agent multi-server smoke test."
git_agent (git MCP): The repository is on the `master` branch, has no commits yet, and has
no tracked or untracked changes.

uv run python -m examples.real_multi_capability_selection
selected 5 candidate tools; using 2 of them:
  echo -> [{'type': 'text', 'text': 'Echo: router says hi', ...}]
  get-sum -> [{'type': 'text', 'text': 'The sum of 19 and 23 is 42.', ...}]
selected 7 candidate resources; reading 3 of them:
  structure.md: # Everything Server - Project Structure ...
  startup.md: # Everything Server - Startup Process ...
  instructions.md: # Everything Server - Server Instructions ...
```

`real_multi_mcp_single_agent.py` registers the Filesystem and Git MCP servers into one runtime
and lets a single `create_agent` agent (backed by a real model) read a file and check repository
status in the same turn -- `runtime.retrieve()` returns capabilities tagged with both
`server_id`s, proving cross-server routing for one agent. `real_multi_agent_multi_mcp.py` flips
that around: two independently created agents, each restricted to its own real MCP server via
`server_id=` filtering on `retrieve()`, run as sequential nodes in a real LangGraph
`StateGraph`. `real_multi_capability_selection.py` uses the Everything MCP server's thirteen
tools and seven document resources to show `retrieve()` returning multiple candidates of each
type and the workflow executing/reading more than one of each, rather than narrowing to a single
match.

!!! note "Resource shape over `langchain-mcp-adapters`"
    `LangChainMCPAdapter.list_resources()` normalizes each underlying
    `langchain_core.documents.Blob` into the `{uri, name, description}` shape that
    `discover_server()` expects, reading the URI from `Blob.metadata['uri']`. `read_resource()`
    returns decoded string content rather than the raw `Blob`.

### Playwright MCP notes

`@playwright/mcp` pins a specific Chrome-for-Testing build per release, which can differ from
the build that a plain `npx playwright install chromium` downloads. Use the server's own
installer instead: `npx -y @playwright/mcp install-browser chromium`. The example passes
`--browser chromium --headless` so it runs without a display, and navigates to local temporary
HTML files (via `file://`) rather than an external URL so it succeeds deterministically
regardless of outbound network policy.

Each routed `execute()` call here invokes the tool through `langchain-mcp-adapters`' default
(non-persistent) session handling, so browser state such as the currently open page is not
guaranteed to carry over between separate `execute()` calls (a `browser_snapshot` call issued
after a separate `browser_navigate` call can land on `about:blank`). The example therefore
demonstrates two independent, self-contained navigations rather than a navigate-then-snapshot
chain.

## Pluggability proofs: registry, embeddings, and metrics

Beyond retrieval (`vector_retrieval_qdrant.py`), four more extension points are verified
hands-on against Podman-hosted infrastructure, with no mocks or simulated output. Full
walkthroughs, commands, and captured results (including Grafana screenshots) live in
[Agent integrations](../guides/agent-integrations.md):

- **`postgres_registry.py`** -- the `CapabilityRegistry` protocol backed by a real Postgres
  instance; persistence proven via a second, independent registry connection re-reading the same
  rows.
- **`embedding_ollama.py`** -- `QdrantCapabilityRetriever`'s `embed_fn` swapped for a
  locally-hosted Ollama embedding model (`local-minilm`, 384-dim), reusing the same retriever
  class from `vector_retrieval_qdrant.py` unchanged. Covers restricted-network setups where
  `registry.ollama.ai` and Hugging Face's model-resolve endpoint are blocked, with a
  GitHub-hosted GGUF workaround.
- **`metrics_prometheus.py`** -- the `MetricsHook` protocol backed by a real
  `prometheus_client` counter, scraped by a Prometheus container and visualized in a Grafana
  dashboard (all three on one Podman network). Covers a Grafana bundled-plugin caveat: its
  `prometheus` datasource plugin can be broken by a failed background auto-update on
  offline/restricted networks, fixed with `GF_PLUGINS_PREINSTALL_DISABLED=true`.
- **`metrics_prometheus_real_llm.py`** -- the same Prometheus/Grafana wiring, driven by a real
  `create_agent` LLM agent talking to a real Filesystem MCP server instead of scripted
  fake-adapter traffic, and a richer `ObservabilityMetricsHook` exporting per-server health,
  capabilities discovered by type, per-server refresh outcomes, and operation latency -- a
  five-panel dashboard, not a single flat counter -- reflecting the metrics developers actually
  reach for in production.

None of these four required any change to `MCPRuntime` or the router core -- each is a drop-in
implementation of an existing protocol (`CapabilityRegistry`, the retriever's `embed_fn`, and
`MetricsHook`), passed in through the same constructor keyword arguments used throughout the rest
of this example suite.
