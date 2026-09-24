from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

from aiolimiter import AsyncLimiter
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from .interceptor import Interceptor, InterceptorChain
from .resilience import (
    AsyncBulkhead,
    CircuitBreaker,
    HealthState,
    HealthTracker,
    MetricsHook,
    NullMetrics,
    semantic_classifier,
    with_fallback,
    with_timeout,
)
from .resilience.metrics import emit

T = TypeVar("T")
Action = Callable[[], Awaitable[T]]
_Key = tuple[str, str]

_UNRECOVERABLE = (asyncio.CancelledError, KeyboardInterrupt, SystemExit)


def _default_retry(attempts: int, metrics: MetricsHook) -> AsyncRetrying:
    """Build the ``tenacity`` policy used when no ``retry=`` override is supplied.

    Preserves this project's original default (no retry unless configured, i.e.
    ``attempts=1``) and non-retryable classification (``semantic_classifier`` never
    retries cancellation/process-control exceptions or semantically non-retryable
    categories such as auth/authorization/invalid-request/capability-not-found/protocol
    failures), while emitting the same ``retry`` metrics event this project has always
    emitted before each backoff sleep.
    """

    async def _before_sleep(retry_state: RetryCallState) -> None:
        delay = retry_state.next_action.sleep if retry_state.next_action else 0.0
        await emit(
            metrics,
            "retry",
            attributes={"attempt": retry_state.attempt_number, "delay": delay},
        )

    return AsyncRetrying(
        stop=stop_after_attempt(max(1, attempts)),
        retry=retry_if_exception(semantic_classifier),
        before_sleep=_before_sleep,
        reraise=True,
    )


# Worst-first ordering used to aggregate the per-operation health of a server into
# the single HealthState returned by MCPRuntime.health().
_SEVERITY = (
    HealthState.UNHEALTHY,
    HealthState.DEGRADED,
    HealthState.RECOVERING,
    HealthState.HEALTHY,
)


class OperationPipeline:
    """Runtime-scoped resilience pipeline shared by every MCP operation.

    One instance is owned exclusively by a single ``MCPRuntime``; nothing here is
    process-global or shared across runtimes. Every call to :meth:`run` composes, in
    order, bulkhead admission, the interceptor chain, a circuit breaker, an optional
    shared rate limiter (``aiolimiter.AsyncLimiter``), retry (``tenacity.AsyncRetrying``),
    and an optional timeout -- then records metrics and updates health -- for whichever
    operation (``connect``, ``discover``, ``call_tool``, ``read_resource``,
    ``get_prompt``) is running.

    Circuit breakers and health trackers are keyed by ``(server_id, operation)``
    rather than by ``server_id`` alone: a cached, always-succeeding ``connect`` must
    never reset the failure count accumulated by a failing ``call_tool`` against the
    same server, so each operation kind gets its own independent failure history.
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 16,
        operation_timeout: float | None = None,
        retry: AsyncRetrying | None = None,
        rate_limiter: AsyncLimiter | None = None,
        interceptors: Iterable[Interceptor[Any]] = (),
        metrics: MetricsHook | None = None,
    ) -> None:
        """Configure the pipeline.

        ``retry``/``rate_limiter`` expose ``tenacity``/``aiolimiter``'s own public
        configuration objects directly: pass a real ``tenacity.AsyncRetrying(...)`` or
        ``aiolimiter.AsyncLimiter(...)`` built from those libraries' own primitives
        (``stop_after_attempt``, ``wait_exponential``, ``retry_if_exception``, etc.) for
        full control. When ``retry`` is omitted, no retry is attempted (a single try);
        when ``rate_limiter`` is omitted, no rate limiting is applied.
        """
        self._bulkhead = AsyncBulkhead(max_concurrency)
        self._operation_timeout = operation_timeout
        self._metrics: MetricsHook = metrics or NullMetrics()
        self._retry = retry or _default_retry(1, self._metrics)
        self._rate_limiter = rate_limiter
        self._interceptors = InterceptorChain(tuple(interceptors))
        self._breakers: dict[_Key, CircuitBreaker] = {}
        self._health: dict[_Key, HealthTracker] = {}

    async def run(
        self,
        server_id: str,
        operation: str,
        action: Action[T],
        *,
        fallback: Callable[[BaseException], Awaitable[T]] | None = None,
    ) -> T:
        """Run ``action`` for ``server_id``/``operation`` through the full pipeline.

        If ``fallback`` is supplied and the pipeline exhausts retries/breaker without
        succeeding, ``fallback(error)`` is invoked instead of propagating the failure
        (e.g. serving a cached value or a degraded default).
        """
        key = (server_id, operation)
        breaker = self._breakers.setdefault(
            key, CircuitBreaker(classifier=semantic_classifier, metrics=self._metrics)
        )
        tracker = self._health.setdefault(key, HealthTracker())
        attributes = {"server_id": server_id, "operation": operation}

        async def timed() -> T:
            if self._operation_timeout is None:
                return await action()
            return await with_timeout(
                action(),
                self._operation_timeout,
                message=f"{operation} timed out for {server_id}",
            )

        async def with_retry() -> T:
            retrying = self._retry.copy()
            try:
                result = await retrying(timed)
            except BaseException as error:
                if not isinstance(error, _UNRECOVERABLE):
                    await emit(
                        self._metrics,
                        "retry.failure",
                        attributes={"attempt": retrying.statistics.get("attempt_number", 1)},
                    )
                raise
            if retrying.statistics.get("attempt_number", 1) > 1:
                await emit(
                    self._metrics,
                    "retry.success",
                    attributes={"attempt": retrying.statistics["attempt_number"]},
                )
            return result

        async def with_rate_limit() -> T:
            if self._rate_limiter is None:
                return await with_retry()
            await self._rate_limiter.acquire()
            return await with_retry()

        async def with_breaker() -> T:
            return await breaker.call(with_rate_limit)

        async def with_bulkhead() -> T:
            return await self._bulkhead.run(with_breaker)

        async def with_fallback_applied() -> T:
            if fallback is None:
                return await self._interceptors.run(with_bulkhead)
            return await with_fallback(
                lambda: self._interceptors.run(with_bulkhead), fallback, metrics=self._metrics
            )

        await self._metrics.record("operation.start", attributes=attributes)
        try:
            result = await with_fallback_applied()
        except BaseException as error:
            if not isinstance(error, _UNRECOVERABLE):
                tracker.record_failure()
                await self._metrics.record(
                    "operation.failure",
                    attributes={**attributes, "error": type(error).__name__},
                )
            raise
        tracker.record_success()
        await self._metrics.record("operation.success", attributes=attributes)
        return result

    async def health(self, server_id: str) -> HealthState:
        """Aggregate the worst per-operation health tracked for ``server_id``."""
        states = {
            tracker.state for (sid, _operation), tracker in self._health.items() if sid == server_id
        }
        if not states:
            return HealthState.HEALTHY
        for state in _SEVERITY:
            if state in states:
                return state
        return HealthState.HEALTHY

    def reset(self, server_id: str) -> None:
        """Drop per-server circuit breaker and health state, e.g. on unregister."""
        for key in [k for k in self._breakers if k[0] == server_id]:
            del self._breakers[key]
        for key in [k for k in self._health if k[0] == server_id]:
            del self._health[key]
