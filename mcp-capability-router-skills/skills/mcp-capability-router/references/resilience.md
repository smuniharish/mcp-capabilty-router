# Resilience

Every server operation (`connect`, `discover`, `call_tool`, `read_resource`,
`get_prompt`) runs through one pipeline, outermost first:

1. the concurrency limit, `max_concurrency` (16), across all servers;
2. the `interceptors`, in order, once per operation;
3. the circuit breaker of the server and operation (purgatory);
4. the `retry` policy (tenacity);
5. per attempt: the `rate_limiter` (aiolimiter), then `operation_timeout`.

## Production configuration

```python
from aiolimiter import AsyncLimiter
from purgatory import AsyncCircuitBreakerFactory
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
    circuit_breaker=AsyncCircuitBreakerFactory(default_threshold=5, default_ttl=30),
)
```

- Without `retry`, each operation makes one attempt. The runtime always re-raises the
  last error, never a tenacity `RetryError`.
- Without `circuit_breaker`, each server gets in-memory circuits (5 failures, 30
  seconds), discarded on unregister. A shared factory, for example with
  `AsyncRedisUnitOfWork(url)` from `purgatory[redis]` and `await factory.initialize()`,
  shares circuit state between runtimes that register the same servers under the same
  IDs. Its `exclude` list is checked before the router's classification.
- A timeout raises the built-in `TimeoutError` with a note naming the operation and
  server. Waiting for the rate limit does not count toward the timeout.

## Classification

| Retried and counted by circuits | Never retried, never counted |
| --- | --- |
| `ServerConnectionError`, `ConnectionError`, `TimeoutError`, `ServerUnavailableError`, `RateLimitError`, `ResourceReadError`, `PromptRetrievalError`, unknown exceptions | `AuthenticationError`, `AuthorizationError`, `InvalidRequestError`, `ConfigurationError`, `ServerNotFoundError`, `CapabilityTypeError`, `RuntimeClosedError`, `CapabilityNotFoundError`, `ProtocolError`, `DiscoveryError`, `ToolExecutionError`, cancellation |

`categorize_failure(error)` returns the `FailureCategory`; `is_retryable(error)`
returns whether to retry. A `RefreshError` is categorized by its cause.

## Circuit behavior

- Circuits count operations, not attempts; retries run inside the circuit.
- At the threshold, the circuit opens: operations raise `CircuitOpenError` without
  calling the server.
- After the open period, operations are trial calls: a success closes the circuit; a
  failure reopens it. Every operation that arrives before the first trial finishes is
  admitted as a trial.
- An operation that ends without a counted failure, including a non-retryable failure
  or a cancellation, resets the consecutive-failure count.

## Interceptors

```python
async def audit(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    try:
        return await call_next()
    finally:
        log.info("%s on %s", context.operation, context.server_id)
```

Interceptors must return `await call_next()` or raise. Raise `AuthorizationError` to
reject an operation without retries or circuit impact. Use one `AsyncLimiter` per
server inside an interceptor to rate-limit servers separately.

## Health

`await runtime.health(server_id)` returns the worst state among the server's circuits:
`HEALTHY`, `DEGRADED` (recent failures, circuit closed), `RECOVERING` (trial calls
admitted), or `UNHEALTHY` (circuit open). It never calls the server.
