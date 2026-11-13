"""The resilience pipeline that every server operation runs through."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastmcp.telemetry import suppress_fastmcp_telemetry
from purgatory import AsyncCircuitBreakerFactory
from purgatory.domain.model import CLOSED, HALF_OPENED, OPENED, OpenedState

from ..contracts import Interceptor, InterceptorLike, Operation, OperationContext
from ..errors import CircuitOpenError, ConfigurationError
from ..models import HealthState, Tool
from ..otel import OpenTelemetryInterceptor
from ..resilience import ResiliencePolicy, is_retryable
from . import metrics

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from opentelemetry.trace import TracerProvider
    from purgatory.domain.model import Context
    from refresh_engine import MetricsSink
    from tenacity import AsyncRetrying

    from ..otel import TracingMode

logger = logging.getLogger("mcp_capability_router")

_TRACING_MODES = ("router", "fastmcp", "all", "off")

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


def _may_retry(policy: ResiliencePolicy, context: OperationContext) -> bool:
    """Whether the operation may be attempted more than once."""
    if context.operation is not Operation.CALL_TOOL or policy.retry_unsafe_tools:
        return True
    return isinstance(context.capability, Tool) and context.capability.idempotent


@dataclass(slots=True)
class _ServerState:
    """The resilience state of one server, derived from its policy."""

    policy: ResiliencePolicy
    breakers: AsyncCircuitBreakerFactory
    retry: AsyncRetrying | None
    semaphore: asyncio.Semaphore | None
    operations: set[Operation] = field(default_factory=set)

    @classmethod
    def create(cls, policy: ResiliencePolicy) -> _ServerState:
        return cls(
            policy=policy,
            breakers=(
                policy.circuit_breaker
                if policy.circuit_breaker is not None
                else AsyncCircuitBreakerFactory()
            ),
            retry=policy.retry.copy(reraise=True) if policy.retry is not None else None,
            semaphore=(
                asyncio.Semaphore(policy.max_concurrency)
                if policy.max_concurrency is not None
                else None
            ),
        )


class OperationPipeline:
    """Runs server operations through every resilience stage.

    The stages wrap each other in this order, outermost first: the concurrency
    limit of the server, the runtime-wide concurrency limit, the interceptors
    (led by the tracing interceptor of the tracing mode), the circuit breaker of
    the server and operation, the retry policy, and, for every attempt, the rate
    limiter and the timeout. Every operation also records metrics.
    """

    def __init__(
        self,
        *,
        max_concurrency: int,
        policy: ResiliencePolicy,
        interceptors: Iterable[InterceptorLike],
        metrics_sink: MetricsSink | None,
        tracing: TracingMode = "router",
        tracer_provider: TracerProvider | None = None,
        capture_tool_content: bool = True,
    ) -> None:
        """Validate and store the configuration."""
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            msg = f"max_concurrency must be a positive integer, got {max_concurrency!r}"
            raise ConfigurationError(msg)
        if not isinstance(policy, ResiliencePolicy):
            msg = f"resilience must be a ResiliencePolicy, got {type(policy).__name__}"
            raise ConfigurationError(msg)
        chain = tuple(interceptors)
        for interceptor in chain:
            if not isinstance(interceptor, Interceptor) and not inspect.iscoroutinefunction(
                interceptor
            ):
                msg = f"interceptor {interceptor!r} is neither an Interceptor nor an async function"
                raise ConfigurationError(msg)
        if tracing not in _TRACING_MODES:
            msg = f"tracing must be one of {', '.join(map(repr, _TRACING_MODES))}, got {tracing!r}"
            raise ConfigurationError(msg)
        # Created in every mode so that `tracer_provider` is always validated.
        router_spans = OpenTelemetryInterceptor(
            tracer_provider=tracer_provider, capture_tool_content=capture_tool_content
        )
        if tracing in ("router", "all") and not any(
            isinstance(interceptor, OpenTelemetryInterceptor) for interceptor in chain
        ):
            chain = (router_spans, *chain)
        self._suppress_fastmcp = tracing in ("router", "off")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._policy = policy
        self._interceptors: tuple[InterceptorLike, ...] = chain
        self._metrics = metrics_sink
        self._servers: dict[str, _ServerState] = {}
        self._listeners: dict[AsyncCircuitBreakerFactory, int] = {}
        self._initialized: set[AsyncCircuitBreakerFactory] = set()
        self._initializing = asyncio.Lock()
        self._pending: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def policy(self) -> ResiliencePolicy:
        """The policy of servers registered without their own."""
        return self._policy

    def add_server(self, server_id: str, policy: ResiliencePolicy | None) -> None:
        """Start tracking the circuits and health of a server.

        Raises:
            ConfigurationError: If `policy` is not a `ResiliencePolicy`.
        """
        if policy is not None and not isinstance(policy, ResiliencePolicy):
            msg = f"resilience must be a ResiliencePolicy, got {type(policy).__name__}"
            raise ConfigurationError(msg)
        state = _ServerState.create(policy if policy is not None else self._policy)
        count = self._listeners.get(state.breakers, 0)
        if not count:
            state.breakers.add_listener(self._on_circuit_event)
        self._listeners[state.breakers] = count + 1
        self._servers[server_id] = state

    def remove_server(self, server_id: str) -> None:
        """Forget the circuits and health of a server."""
        state = self._servers.pop(server_id, None)
        if state is None:
            return
        count = self._listeners[state.breakers] - 1
        if count:
            self._listeners[state.breakers] = count
        else:
            del self._listeners[state.breakers]
            self._initialized.discard(state.breakers)
            state.breakers.remove_listener(self._on_circuit_event)

    async def aclose(self) -> None:
        """Detach from every circuit breaker factory and flush pending metrics."""
        if self._closed:
            return
        self._closed = True
        for server_id in list(self._servers):
            self.remove_server(server_id)
        while self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)

    async def run[T](self, context: OperationContext, action: Callable[[], Awaitable[T]]) -> T:
        """Run `action` for `context` through every stage of the pipeline."""
        state = self._servers.get(context.server_id)
        if state is None:
            # The server was removed while the operation was queued.
            state = _ServerState.create(self._policy)
        started = time.perf_counter()
        outcome = "failure"
        try:
            limit = state.semaphore if state.semaphore is not None else contextlib.nullcontext()
            # FastMCP's own spans, in-process servers included, would repeat the
            # router's span; the trace context still reaches the server.
            scope = (
                suppress_fastmcp_telemetry() if self._suppress_fastmcp else contextlib.nullcontext()
            )
            with scope:
                async with limit, self._semaphore:
                    result = await self._intercept(state, context, action)
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
            await metrics.increment(self._metrics, metrics.OPERATIONS, 1, attributes)
            await metrics.observe(
                self._metrics,
                metrics.OPERATION_DURATION,
                time.perf_counter() - started,
                attributes,
            )

    async def health(self, server_id: str) -> HealthState:
        """Return the worst health among the circuits of a server."""
        state = self._servers.get(server_id)
        if state is None:
            return HealthState.HEALTHY
        worst = HealthState.HEALTHY
        for operation in sorted(state.operations):
            breaker = await self._breaker(state, server_id, operation)
            health = _health(breaker.context)
            if _SEVERITY.index(health) > _SEVERITY.index(worst):
                worst = health
        return worst

    async def _intercept[T](
        self,
        state: _ServerState,
        context: OperationContext,
        action: Callable[[], Awaitable[T]],
    ) -> T:
        call: Callable[[], Awaitable[Any]] = functools.partial(self._guard, state, context, action)
        for interceptor in reversed(self._interceptors):
            call = functools.partial(interceptor, context, call)
        return await call()

    async def _guard[T](
        self,
        state: _ServerState,
        context: OperationContext,
        action: Callable[[], Awaitable[T]],
    ) -> T:
        state.operations.add(context.operation)
        breaker = await self._breaker(state, context.server_id, context.operation)
        try:
            async with breaker:
                return await self._attempts(state, context, action)
        except OpenedState as error:
            msg = f"the circuit of {context.operation} on server {context.server_id!r} is open"
            raise CircuitOpenError(msg) from error

    async def _breaker(self, state: _ServerState, server_id: str, operation: Operation):
        factory = state.breakers
        if factory not in self._initialized:
            async with self._initializing:
                if factory not in self._initialized:
                    # Connects a shared store, such as purgatory's Redis unit of work.
                    await factory.initialize()
                    self._initialized.add(factory)
        breaker = await factory.get_breaker(f"{server_id}:{operation}")
        # purgatory stops at the first matching exclusion; the factory's own
        # exclusions take precedence over the router's classification.
        breaker.context.exclude_list = [*factory.global_exclude, *_EXCLUDE]
        return breaker

    async def _attempts[T](
        self,
        state: _ServerState,
        context: OperationContext,
        action: Callable[[], Awaitable[T]],
    ) -> T:
        if state.retry is None or not _may_retry(state.policy, context):
            return await self._attempt(state.policy, context, action)
        retrying = state.retry.copy()
        try:
            return await retrying(self._attempt, state.policy, context, action)
        finally:
            retries = int(retrying.statistics.get("attempt_number", 1)) - 1
            if retries > 0:
                await metrics.increment(
                    self._metrics,
                    metrics.RETRIES,
                    retries,
                    {"server_id": context.server_id, "operation": str(context.operation)},
                )

    async def _attempt[T](
        self,
        policy: ResiliencePolicy,
        context: OperationContext,
        action: Callable[[], Awaitable[T]],
    ) -> T:
        if policy.rate_limiter is not None:
            await policy.rate_limiter.acquire()
        if policy.operation_timeout is None:
            return await action()
        deadline = asyncio.timeout(policy.operation_timeout)
        try:
            async with deadline:
                return await action()
        except TimeoutError as error:
            if deadline.expired():
                error.add_note(
                    f"{context.operation} on server {context.server_id!r} exceeded "
                    f"the operation timeout of {policy.operation_timeout}s"
                )
            raise

    def _on_circuit_event(self, name: str, kind: str, event: object) -> None:
        if kind != "state_changed":
            return
        server_id, _, operation = name.partition(":")
        if server_id not in self._servers:
            return
        raw_state = str(getattr(event, "state", ""))
        state = _STATE_NAMES.get(raw_state, raw_state)
        if state == "open":
            logger.warning("Circuit opened for %s on server %r", operation, server_id)
        else:
            logger.info("Circuit %s for %s on server %r", state, operation, server_id)
        if self._metrics is None:
            return
        # purgatory calls listeners synchronously; the sink is awaited in a task that
        # `aclose` waits for.
        task = asyncio.get_running_loop().create_task(
            metrics.increment(
                self._metrics,
                metrics.CIRCUIT_TRANSITIONS,
                1,
                {"server_id": server_id, "operation": operation, "state": state},
            )
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
