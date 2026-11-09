# Examples

Each example is a complete, runnable program. Run them from this directory:

```bash
cd examples
uv sync --all-extras --group examples
uv run python 01_quickstart.py
```

The demo servers in [`common.py`](common.py) run in process through FastMCP, so
the examples need no network, no subprocess, and no credentials unless noted.
The expected output of every deterministic example is stored in
[`output/`](output/) and verified in continuous integration with
`scripts/run_examples.py`.

Most examples use only the core package. The **Extra** column names the extra
an example needs, such as `pip install "mcp-capability-router[langchain]"`.

| Example | Shows | Extra |
| --- | --- | --- |
| [`01_quickstart.py`](01_quickstart.py) | Register a server, retrieve the matching tool, and call it. | |
| [`02_capability_types.py`](02_capability_types.py) | Tools, resources, and prompts through one runtime. | |
| [`03_lazy_and_isolated.py`](03_lazy_and_isolated.py) | Lazy registration, and isolated runtimes per tenant. | |
| [`04_refresh_policies.py`](04_refresh_policies.py) | Refresh on query misses and change events, and targeted refreshes. | |
| [`05_resilience.py`](05_resilience.py) | Retries, circuit breaking, timeouts, interceptors, and health. | |
| [`06_observability.py`](06_observability.py) | Metrics in memory and in Prometheus. | |
| [`07_custom_registry.py`](07_custom_registry.py) | SQLite registry and refresh StateStore, surviving restarts. | |
| [`08_semantic_retrieval.py`](08_semantic_retrieval.py) | Hybrid ranking by words and meaning with any LangChain embedding model. | `langchain` |
| [`09_langgraph_workflow.py`](09_langgraph_workflow.py) | Routing inside a deterministic LangGraph workflow. | `langchain` |
| [`10_agent_middleware.py`](10_agent_middleware.py) | A LangChain agent that sees only the tools each turn needs. | `langchain` |
| [`11_deep_agent.py`](11_deep_agent.py) | The same middleware in a DeepAgents agent. | `langchain` |
| [`12_agent_swarm.py`](12_agent_swarm.py) | A langgraph-swarm network of agents scoped to one server each. | `langchain` |
| [`13_postgres_registry.py`](13_postgres_registry.py) | PostgreSQL registry and per-server StateStore shared by processes. | |
| [`14_stdio_servers.py`](14_stdio_servers.py) | The official Filesystem MCP server, launched over stdio. | |
| [`15_scale.py`](15_scale.py) | Routing among 10,000 capabilities from 20 servers. | |
| [`16_opentelemetry.py`](16_opentelemetry.py) | MCP client spans and refresh metrics, in memory or over OTLP. | `otel` |
| [`17_redis_shared_state.py`](17_redis_shared_state.py) | Shared Redis circuit state and a custom result-cache store. | `redis` |
| [`18_qdrant_server.py`](18_qdrant_server.py) | The capability index in a Qdrant server, shared by processes. | |
| [`19_result_cache.py`](19_result_cache.py) | Read-only result caching, single-flight, and invalidation. | |
| [`20_mcp_gateway.py`](20_mcp_gateway.py) | The router served as one MCP server, in search and catalog modes. | |
| [`21_code_mode.py`](21_code_mode.py) | The gateway's code mode: a script chains tool calls in a sandbox. | `codemode` |
| [`22_any_framework.py`](22_any_framework.py) | Routed tools for any framework, here the plain OpenAI SDK. | |
| [`23_gateway_agent.py`](23_gateway_agent.py) | A LangChain agent that searches and calls tools through the gateway. | `langchain` |
| [`24_browser_automation.py`](24_browser_automation.py) | Routing among the tools of the Playwright MCP server. | |

## Examples with external requirements

These examples run only when their environment variable is set:

| Example | Set | Also needs |
| --- | --- | --- |
| `08_semantic_retrieval.py` | `MCP_ROUTER_EXAMPLE_EMBEDDINGS`, such as `openai:text-embedding-3-small` | The provider's package and credentials |
| `10_agent_middleware.py`, `11_deep_agent.py`, `12_agent_swarm.py`, `23_gateway_agent.py` | `MCP_ROUTER_EXAMPLE_MODEL`, such as `openai:gpt-5.4-mini` | The provider's package and credentials |
| `13_postgres_registry.py` | `MCP_ROUTER_EXAMPLE_POSTGRES_DSN` | A PostgreSQL database |
| `14_stdio_servers.py` | `MCP_ROUTER_EXAMPLE_NODE=1` | Node.js with `npx` |
| `16_opentelemetry.py` | Optional `OTEL_EXPORTER_OTLP_ENDPOINT` | An OTLP collector; unset for in-memory output |
| `17_redis_shared_state.py` | `MCP_ROUTER_EXAMPLE_REDIS_URL` | A dedicated Redis database |
| `18_qdrant_server.py` | `MCP_ROUTER_EXAMPLE_QDRANT_URL`, optional `MCP_ROUTER_EXAMPLE_EMBEDDINGS` | A Qdrant server; ranks with BM25 only when no embeddings are set |
| `22_any_framework.py` | `MCP_ROUTER_EXAMPLE_OPENAI_MODEL`, such as `gpt-5.4-mini` | `OPENAI_API_KEY`, optionally `OPENAI_BASE_URL` |
| `24_browser_automation.py` | `MCP_ROUTER_EXAMPLE_BROWSER`, such as `chromium` or `msedge` | Node.js with `npx` and a browser Playwright can drive |

LangChain models and embeddings are created with `init_chat_model` and
`init_embeddings`, so the provider reads its usual environment variables, such as
`OPENAI_API_KEY` and `OPENAI_BASE_URL` for OpenAI-compatible endpoints. The
`examples` dependency group installs `openai` and `langchain-openai`; install the
package of any other provider you use.

The test suite runs the model-based examples with scripted models, so their
wiring is verified without credentials.