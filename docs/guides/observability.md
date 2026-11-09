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

LangChain tracing, such as LangSmith, records routed agent tool calls. Trace all
server operations with the optional MCP client-span interceptor:

```python
from opentelemetry.sdk.trace import TracerProvider

from mcp_capability_router import MCPRuntime
from mcp_capability_router.otel import OpenTelemetryInterceptor

provider = TracerProvider()
runtime = MCPRuntime(interceptors=[OpenTelemetryInterceptor(provider.get_tracer("my-service"))])
```

Spans include the method, server ID, and tool name or resource URI, never arguments
or results. Errors set the span status and record the exception. Add the tracing
interceptor before caching to include cache hits in the operation span.

Providers, exporters, and their shutdown belong to the application. The
[OpenTelemetry example](../examples.md#opentelemetry) shows in-memory inspection
and OTLP export to a collector. Configure a metrics reader and a span processor
before routing calls.
