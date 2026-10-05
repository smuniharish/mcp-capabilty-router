# Production checklist

Review these points before routing production traffic.

## Lifecycle

- [ ] Create one runtime per tenant, agent, or trust boundary, and reuse it across
      requests.
- [ ] Close every runtime on shutdown, for example in the lifespan of your web
      application.
- [ ] Register each server under a stable ID; capability IDs, metrics, and health are
      keyed by it.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mcp_capability_router import MCPRuntime, RefreshPolicy


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with MCPRuntime(operation_timeout=30) as runtime:
        await runtime.register_mcp(
            "docs",
            "https://docs.example.com/mcp",
            refresh=RefreshPolicy(on_register=True, on_query_miss=True, interval=900),
        )
        app.state.router = runtime
        yield


app = FastAPI(lifespan=lifespan)
```

## Discovery

- [ ] Choose a refresh policy for every server: `on_register` for servers that must
      be ready at startup, `change_events` for servers that announce changes, and
      `on_query_miss` with a long `interval` as a safety net.
- [ ] To keep capabilities across restarts or share them between processes, use a
      durable registry, and let one process refresh each server.

## Resilience

- [ ] Set `operation_timeout`.
- [ ] Configure `retry` with `retry_if_exception(is_retryable)`, a small number of
      attempts, and exponential backoff with jitter.
- [ ] Tune circuit-breaker thresholds and open periods to the servers' failure
      patterns; share breaker state between replicas when they call the same servers.
- [ ] Respect the servers' quotas with `rate_limiter` or per-server interceptors.
- [ ] Size `max_concurrency` to what your servers and process can handle.

## Security

- [ ] Pass credentials through targets or adapter factories, never through tool
      arguments.
- [ ] Register only trusted servers, and scope local servers to the resources they
      need.
- [ ] Restrict destructive tools with an interceptor, an allow-list, or human
      approval.

## Observability

- [ ] Export the runtime's metrics to your monitoring system.
- [ ] Collect `WARNING` and higher from the `mcp_capability_router` logger.
- [ ] Report `health(server_id)` in readiness checks and dashboards.
- [ ] Alert on open circuits, rising failure outcomes, and failed refreshes.

## Agents

- [ ] Tune `limit` of the routing middleware, and scope agents with `server_id` where
      possible.
- [ ] Check retrieval quality on real requests: log the routed tools, and adjust tool
      descriptions, tags, or the retriever until the right tools are routed.
- [ ] Invoke agents asynchronously, with `ainvoke` or `astream`.

## Testing

- [ ] Test routing with in-process servers, failures with injected adapters, and
      agents with scripted models; see [Testing integrations](testing.md).
