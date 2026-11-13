# Observability

## Metrics

Pass a refresh-engine `MetricsSink` subclass with async
`increment(name, value=1, attributes=None, /)` and
`observe(name, value, attributes=None, /)`, as `MCPRuntime(metrics=...)`.
`refresh_engine.InMemoryMetrics` works for tests; bridge to Prometheus or
OpenTelemetry with `refresh_engine.otel.OpenTelemetryMetricsSink`.

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

The runtime traces every server operation by default through the OpenTelemetry API;
spans appear once the application configures an SDK (the `otel` extra installs it)
globally or passes `MCPRuntime(tracer_provider=...)`. Each operation records one
client span, such as `tools/call search_docs`, with scope `mcp_capability_router`.
Tool arguments and results are recorded as JSON in `gen_ai.tool.call.arguments`
and `gen_ai.tool.call.result` by default, including potentially sensitive data.
Use `MCPRuntime(capture_tool_content=False)` to omit them from router spans.
This does not control FastMCP, remote servers, other instrumentation, or exception
messages. Prompt arguments and resource contents are not captured by the router.

`MCPRuntime(tracing=...)` chooses the spans, so each call appears once:

- `"router"` (default): router spans; FastMCP's spans within them are suppressed.
- `"fastmcp"`: FastMCP's spans only.
- `"all"`: both, nested, for debugging.
- `"off"`: neither.

The trace context reaches servers in every mode. The MCP SDK's `MCP send ...`
transport spans (scope `mcp-python-sdk`) remain; filter them by scope in the
collector. Pass an `OpenTelemetryInterceptor` among `interceptors` to choose the
tracer or its position; the runtime then adds none and the explicit interceptor's
own `capture_tool_content` setting applies. LangChain tracing records
routed tool calls like any tool call. Configure and shut down providers in the
application.
