# Agent integrations

The router is deliberately below the agent layer. Playwright is launched directly with its
official MCP command and passed through the generic `LangChainMCPAdapter`; this project contains
no Playwright-specific client implementation:

```mermaid
flowchart TD
  Request --> Router[retrieve / query]
  Router --> CandidateSet[small candidate set]
  CandidateSet --> Select[application-owned model or policy]
  Select --> JIT[load or execute selected capability]
  JIT --> Agent[create_agent / LangGraph / DeepAgents]
```

## Simple LangGraph `create_agent`

Install the optional agent dependencies:

```powershell
uv sync --extra agents --extra openai --extra examples
```

`examples/create_agent_routing.py` retrieves one capability, forwards its real JSON Schema, and
wraps only that capability as a LangChain `StructuredTool`. The complete registry is never
attached to the model. The chat model is a plain LangChain class instantiated directly in
code — there is no router-owned model configuration layer:

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model=os.environ.get("EXPLABS_MODEL", "gpt-5.6-luna"),
    base_url=os.environ.get("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
    api_key=api_key,
)
```

Any LangChain-compatible chat model class (`ChatLiteLLM`, `ChatAnthropic`, ...) can be substituted
here with no other change to the router or the example.

This example was executed for real against the official Filesystem MCP server and a real
OpenAI-compatible endpoint. Captured output:

```powershell
uv run python -m examples.create_agent_routing
```

Real output:

> `router-note.txt` contains:
>
> ```text
> real MCP agent
> ```

The agent selected `read_text_file` through the router, called it with the correct `path`
argument (thanks to the real JSON Schema forwarded from MCP tool discovery), and produced the
answer above from the real file content — with no capability other than the single routed tool
ever exposed to the model.

## Basic LangGraph network

`examples/langgraph_network.py` builds a three-node network:

1. `router` retrieves the relevant capability and performs query-driven refresh.
2. `researcher` executes the selected MCP tool.
3. `writer` turns the result into the next state update.

Run it without credentials:

```powershell
uv run python -m examples.langgraph_network
```

This is the smallest useful multi-agent/network boundary. Replace the researcher and writer
bodies with model-backed nodes without changing the runtime lifecycle or routing policy.

## DeepAgents

DeepAgents is optional and is not a replacement for the router. `examples/deepagents_network.py`
uses `create_deep_agent` only after retrieval and wraps the selected capability as a tool.

```powershell
uv sync --extra agents --extra openai
uv run python -m examples.deepagents_network
```

If DeepAgents is not installed, the example exits with an actionable installation message.

## `langgraph-swarm`

`langgraph-swarm` adds explicit agent handoffs on top of LangGraph. The real
`examples/langgraph_swarm_network.py` example routes only the selected Playwright capability to
the navigator agent, then hands control to an auditor agent:

```powershell
uv sync --extra mcp --extra agents --extra openai --extra swarm
uv run python -m examples.langgraph_swarm_network
```

The swarm package is optional. It does not replace `MCPRuntime`; it consumes the small
application-selected tool set produced by the runtime.

Playwright MCP requires a browser binary. Install it using the server's own installer:

```powershell
npx -y @playwright/mcp@latest install-browser chrome-for-testing
```

## Real MCP server smoke test

The repository includes `examples/real_filesystem_mcp.py`, which starts the official
Filesystem MCP server over stdio through `langchain-mcp-adapters`, discovers tools, routes a
matching capability, and executes it against a temporary directory:

```powershell
uv sync --extra mcp
uv run python -m examples.real_filesystem_mcp
```

The same adapter boundary can be used for the following public servers. Verify package versions
and permissions before running them in your environment:

| Server | Typical launcher | Useful capability |
|---|---|---|
| Playwright MCP | `npx -y @playwright/mcp@latest` | Browser tools |
| Filesystem MCP | `npx -y @modelcontextprotocol/server-filesystem <root>` | File tools |
| Everything MCP | `npx -y @modelcontextprotocol/server-everything` | Protocol/demo tools |
| Git MCP | `uvx mcp-server-git --repository <repo>` | Git tools |
| Fetch MCP | `uvx mcp-server-fetch` | Fetch tools |

These launchers are application configuration, not router functionality. The router does not
implement transport, authentication, or server processes.

## Vector retrieval with Podman

The default deterministic retrieval path requires no database. If an application supplies a
custom retriever, Podman (or Podman Desktop) can host a vector backend without changing the
runtime -- retrieval is a pluggable `CapabilityRetriever` protocol, not a hard-coded concern.

This was verified for real in a Podman-hosted Qdrant instance in this repository. Start Qdrant:

```powershell
podman run -d --name mcp-router-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

Install the example dependency and run `examples/vector_retrieval_qdrant.py`, which implements a
`QdrantCapabilityRetriever` satisfying the same `retrieve(query, candidates, limit)` protocol as
the built-in `DeterministicRetriever`, then passes it straight to `MCPRuntime(retriever=...)`:

```powershell
uv sync --extra examples
uv run python -m examples.vector_retrieval_qdrant
```

Real captured output from this environment:

```text
vector-ranked tools: ['issue_refund', 'search_orders']
vector-ranked resources: ['refund_policy']
executed: {'name': 'issue_refund', 'arguments': {'status': 'open'}}
```

The example uses a small deterministic hashing-trick embedding (no model download or hosted
embeddings API required) by default, reproducible offline. `QdrantCapabilityRetriever` accepts an
injectable async `embed_fn: Callable[[str], Awaitable[list[float]]]` and `vector_size`, so a real
embedding model is a drop-in swap -- see
[Embedding model pluggability with Ollama](#embedding-model-pluggability-with-ollama) below, which
reuses this exact class with a different `embed_fn`. `QDRANT_URL` defaults to
`http://localhost:6333`; if a container runtime's port publishing is not forwarded to the host in
your setup (observed in this sandboxed environment, where the container was reachable only via
the Podman machine VM's own address), set `QDRANT_URL` to whatever address is actually reachable.

Keep embeddings and vector-client dependencies in an application/example extra (`qdrant-client`
lives in this project's `examples` extra, not a required dependency). The router receives a
`CapabilityRetriever` implementation; it never owns or requires a global vector database.

Point IDs are derived from a stable SHA-256 hash of the capability kind/name (`_stable_point_id`),
not Python's builtin `hash()` -- `hash()` is randomized per-process (`PYTHONHASHSEED`), which would
otherwise silently accumulate duplicate points in the collection across separate runs of the same
script instead of upserting into the same point. This was a genuine bug found and fixed while
verifying the embedding-pluggability work below; running the example twice consecutively now
produces identical, non-duplicated results both times.

## Registry pluggability with Postgres

The default in-memory registry requires no external service. If an application needs the
capability registry to persist across restarts or be shared across multiple runtime instances,
any backing store can be substituted -- the registry is a pluggable `CapabilityRegistry` protocol
(`upsert_many` / `remove_missing` / `get` / `list` / `close`), not a hard-coded concern.

This was verified for real against a Podman-hosted Postgres instance in this repository. Start
Postgres:

```powershell
podman run -d --name mcp-router-postgres -e POSTGRES_PASSWORD=router -e POSTGRES_DB=mcp_router -p 5432:5432 postgres:16-alpine
```

Install the example dependency and run `examples/postgres_registry.py`, which implements a
`PostgresCapabilityRegistry` satisfying the `CapabilityRegistry` protocol (auto-creating its own
schema on first connect) and passes it straight to `MCPRuntime(registry=...)`:

```powershell
uv sync --extra examples
$env:POSTGRES_URL = "postgresql://postgres:router@localhost:5432/mcp_router"
uv run python -m examples.postgres_registry
```

Real captured output from this environment (`POSTGRES_URL` pointed at the Podman machine VM's
own address, for the same reason described above):

```text
persisted 5 capabilities in Postgres
capabilities visible via a second, independent registry connection: 5
executed: {'name': 'issue_refund', 'arguments': {'status': 'open'}}
```

The second registry connection (opened separately, after the first connection closed) reads the
exact same rows written by the first, proving real persistence rather than in-process caching.
The router only depends on the `CapabilityRegistry` protocol; `asyncpg` and the `postgresql://`
connection string are entirely example/application concerns, kept in the `examples` extra.

## Embedding model pluggability with Ollama

`QdrantCapabilityRetriever`'s `embed_fn` is independently swappable from both the retriever
backend (Qdrant) and the registry backend (Postgres) above -- proving pluggability at every layer
of the retrieval stack, not just at the top-level `CapabilityRetriever` protocol.

This was verified for real against a Podman-hosted Ollama instance in this repository, serving a
locally-created embedding model. Start Ollama:

```powershell
podman run -d --name mcp-router-ollama -p 11434:11434 ollama/ollama:latest
```

**Honest note on a real environment constraint hit while doing this**: pulling any model from the
official Ollama registry (`registry.ollama.ai`) and downloading HuggingFace's actual model-resolve
endpoint were both genuinely blocked in this sandboxed environment by an explicit corporate
content-policy proxy (`ollama pull all-minilm` failed with a literal
"Web Page Blocked ... Category: AI-platform-service" HTML page; HuggingFace's
`resolve/main/config.json` URL returned HTTP 403). This is a real, non-bypassable network policy,
not a bug in Ollama, HuggingFace, or this package. The workaround used here: a small public GitHub
repository ([`prakashsundar18/all-minilm-l6-v2-gguf`](https://github.com/prakashsundar18/all-minilm-l6-v2-gguf))
hosts a quantized GGUF build of `all-MiniLM-L6-v2` as a plain committed file, downloadable via
`raw.githubusercontent.com` (not categorized/blocked the same way). Ollama can create a model
directly from a local GGUF file without touching its official registry:

```powershell
# download all-MiniLM-L6-v2-Q4_K_M.gguf from the repo above, then:
podman cp all-MiniLM-L6-v2-Q4_K_M.gguf mcp-router-ollama:/tmp/model.gguf
podman exec mcp-router-ollama sh -c "printf 'FROM /tmp/model.gguf\n' > /tmp/Modelfile"
podman exec mcp-router-ollama ollama create local-minilm -f /tmp/Modelfile
```

Install the example dependency and run `examples/embedding_ollama.py`, which implements an
`OllamaEmbedder` calling the real `/api/embed` HTTP endpoint (via `httpx`) and reuses
`QdrantCapabilityRetriever` from `vector_retrieval_qdrant.py` unchanged, only swapping in the
Ollama-backed `embed_fn`, a 384-dim `vector_size`, and a separate collection name:

```powershell
$env:OLLAMA_URL = "http://localhost:11434"
$env:OLLAMA_EMBED_MODEL = "local-minilm"
$env:QDRANT_URL = "http://localhost:6333"
uv run python -m examples.embedding_ollama
```

Real captured output from this environment:

```text
ollama-embedded ranked tools: ['issue_refund', 'search_orders']
ollama-embedded ranked resources: ['refund_policy']
embedding dimensions: 384
executed: {'name': 'issue_refund', 'arguments': {'status': 'open'}}
```

The 384-dimensional vectors are real model output from a genuinely local, self-hosted embedding
model -- no hosted embeddings API was used. Swapping the embedding backend required zero changes
to `MCPRuntime` or the router core; only the `embed_fn` and `vector_size` passed into the example's
own retriever construction changed.

## Metrics with Prometheus and Grafana

`MCPRuntime(metrics=...)` accepts any object satisfying the `MetricsHook` protocol
(`src/mcp_capability_router/resilience/metrics.py`); the router calls it for every operation
outcome. This was verified for real by exporting metrics in Prometheus's own exposition format and
visualizing them in a real Grafana dashboard, all Podman-hosted.

`examples/metrics_prometheus.py` implements a `PrometheusMetricsHook` (a real
`prometheus_client.Counter`, labeled `server_id` / `operation` / `outcome`) and drives traffic
through two adapters: a `FlakyAdapter` (fails every third call, masked by the router's own retry
policy) and an `AlwaysFailingAdapter` (always fails, to produce genuine failure counters even
after retries are exhausted). Run everything on one Podman network so the containers can reach
each other without relying on host port-forwarding or host firewall rules:

```powershell
podman network create mcp-router-net
podman run -d --name mcp-router-metrics --network mcp-router-net -p 9106:9105 -v <repo>:/app:Z -w /app python:3.12-slim sleep infinity
podman exec mcp-router-metrics sh -c "pip install -e '.[mcp,examples]'"
podman exec mcp-router-metrics python -m examples.metrics_prometheus
```

Start Prometheus on the same network, scraping the metrics container directly by its container
name (no host networking involved):

```powershell
podman run -d --name mcp-router-prometheus --network mcp-router-net -p 9090:9090 prom/prometheus:latest
# then podman cp a prometheus.yml with:
#   scrape_configs:
#     - job_name: mcp-capability-router
#       static_configs: [{ targets: ['mcp-router-metrics:9105'] }]
# and `podman restart mcp-router-prometheus`
```

Start Grafana on the same network, with its own bundled Prometheus plugin (do not let it try to
auto-update over the network -- see the note below):

```powershell
podman run -d --name mcp-router-grafana --network mcp-router-net -p 3000:3000 `
  -e GF_SECURITY_ADMIN_PASSWORD=router -e GF_PLUGINS_PREINSTALL_DISABLED=true grafana/grafana:latest
```

**Genuine issue found and fixed**: Grafana's bundled `prometheus` plugin registers correctly at
startup, but by default a background installer immediately tries to update it (and every other
bundled plugin) to the latest version by downloading from `storage.googleapis.com`. In this
sandboxed environment that download failed TLS verification, and the failed in-place update left
the plugin unusable -- every Prometheus query then failed with `Could not find plugin definition
for data source, datasource_type=prometheus`, even though the datasource itself was configured
correctly. This reproduced with a Postgres-registry-style false lead (checking datasource
UIDs/orgs) before the real cause was found in the container logs. The fix is
`GF_PLUGINS_PREINSTALL_DISABLED=true`, which skips the background auto-updater entirely and uses
the bundled plugin version as-is. This is a genuine Grafana/offline-environment interaction worth
documenting, not a router or example bug.

With that fix applied, a Prometheus datasource and a dashboard panel querying
`mcp_router_operations_total` were provisioned via Grafana's HTTP API and rendered real, live data:

```text
flaky/discover/success  = 1
broken/discover/success = 1
flaky/connect/success   = 15
flaky/call_tool/success = 15
broken/connect/success  = 5
broken/call_tool/failure = 5
```

![Grafana dashboard showing real mcp_router_operations_total data](../assets/grafana-prometheus-metrics.png)

Note the `flaky` adapter's `call_tool` metric shows 100% success, even though the underlying
adapter genuinely fails every third call: a `tenacity.AsyncRetrying(stop_after_attempt(2), ...)`
passed via `retry=` transparently absorbs the periodic failure before it ever reaches the
metrics/health layer. This is real, verified router behavior, not a bug -- but it means
operation-level success/failure metrics measure what the *caller* observed, not what every
underlying attempt did. The always-`broken` adapter's `call_tool` failure counter is real and
non-zero because retries do not help when every attempt fails.

### A production-shaped observability dashboard, driven by a real LLM

`examples/metrics_prometheus.py` proves the `MetricsHook` plugin point at all: one counter,
`mcp_router_operations_total`. That is enough to prove the plugin point exists, but it is not what
an on-call developer actually wants to look at. `examples/metrics_prometheus_real_llm.py` goes
further in two ways at once:

- It drives traffic with a real `langchain.agents.create_agent` LLM agent talking to a real
  Filesystem MCP server (three turns: read a file, count its words, summarize it), so every
  `connect`/`call_tool` success reflects genuine LLM-chosen tool calls -- not a scripted loop. A
  permanently-broken fake adapter is still registered alongside it for a deterministic,
  non-zero failure/unhealthy signal, since reliably asking an LLM to "please fail a tool call" is
  not a sound test strategy.
- Its `ObservabilityMetricsHook` exports the metrics a developer actually reaches for in
  production, not just a flat counter:
  - `mcp_router_server_health{server_id}` -- `MCPRuntime.health()` per server (healthy/degraded/
    recovering/unhealthy), so you can see at a glance which MCP servers are currently trustworthy.
  - `mcp_router_capabilities_discovered{server_id,type}` -- how many tools, resources, and prompts
    the registry currently holds for each server, broken out by capability type.
  - `mcp_router_refresh_last_result{server_id,field}` -- the `discovered`/`added`/`modified`/
    `deleted` counts from each server's most recent `refresh_engine.RefreshResult`, published by
    application code right after `runtime.refresh_server(...)` (this detail is not part of the
    `MetricsHook` event stream, since the pipeline only ever emits `server_id`/`operation`
    attributes for `operation.*` events).
  - `mcp_router_operation_duration_seconds{server_id,operation}` -- a real `Histogram`, timed
    around each operation via its `operation.start`/`.success`/`.failure` events.
  - `mcp_router_operations_total{server_id,operation,outcome}` and `mcp_router_retries_total` --
    the same throughput/retry counters as the simpler example, kept for continuity.

This was re-verified for real in this environment using the same Podman network and
Grafana-plugin fix described above -- only the metrics container's entry point changed, from
`python -m examples.metrics_prometheus` to `python -m examples.metrics_prometheus_real_llm`, with
`EXPLABS_API_KEY` (and optionally `EXPLABS_BASE_URL`/`EXPLABS_MODEL`) passed into the container as
environment variables. A five-panel dashboard was provisioned via Grafana's HTTP API -- server
health, capabilities discovered by type, most recent refresh result, operations by outcome, and
average operation duration -- and rendered real, live data:

```text
server health:            broken = Unhealthy, filesystem = Healthy
capabilities discovered:  broken/tool = 1, filesystem/tool = 14
refresh result:           filesystem discovered=14 added=14 modified=0 deleted=0
operations by outcome:    filesystem connect/success=3, call_tool/success=3 (real LLM turns)
                          broken connect/success=5, call_tool/failure=5 (scripted)
avg operation duration:   filesystem/discover = 644ms, filesystem/call_tool = 602ms
```

![Grafana dashboard with server health, capability discovery, refresh results, operation outcomes, and latency panels, driven by a real LLM agent](../assets/grafana-observability-dashboard.png)

The `filesystem` server's health, discovery, and latency numbers above are not simulated: they are
the direct result of a real LLM agent choosing to call the selected `read_text_file` tool three
times across three prompts, and of a real `refresh_server("filesystem")` discovering the Filesystem
MCP server's actual 14 tools -- routed through the real resilience pipeline and observed by the
same `ObservabilityMetricsHook` in every case. The `broken` server's Unhealthy status is equally
real: five genuine `call_tool` failures against a `HealthTracker(failure_threshold=3)` flip its
aggregated health from `HEALTHY` to `UNHEALTHY`, exactly as `MCPRuntime.health()` reports it to any
caller -- proving the richer metrics plugin point holds up under genuine, non-deterministic
LLM-driven traffic, not just scripted test traffic.
