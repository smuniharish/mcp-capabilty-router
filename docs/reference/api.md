# API reference

The public API is intentionally small. Internal discovery, interceptor, and resilience modules
may evolve independently; applications should depend on the symbols documented here.

::: mcp_capability_router.runtime.MCPRuntime

::: mcp_capability_router.models

::: mcp_capability_router.registry

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

* `CapabilityRegistry`: implement `upsert_many`, `remove_missing`, `remove`, `get`, `list`, and
  `close`.
* `CapabilityRetriever`: implement async `retrieve(query, candidates, limit=...)`.
* `MCPAdapter`: implement the async server operation boundary; transport and authentication
  remain the responsibility of `langchain-mcp-adapters` and the application.

## Errors

The stable base class is `MCPCapabilityRouterError`. Important subclasses include
`ConfigurationError`, `ServerError`, `ConnectionError`, `DiscoveryError`, `RegistryError`,
`RetrievalError`, `LoadingError`, `RefreshError`, `TimeoutError`, `CircuitOpenError`, and
`RateLimitError`.

## Main operations

| Method | Purpose |
|---|---|
| `register_server` | Add a lazy factory or adapter |
| `refresh_server` / `refresh` | Discover and reconcile metadata |
| `retrieve` / `query` | Find ranked capabilities |
| `load` | Load one selected capability |
| `execute` | Invoke a tool |
| `read_resource` | Read a resource |
| `get_prompt` | Retrieve a prompt |
| `connect` / `reconnect` | Manage one server connection |
| `health` | Read the handle health state |
| `close` | Release runtime resources |
