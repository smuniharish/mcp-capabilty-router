# API reference

The public API is intentionally small. Internal discovery, interceptor, and resilience modules
may evolve independently; applications should depend on the symbols documented here.

## `MCPRuntime`

### Construction

```python
MCPRuntime(
    *,
    registry: CapabilityRegistry | None = None,
    retriever: CapabilityRetriever | None = None,
    max_concurrency: int = 16,
    operation_timeout: float | None = None,
    retry: tenacity.AsyncRetrying | None = None,
    rate_limiter: aiolimiter.AsyncLimiter | None = None,
    interceptors: Iterable[Interceptor[Any]] = (),
    metrics: MetricsHook | None = None,
)
```

* `registry` injects an application-owned async metadata store. `InMemoryRegistry` is the
  isolated default.
* `retriever` injects lexical, metadata, hybrid, or vector retrieval. The default is
  `DeterministicRetriever`.
* `max_concurrency` bounds active tool/resource/prompt operations for this runtime.
* `operation_timeout`, `retry`, and `rate_limiter` configure the runtime operation pipeline.
  `retry`/`rate_limiter` accept real `tenacity.AsyncRetrying`/`aiolimiter.AsyncLimiter`
  instances, built from those libraries' own primitives. See
  [resilience](../operations/resilience.md) for behavior and limits.
* `interceptors` wraps every operation in an ordered chain of application-supplied
  `Interceptor` instances (for example, request logging or argument validation) that run
  inside the bulkhead but outside the circuit breaker and retry loop.
* `metrics` injects a `MetricsHook` observing every pipeline event. `NullMetrics` is the
  default. See [Extension protocols](#extension-protocols) below.

### Lifecycle and server management

| Method | Contract |
|---|---|
| `register_server(server_id, factory, metadata=None, refresh=None)` | Register lazily or activate a per-server `RefreshPolicy`; raises `ServerError` for duplicates. |
| `register_mcp_client(server_id, client, client_server_name=None, discover_resources=False, metadata=None, refresh=None)` | Register a `MultiServerMCPClient` directly through the generic bridge with optional automatic refresh. |
| `connect(server_id)` | Connect once, deduplicating concurrent callers. |
| `reconnect(server_id)` | Close and establish a fresh adapter connection. |
| `unregister_server(server_id)` | Remove metadata, close the adapter and its `RefreshEngine`, and invalidate loaded state. |
| `refresh_server(server_id, *, mode=RefreshMode.FULL, resource_ids=())` | Discover and reconcile one server via its `refresh_engine.RefreshEngine`; returns a `RefreshResult` and raises `RefreshError` if the refresh fails outright. |
| `refresh()` | Refresh all registered servers concurrently. |
| `health(server_id)` | Return the runtime-scoped health state. |
| `close()` | Stop every scheduler and policy task, close every server's `RefreshEngine`, close adapters, and release caches. |

`RefreshPolicy(on_register=False, on_query_miss=False, interval=None, change_events=None,
mode=RefreshMode.FULL, config=None, store=None)` configures automatic triggers and the
underlying `refresh_engine.RefreshEngine` for one server. `interval` is a positive number of
seconds (backed by a `refresh_engine.AsyncScheduler`); `change_events` accepts an
`asyncio.Queue` or async iterable. `mode` is the `refresh_engine.RefreshMode` these automatic
triggers use. `config`/`store` are passed straight through to `RefreshEngine(config=, store=)`
-- `None` means refresh-engine's own recommended defaults apply. Background failures are
logged and last-known capability records remain available. See
[refresh](../operations/refresh.md) for the full reconciliation contract, modes, and
`RefreshResult.status` semantics.

### Routing and execution

| Method | Return | Notes |
|---|---|---|
| `retrieve(query, type=None, limit=20, server_id=None)` | `list[Capability]` | Deterministic or injected retrieval over metadata. |
| `query(query, type=None, limit=20, refresh_servers=(), mode=RefreshMode.FULL, resource_ids=())` | `list[Capability]` | After a miss, refreshes policy-enabled servers plus any explicit one-off hints. |
| `resolve(capability_id)` | `Capability` | Raises `CapabilityNotFoundError` when absent. |
| `load(capability_id)` | `Any` | JIT-loads one selected capability and caches it. |
| `execute(capability_id, arguments=None)` | `Any` | Calls one Tool. |
| `read_resource(capability_id)` | `Any` | Reads one Resource. |
| `get_prompt(capability_id, arguments=None)` | `Any` | Retrieves one Prompt. |

All methods are async. Network failures are chained into package exceptions such as
`DiscoveryError`, `LoadingError`, and `ServerError`; callers should not rely on silent fallbacks.

## Extension protocols

Every extension point below is a structural `typing.Protocol`: any object with matching async
methods works, with or without inheriting from anything. Each also ships an optional
`*Base` abstract base class as a convenience for implementers who want a concrete,
discoverable template — subclassing it means a forgotten method fails loudly at
instantiation time (`TypeError`) instead of silently no-op-ing the first time the runtime
calls it. Neither style is required; the built-in defaults (`InMemoryRegistry`,
`DeterministicRetriever`, `NullMetrics`) satisfy their protocols structurally, without
inheriting from the `*Base` classes.

* `CapabilityRegistry` / `CapabilityRegistryBase`: implement `upsert_many`, `remove_missing`,
  `remove`, `get`, `list`, and `close`. See `examples/custom_registry.py` (structural) and
  `examples/postgres_registry.py` (`CapabilityRegistryBase` subclass).
* `CapabilityRetriever` / `CapabilityRetrieverBase`: implement async
  `retrieve(query, candidates, limit=...)`. See `examples/vector_retrieval_qdrant.py`.
* `MCPAdapter` / `MCPAdapterBase`: implement the async server operation boundary (`connect`,
  `close`, `list_tools`, `list_resources`, `list_prompts`, `call_tool`, `read_resource`,
  `get_prompt`); transport and authentication remain the responsibility of
  `langchain-mcp-adapters` or your own adapter, not the router. See
  `examples/public_api_overrides.py`'s `FakeAdapter` for an `MCPAdapterBase` subclass.
* `MetricsHook` / `MetricsHookBase`: implement async
  `record(event, attributes=None)`, called for every pipeline event
  (`operation.start`/`.success`/`.failure`, `retry`/`retry.success`/`retry.failure`,
  `circuit.open`/`.half_open`/`.closed`, `fallback.triggered`). See
  `examples/metrics_prometheus.py`'s `PrometheusMetricsHook` for a `MetricsHookBase` subclass.

All four `MCPAdapter`, `MCPAdapterBase`, `MetricsHook`, `MetricsHookBase`,
`CapabilityRegistry`, `CapabilityRegistryBase`, `CapabilityRetriever`, and
`CapabilityRetrieverBase` are importable directly from the top-level `mcp_capability_router`
package.

## Errors

The stable base class is `MCPCapabilityRouterError`. Important subclasses include
`ConfigurationError`, `ServerError`, `ConnectionError`, `DiscoveryError`, `RegistryError`,
`RetrievalError`, `LoadingError`, `RefreshError`, `TimeoutError`, `CircuitOpenError`, and
`RateLimitError`.
