# Observability

## Metrics

Pass any refresh-engine `MetricsSink`, an object with
`increment(name, value=1, attributes=None, /)` and
`observe(name, value, attributes=None, /)`, as `MCPRuntime(metrics=...)`.
`refresh_engine.InMemoryMetrics` works for tests; bridge to Prometheus or
OpenTelemetry with a small sink class.

| Metric | Kind | Attributes |
| --- | --- | --- |
| `mcp_capability_router.operations` | counter | `server_id`, `operation`, `outcome` |
| `mcp_capability_router.operation.duration` | seconds | `server_id`, `operation`, `outcome` |
| `mcp_capability_router.retries` | counter of extra attempts | `server_id`, `operation` |
| `mcp_capability_router.circuit.transitions` | counter | `server_id`, `operation`, `state` |

- `operation`: `connect`, `discover`, `call_tool`, `read_resource`, `get_prompt`.
- `outcome`: `success`, `failure`, `rejected` (open circuit), `cancelled`.
- `state`: `open`, `half_open`, `closed`.
- refresh-engine's metrics, such as `refresh_engine.refreshes` and
  `refresh_engine.refresh.duration`, arrive with a `server_id` attribute.
- A failing sink is logged and never fails an operation.

## Logs

Standard `logging`, logger `mcp_capability_router`:

| Level | Event |
| --- | --- |
| `WARNING` | A circuit opened; a background refresh (query miss, interval, change event) failed. |
| `INFO` | A circuit moved to half-open or closed. |
| `ERROR` | An unexpected error in a background refresh, a change-event source, or a metrics sink. |

FastMCP logs through the `fastmcp` logger.

## Refresh events

`RefreshPolicy(event_handlers=(handler,))` receives refresh-engine `RefreshEvent`s,
such as `EventKind.REFRESH_COMPLETED` and `RESOURCE_REFRESH_FAILED`. Handlers run off
the refresh path. `refresh_engine.StructlogEventHandler()` logs them as structured
logs.

## Health

`await runtime.health(server_id)` returns `HealthState.HEALTHY`, `DEGRADED`,
`RECOVERING`, or `UNHEALTHY`, the worst among the server's circuits, without calling
the server. Use it in readiness checks:

```python
states = {server: str(await runtime.health(server)) for server in runtime.servers}
```

## Tracing

LangChain tracing records routed tool calls like any tool call. Trace server
operations with an interceptor that opens a span around `await call_next()`.
