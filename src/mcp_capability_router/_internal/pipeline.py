"""The resilience pipeline that every server operation runs through."""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from aiolimiter import AsyncLimiter
from purgatory import AsyncCircuitBreakerFactory
from purgatory.domain.model import CLOSED, HALF_OPENED, OPENED, OpenedState
from refresh_engine import MetricsSink
from tenacity import AsyncRetrying

from ..contracts import Interceptor, Operation, OperationContext
from ..errors import CircuitOpenError, ConfigurationError
from ..models import HealthState
from ..resilience import is_retryable
from . import metrics

if TYPE_CHECKING:
    from purgatory.domain.model import Context

logger = logging.getLogger("mcp_capability_router")

_SEVERITY = (
    HealthState.HEALTHY,
    HealthState.DEGRADED,
    HealthState.RECOVERING,
    HealthState.UNHEALTHY,
)
_STATE_NAMES: dict[str, str] = {
    CLOSED: "closed",
    OPENED: "open",
    HALF_OPENED: "half_open",
}


def _not_a_server_failure(error: BaseException) -> bool:
    """Whether `error` leaves the circuit untouched as a failure."""
    return not is_retryable(error)


_EXCLUDE: list[Any] = [(BaseException, _not_a_server_failure)]
"""Exclusions passed after those of the factory, which purgatory checks first."""


def _health(context: Context) -> HealthState:
    if context.state == OPENED:
        reopens_at = (context.opened_at or 0.0) + context.ttl
        if time.time() >= reopens_at:
            return HealthState.RECOVERING
        return HealthState.UNHEALTHY
    if context.state == HALF_OPENED:
        return HealthState.RECOVERING
    return HealthState.DEGRADED if context.failure_count else HealthState.HEALTHY


class OperationPipeline:
    """Runs server operations through every resilience stage.

    The stages wrap each other in this order, outermost first: the semaphore of
    `max_concurrency`, the interceptors, the circuit breaker of the server and
    operation, the retry policy, and, for every attempt, the rate limiter and the
    timeout. Every operation also records metrics.
    """

    def __init__(
        self,
        *,
        max_concurrency: int,
        operation_timeout: float | None,
        retry: AsyncRetrying | None,
        rate_limiter: AsyncLimiter | None,
        circuit_breaker: AsyncCircuitBreakerFactory | None,
        interceptors: Sequence[Interceptor],
        metrics_sink: MetricsSink | None,
    ) -> None:
        """Validate and store the configuration."""
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            msg = f"max_concurrency must be a positive integer, got {max_concurrency!r}"
            raise ConfigurationError(msg)
        if operation_timeout is not None and not operation_timeout > 0:
            msg = f"operation_timeout must be positive, got {operation_timeout!r}"
            raise ConfigurationError(msg)
        if retry is not None and not isinstance(retry, AsyncRetrying):
            msg = f"retry must be a tenacity.AsyncRetrying, got {type(retry).__name__}"
            raise ConfigurationError(msg)
        if rate_limiter is not None and not isinstance(rate_limiter, AsyncLimiter):
            msg = (
                "rate_limiter must be an aiolimiter.AsyncLimiter, got "
                f"{type(rate_limiter).__name__}"
            )
            raise ConfigurationError(msg)
        if circuit_breaker is not None and not isinstance(
            circuit_breaker, AsyncCircuitBreakerFactory
        ):
            msg = (
                "circuit_breaker must be a purgatory.AsyncCircuitBreakerFactory, got "
                f"{type(circuit_breaker).__name__}"
            )
            raise ConfigurationError(msg)
        interceptors = tuple(interceptors)
        for interceptor in interceptors:
            if not isinstance(interceptor, Interceptor):
                msg = f"interceptor {interceptor!r} is not callable"
                raise ConfigurationError(msg)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = operation_timeout
        self._retry = retry.copy(reraise=True) if retry is not None else None
        self._rate_limiter = rate_limiter
        self._shared_breakers = circuit_breaker
        self._breakers: dict[str, AsyncCircuitBreakerFactory] = {}
        self._operations: dict[str, set[Operation]] = {}
        self._interceptors: tuple[Interceptor, ...] = interceptors
        self._metrics = metrics_sink
        self._closed = False
        if circuit_breaker is not None:
            circuit_breaker.add_listener(self._on_circuit_event)

    def add_server(self, server_id: str) -> None:
        """Start tracking the circuits and health of a server."""
        if self._shared_breakers is None:
            factory = AsyncCircuitBreakerFactory()
            factory.add_listener(self._on_circuit_event)
            self._breakers[server_id] = factory
        self._operations[server_id] = set()

    def remove_server(self, server_id: str) -> None:
        """Forget the circuits and health of a server."""
        self._breakers.pop(server_id, None)
        self._operations.pop(server_id, None)

    def close(self) -> None:
        """Detach from a shared circuit breaker factory and forget every server."""
        if self._closed:
            return
        self._closed = True
        if self._shared_breakers is not None:
            self._shared_breakers.remove_listener(self._on_circuit_event)
        self._breakers.clear()
        self._operations.clear()

    async def run[T](
        self, context: OperationContext, action: Callable[[], Awaitable[T]]
    ) -> T:
        """Run `action` for `context` through every stage of the pipeline."""
        started = time.perf_counter()
        outcome = "failure"
        try:
            async with self._semaphore:
                result = await self._intercept(context, action)
        except CircuitOpenError:
            outcome = "rejected"
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        else:
            outcome = "success"
            return result
        finally:
            attributes = {
                "server_id": context.server_id,
                "operation": str(context.operation),
                "outcome": outcome,
            }
            metrics.increment(self._metrics, metrics.OPERATIONS, 1, attributes)
            metrics.observe(
                self._metrics,
                metrics.OPERATION_DURATION,
                time.perf_counter() - started,
                attributes,
            )

    async def health(self, server_id: str) -> HealthState:
        """Return the worst health among the circuits of a server."""
        worst = HealthState.HEALTHY
        for operation in sorted(self._operations.get(server_id, ())):
            breaker = await self._breaker(server_id, operation)
            state = _health(breaker.context)
            if _SEVERITY.index(state) > _SEVERITY.index(worst):
                worst = state
        return worst

    async def _intercept[T](
        self, context: OperationContext, action: Callable[[], Awaitable[T]]
    ) -> T:
        call: Callable[[], Awaitable[Any]] = functools.partial(
            self._guard, context, action
        )
        for interceptor in reversed(self._interceptors):
            call = functools.partial(interceptor, context, call)
        return await call()

    async def _guard[T](
        self, context: OperationContext, action: Callable[[], Awaitable[T]]
    ) -> T:
        operations = self._operations.get(context.server_id)
        if operations is not None:
            operations.add(context.operation)
        breaker = await self._breaker(context.server_id, context.operation)
        try:
            async with breaker:
                return await self._attempts(context, action)
        except OpenedState as error:
            msg = (
                f"the circuit of {context.operation} on server "
                f"{context.server_id!r} is open"
            )
            raise CircuitOpenError(msg) from error

    async def _breaker(self, server_id: str, operation: Operation):
        factory = self._shared_breakers
        if factory is None:
            factory = self._breakers.get(server_id)
        if factory is None:
            # The server was removed while the operation was in flight.
            factory = AsyncCircuitBreakerFactory()
        breaker = await factory.get_breaker(f"{server_id}:{operation}")
        # purgatory stops at the first matching exclusion; the factory's own
        # exclusions take precedence over the router's classification.
        breaker.context.exclude_list = [*factory.global_exclude, *_EXCLUDE]
        return breaker

    async def _attempts[T](
        self, context: OperationContext, action: Callable[[], Awaitable[T]]
    ) -> T:
        if self._retry is None:
            return await self._attempt(context, action)
        retrying = self._retry.copy()
        try:
            return await retrying(self._attempt, context, action)
        finally:
            retries = int(retrying.statistics.get("attempt_number", 1)) - 1
            if retries > 0:
                metrics.increment(
                    self._metrics,
                    metrics.RETRIES,
                    retries,
                    {
                        "server_id": context.server_id,
                        "operation": str(context.operation),
                    },
                )

    async def _attempt[T](
        self, context: OperationContext, action: Callable[[], Awaitable[T]]
    ) -> T:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()
        if self._timeout is None:
            return await action()
        deadline = asyncio.timeout(self._timeout)
        try:
            async with deadline:
                return await action()
        except TimeoutError as error:
            if deadline.expired():
                error.add_note(
                    f"{context.operation} on server {context.server_id!r} exceeded "
                    f"the operation timeout of {self._timeout}s"
                )
            raise

    def _on_circuit_event(self, name: str, kind: str, event: object) -> None:
        if kind != "state_changed":
            return
        server_id, _, operation = name.partition(":")
        raw_state = str(getattr(event, "state", ""))
        state = _STATE_NAMES.get(raw_state, raw_state)
        if state == "open":
            logger.warning("Circuit opened for %s on server %r", operation, server_id)
        else:
            logger.info("Circuit %s for %s on server %r", state, operation, server_id)
        metrics.increment(
            self._metrics,
            metrics.CIRCUIT_TRANSITIONS,
            1,
            {"server_id": server_id, "operation": operation, "state": state},
        )
