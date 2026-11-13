# Metrics, logging, and health

The runtime reports what it does through metrics, logs, refresh events, and health
states. None of them needs a particular monitoring stack.

## Metrics

Pass a metrics sink to the runtime. A sink subclasses refresh-engine's
`MetricsSink` and implements async `increment` and `observe`; `refresh_engine.InMemoryMetrics` is
a ready-made sink for tests and debugging:

```python
from refresh_engine import InMemoryMetrics

from mcp_capability_router import MCPRuntime

metrics = InMemoryMetrics()
runtime = MCPRuntime(metrics=metrics)
```

The runtime records these metrics for every server operation:

| Metric | Kind | Attributes |
| --- | --- | --- |
| `mcp_capability_router.operations` | Counter | `server_id`, `operation`, `outcome` |
| `mcp_capability_router.operation.duration` | Duration in seconds | `server_id`, `operation`, `outcome` |
| `mcp_capability_router.retries` | Counter of extra attempts | `server_id`, `operation` |
| `mcp_capability_router.circuit.transitions` | Counter | `server_id`, `operation`, `state` |

`operation` is one of `connect`, `discover`, `call_tool`, `read_resource`, and
`get_prompt`. `outcome` is `success`, `failure`, `rejected` when an open circuit
rejected the operation, or `cancelled`. `state` is `open`, `half_open`, or `closed`.

Each server's refreshes also report refresh-engine's metrics, such as
`refresh_engine.refreshes` and `refresh_engine.refresh.duration`, with a `server_id`
attribute added. A sink that fails is logged and never fails an operation.

### Export to Prometheus or OpenTelemetry

Install `mcp-capability-router[otel]`. Use refresh-engine's ready-made sink with
an application-owned meter provider:

```python
from opentelemetry.sdk.metrics import MeterProvider
from refresh_engine.otel import OpenTelemetryMetricsSink

from mcp_capability_router import MCPRuntime

provider = MeterProvider()
sink = OpenTelemetryMetricsSink(provider.get_meter("mcp_capability_router"))
runtime = MCPRuntime(metrics=sink)
```

The [observability example](../examples.md#observability) bridges to
`prometheus_client` the same way.

## Logging

The runtime logs to the `mcp_capability_router` logger with the standard `logging`
module:

| Level | Message |
| --- | --- |
| `WARNING` | A circuit opened, or a refresh triggered by a query miss, an interval, or a change event failed. |
| `INFO` | A circuit moved to half-open or closed. |
| `ERROR` | An unexpected error in a background refresh, a change-event source, or a metrics sink. |

Configure it like any other logger:

```python
import logging

logging.getLogger("mcp_capability_router").setLevel(logging.INFO)
```

## Refresh events

`RefreshPolicy.event_handlers` receive the lifecycle events of a server's refreshes,
such as `REFRESH_STARTED`, `RESOURCE_REFRESH_FAILED`, and `REFRESH_COMPLETED`.
Handlers run off the refresh path, so a slow or failing handler never delays or fails
a refresh. refresh-engine's `StructlogEventHandler` writes them as structured logs:

```python
from refresh_engine import StructlogEventHandler

from mcp_capability_router import RefreshPolicy

policy = RefreshPolicy(interval=300, event_handlers=(StructlogEventHandler(),))
```

## Health

`health(server_id)` derives the health of a server from its circuit breakers and
returns the worst state among its operations: `HEALTHY`, `DEGRADED`, `RECOVERING`, or
`UNHEALTHY`. It never calls the server, so it is cheap enough for every readiness
probe:

```python
from mcp_capability_router import HealthState


async def readiness() -> dict[str, str]:
    states = {server: await runtime.health(server) for server in runtime.servers}
    return {server: str(state) for server, state in states.items()}


async def unhealthy_servers() -> list[str]:
    return [
        server
        for server in runtime.servers
        if await runtime.health(server) is HealthState.UNHEALTHY
    ]
```

## Tracing

The runtime traces every server operation with OpenTelemetry, with no extra to
install. Tracing uses only the OpenTelemetry API, so nothing is recorded until the
application configures an SDK. Install `mcp-capability-router[otel]` for the SDK,
then set a tracer provider:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from mcp_capability_router import MCPRuntime

trace.set_tracer_provider(TracerProvider())
runtime = MCPRuntime()
```

Pass `tracer_provider=` to the runtime instead of using the global provider. Each
operation records one client span, named after the MCP method and its target, such
as `tools/call search_docs`. Spans include the method, server ID, and tool name,
prompt name, or resource URI. For tool calls, the router also records arguments
and results as JSON in `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result`.
Langfuse recognizes these attributes as the tool observation's input and output.
The result includes the adapter's full return value, including FastMCP content
blocks and structured content. Errors set the span status and record the
exception; a failed call has no result attribute. The span covers every retry
attempt and the other interceptors, including cache hits.

**Tool content may contain secrets or personal data and is captured by default.**
Set `capture_tool_content=False` to omit both attributes from router spans:

```python
runtime = MCPRuntime(capture_tool_content=False)
```

The option applies to router spans only. FastMCP, the MCP SDK, remote servers,
other instrumentation, and exception messages may record data independently;
configure them and your collector separately to meet your privacy requirements.
Prompt arguments and resource contents are not captured by the router. If a
tool's arguments or result cannot be serialized as JSON, the router logs a
warning and omits that attribute without changing the tool call's outcome.

FastMCP, which connects to the servers, records spans of its own for the same
operations. The `tracing` option chooses which spans to keep, so each call appears
once:

| `tracing` | Spans recorded |
| --- | --- |
| `"router"` (default) | One router span per operation; FastMCP's spans within it are suppressed |
| `"fastmcp"` | FastMCP's spans only, as without the router |
| `"all"` | The router span with FastMCP's spans nested in it, for debugging |
| `"off"` | Neither router nor FastMCP spans |

```python
runtime = MCPRuntime(tracing="off")
```

In every mode the runtime propagates the trace context to servers, so spans that a
remote server records nest under the operation. In-process servers share the
caller's context, so their FastMCP spans follow the same mode. The MCP SDK
records a short `MCP send <method>` transport span under each operation, with the
instrumentation scope `mcp-python-sdk`; drop it in the collector or exporter by
scope if it is not wanted. The router's scope is
[`INSTRUMENTATION_NAME`](../api/extensions.md), `mcp_capability_router`.

To choose the tracer or the interceptor's position in the chain, pass an
`OpenTelemetryInterceptor` among the runtime's `interceptors`; the runtime then
adds no other. An explicit interceptor controls its own content capture; configure
`OpenTelemetryInterceptor(capture_tool_content=False)` to disable it:

```python
from opentelemetry import trace

from mcp_capability_router import MCPRuntime
from mcp_capability_router.otel import OpenTelemetryInterceptor

runtime = MCPRuntime(interceptors=[OpenTelemetryInterceptor(trace.get_tracer("my-service"))])
```

LangChain tracing, such as LangSmith, also records routed agent tool calls.

Providers, exporters, and their shutdown belong to the application. The
[OpenTelemetry example](../examples.md#opentelemetry) prints the span tree in
memory and exports to an OTLP collector. Configure a metrics reader and a span
processor before routing calls.
