# Resilience

Every operation that the runtime performs on a server — connecting, discovering,
calling a tool, reading a resource, rendering a prompt — runs through one resilience
pipeline. The pipeline is built from established libraries:
[tenacity](https://tenacity.readthedocs.io) for retries,
[purgatory](https://pypi.org/project/purgatory/) for circuit breakers, and
[aiolimiter](https://aiolimiter.readthedocs.io) for rate limits.

![Resilience pipeline](../assets/diagrams/resilience-pipeline-light.png#only-light)
![Resilience pipeline](../assets/diagrams/resilience-pipeline-dark.png#only-dark)

## Configure the pipeline

```python
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from mcp_capability_router import MCPRuntime, is_retryable

runtime = MCPRuntime(
    max_concurrency=32,
    operation_timeout=30,
    retry=AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.2, max=5),
        retry=retry_if_exception(is_retryable),
    ),
    rate_limiter=AsyncLimiter(100, time_period=1),
)
```

| Setting | Default | Applies to |
| --- | --- | --- |
| `max_concurrency` | 16 | Operations in flight, across all servers. |
| `interceptors` | none | Each operation, once. |
| `circuit_breaker` | 5 failures, 30 seconds, per server | Each operation, per server and operation. |
| `retry` | one attempt | Each operation. |
| `rate_limiter` | none | Each attempt, across all servers. |
| `operation_timeout` | none | Each attempt. |

## Timeouts

`operation_timeout` bounds each attempt, in seconds. An attempt that takes longer is
cancelled and raises the built-in `TimeoutError`, with a note that names the
operation and the server. Time spent waiting for the rate limit does not count
toward the timeout. Set a timeout in production: without one, a server that stops
answering holds a concurrency slot indefinitely.

## Retries

`retry` takes a tenacity `AsyncRetrying` policy that decides how many attempts to make
and how long to wait between them. The runtime always re-raises the error of the last
attempt, never a tenacity `RetryError`. Use `retry_if_exception(is_retryable)` as the
predicate, so that only failures that can pass on another attempt are retried.

## Failure classification

`categorize_failure` maps every exception to a `FailureCategory`, and `is_retryable`
decides from the category:

<!-- test -->
```python
from mcp_capability_router import (
    AuthenticationError,
    ServerUnavailableError,
    ToolExecutionError,
    categorize_failure,
    is_retryable,
)

for error in (
    ServerUnavailableError("overloaded"),
    TimeoutError(),
    AuthenticationError("expired token"),
    ToolExecutionError("unknown customer"),
):
    category = categorize_failure(error)
    print(f"{type(error).__name__}: {category}, retryable={is_retryable(error)}")
```

```text
ServerUnavailableError: server_unavailable, retryable=True
TimeoutError: timeout, retryable=True
AuthenticationError: authentication_failure, retryable=False
ToolExecutionError: tool_execution_failure, retryable=False
```

| Category | Raised as | Retried |
| --- | --- | --- |
| `connection_failure` | `ServerConnectionError`, `ConnectionError` | Yes |
| `timeout` | `TimeoutError` | Yes |
| `server_unavailable` | `ServerUnavailableError` | Yes |
| `rate_limited` | `RateLimitError` | Yes |
| `resource_read_failure` | `ResourceReadError` | Yes |
| `prompt_retrieval_failure` | `PromptRetrievalError` | Yes |
| `unknown` | Any other exception | Yes |
| `authentication_failure` | `AuthenticationError` | No |
| `authorization_failure` | `AuthorizationError` | No |
| `invalid_request` | `InvalidRequestError`, `ConfigurationError`, `ServerNotFoundError`, `CapabilityTypeError`, `RuntimeClosedError` | No |
| `capability_not_found` | `CapabilityNotFoundError` | No |
| `protocol_failure` | `ProtocolError`, `DiscoveryError` | No |
| `tool_execution_failure` | `ToolExecutionError` | No |

Failures that are retried also count toward the circuit breaker. Repeating a rejected
request fails the same way, and a tool may have side effects, so the other failures
are never retried. They also prove that the server answered, so they never open a
circuit. Cancellation is never retried and never counted.

`FastMCPAdapter` translates FastMCP, MCP, and HTTP errors into these exceptions: for
example, HTTP 401 becomes `AuthenticationError`, 429 becomes `RateLimitError`, and
5xx responses become `ServerUnavailableError`.

## Circuit breakers

Each server has a circuit breaker for each kind of operation, so a server whose tool
calls fail can still be discovered, and the other way around. A circuit counts
operations, not attempts: retries run inside it, so an operation that failed after
three attempts counts as one failure.

![Health states](../assets/diagrams/health-states-light.png#only-light)
![Health states](../assets/diagrams/health-states-dark.png#only-dark)

1. While the circuit is **closed**, operations run normally, and consecutive
   failures that count are tracked.
2. When the failures reach the threshold, the circuit **opens**: operations fail with
   `CircuitOpenError` immediately, without calling the server.
3. When the open period elapses, operations are admitted as **trial calls**. A success
   closes the circuit; a failure opens it again for another period.

The defaults are a threshold of 5 failures and an open period of 30 seconds. Change
them, or share circuit state between processes, with a purgatory factory:

```python
from purgatory import AsyncCircuitBreakerFactory, AsyncRedisUnitOfWork

breakers = AsyncCircuitBreakerFactory(
    default_threshold=3,
    default_ttl=60,
    uow=AsyncRedisUnitOfWork("redis://localhost:6379/0"),
)
await breakers.initialize()
runtime = MCPRuntime(circuit_breaker=breakers)
```

Install `purgatory[redis]` for Redis storage. A shared factory keys circuits by
server ID and operation, so share it only between runtimes that register the same
servers under the same IDs, such as replicas of one service. Exceptions excluded with
the factory's `exclude` argument never count as failures, before the router's own
classification applies. Without a factory, each server gets in-memory circuits that
are discarded when it is unregistered.

Two behaviors come from purgatory and are worth knowing:

- An operation that ends without a failure that counts — a success, a
  non-retryable failure, or a cancellation — resets the count of consecutive
  failures.
- After the open period, every operation that arrives before the first trial call
  finishes is admitted as a trial call.

## Rate limits

`rate_limiter` takes an aiolimiter `AsyncLimiter`, which every attempt of every
operation waits for. To limit servers separately, use an interceptor with a limiter
per server; interceptors run once per operation:

```python
from collections.abc import Awaitable, Callable
from typing import Any

from aiolimiter import AsyncLimiter

from mcp_capability_router import MCPRuntime, OperationContext

LIMITS = {"search": AsyncLimiter(10, time_period=1)}


async def limit_per_server(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    limiter = LIMITS.get(context.server_id)
    if limiter is not None:
        await limiter.acquire()
    return await call_next()


runtime = MCPRuntime(interceptors=[limit_per_server])
```

## Interceptors

Interceptors wrap every operation, in order, inside the concurrency limit and outside
the circuit breaker. They see each operation once, however many attempts it takes.
An interceptor can inspect the server, the operation, the capability, and the
arguments, do work before and after the operation, or raise to reject it. See
[Extending the router](extending.md#interceptors).

## Health

`health(server_id)` returns the worst state among the circuits of a server:

| State | Meaning |
| --- | --- |
| `HEALTHY` | No recent failures. |
| `DEGRADED` | Recent operations failed, but the circuit is still closed. |
| `RECOVERING` | The open period elapsed, and trial calls decide whether the server recovered. |
| `UNHEALTHY` | The circuit is open, and operations are rejected without calling the server. |

Use health for readiness checks, dashboards, and to steer requests away from
unhealthy servers. See [Metrics, logging, and health](observability.md).
