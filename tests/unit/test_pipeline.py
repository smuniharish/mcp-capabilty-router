from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from aiolimiter import AsyncLimiter
from purgatory import AsyncCircuitBreakerFactory
from refresh_engine import InMemoryMetrics
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from mcp_capability_router import (
    CallNext,
    CircuitOpenError,
    ConfigurationError,
    HealthState,
    Interceptor,
    Operation,
    OperationContext,
    RateLimitError,
    ResiliencePolicy,
    ServerConnectionError,
    ToolExecutionError,
    is_retryable,
)
from mcp_capability_router._internal.pipeline import OperationPipeline
from tests.support import tool

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_PIPELINE_OPTIONS = {"max_concurrency", "interceptors", "metrics_sink"}


def make_pipeline(**overrides: Any) -> OperationPipeline:
    """Build a pipeline with server `s`; other keywords configure its policy."""
    options: dict[str, Any] = {"max_concurrency": 4, "interceptors": (), "metrics_sink": None}
    options.update({key: value for key, value in overrides.items() if key in _PIPELINE_OPTIONS})
    policy = ResiliencePolicy(
        **{key: value for key, value in overrides.items() if key not in _PIPELINE_OPTIONS}
    )
    pipeline = OperationPipeline(policy=policy, **options)
    pipeline.add_server("s", None)
    return pipeline


def context(
    operation: Operation = Operation.CALL_TOOL, *, idempotent: bool = True
) -> OperationContext:
    """Return a context for server `s`; tool calls target an idempotent tool by default."""
    capability = None
    if operation is Operation.CALL_TOOL:
        hints = {"idempotent_hint": idempotent, "destructive_hint": False}
        capability = tool("s", "t", metadata={"annotations": hints})
    return OperationContext(server_id="s", operation=operation, capability=capability)


def raising(error: BaseException) -> Callable[[], Awaitable[None]]:
    async def action() -> None:
        raise error

    return action


async def ok() -> str:
    return "ok"


def retrying(attempts: int = 3, *, reraise: bool = True) -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        retry=retry_if_exception(is_retryable),
        reraise=reraise,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_concurrency": 0}, "max_concurrency"),
        ({"max_concurrency": True}, "max_concurrency"),
        ({"interceptors": [42]}, "neither an Interceptor nor an async function"),
        ({"interceptors": [lambda context, call_next: None]}, "async function"),
    ],
)
def test_invalid_configuration_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        make_pipeline(**overrides)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"operation_timeout": 0}, "operation_timeout"),
        ({"operation_timeout": True}, "operation_timeout"),
        ({"operation_timeout": float("inf")}, "operation_timeout"),
        ({"retry": object()}, "tenacity.AsyncRetrying"),
        ({"retry_unsafe_tools": 1}, "retry_unsafe_tools"),
        ({"rate_limiter": object()}, "aiolimiter.AsyncLimiter"),
        ({"circuit_breaker": object()}, "purgatory.AsyncCircuitBreakerFactory"),
        ({"max_concurrency": 0}, "max_concurrency"),
        ({"max_concurrency": True}, "max_concurrency"),
    ],
)
def test_invalid_policies_are_rejected(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        ResiliencePolicy(**options)


def test_policies_must_be_resilience_policies() -> None:
    with pytest.raises(ConfigurationError, match="ResiliencePolicy"):
        OperationPipeline(
            max_concurrency=1,
            policy=object(),  # type: ignore[arg-type]
            interceptors=(),
            metrics_sink=None,
        )
    pipeline = make_pipeline()
    with pytest.raises(ConfigurationError, match="ResiliencePolicy"):
        pipeline.add_server("t", object())  # type: ignore[arg-type]


async def test_records_success_and_failure_metrics() -> None:
    metrics = InMemoryMetrics()
    pipeline = make_pipeline(metrics_sink=metrics)
    assert await pipeline.run(context(), ok) == "ok"
    with pytest.raises(ValueError, match="boom"):
        await pipeline.run(context(), raising(ValueError("boom")))
    counters, observations = metrics.snapshot()
    base = "mcp_capability_router.operations{operation=call_tool,outcome="
    assert counters[f"{base}success,server_id=s}}"] == 1
    assert counters[f"{base}failure,server_id=s}}"] == 1
    assert len(observations) == 2


async def test_circuit_opens_after_repeated_server_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    metrics = InMemoryMetrics()
    pipeline = make_pipeline(metrics_sink=metrics)
    with caplog.at_level(logging.WARNING, logger="mcp_capability_router"):
        for _ in range(5):
            with pytest.raises(ServerConnectionError):
                await pipeline.run(context(), raising(ServerConnectionError("down")))
    with pytest.raises(CircuitOpenError, match="call_tool on server 's' is open"):
        await pipeline.run(context(), ok)
    assert await pipeline.health("s") is HealthState.UNHEALTHY
    await pipeline.aclose()
    counters, _ = metrics.snapshot()
    assert (
        counters[
            "mcp_capability_router.circuit.transitions{operation=call_tool,server_id=s,state=open}"
        ]
        == 1
    )
    assert (
        counters[
            "mcp_capability_router.operations{operation=call_tool,outcome=rejected,server_id=s}"
        ]
        == 1
    )
    assert "Circuit opened for call_tool on server 's'" in caplog.text


async def test_circuits_are_separate_per_operation() -> None:
    pipeline = make_pipeline()
    for _ in range(5):
        with pytest.raises(ServerConnectionError):
            await pipeline.run(context(), raising(ServerConnectionError("down")))
    assert await pipeline.run(context(Operation.READ_RESOURCE), ok) == "ok"


async def test_non_retryable_failures_leave_the_circuit_closed() -> None:
    pipeline = make_pipeline()
    with pytest.raises(ServerConnectionError):
        await pipeline.run(context(), raising(ServerConnectionError("down")))
    assert await pipeline.health("s") is HealthState.DEGRADED
    for _ in range(10):
        with pytest.raises(ToolExecutionError):
            await pipeline.run(context(), raising(ToolExecutionError("bad input")))
    assert await pipeline.health("s") is HealthState.HEALTHY


async def test_exclusions_of_a_shared_factory_take_precedence() -> None:
    breakers = AsyncCircuitBreakerFactory(default_threshold=2, exclude=[RateLimitError])
    pipeline = make_pipeline(circuit_breaker=breakers)
    for _ in range(4):
        with pytest.raises(RateLimitError):
            await pipeline.run(context(), raising(RateLimitError("slow down")))
    assert await pipeline.health("s") is HealthState.HEALTHY
    for _ in range(2):
        with pytest.raises(ServerConnectionError):
            await pipeline.run(context(), raising(ServerConnectionError("down")))
    with pytest.raises(CircuitOpenError):
        await pipeline.run(context(), ok)


async def test_health_reports_recovery_after_the_open_period() -> None:
    breakers = AsyncCircuitBreakerFactory(default_threshold=1, default_ttl=0.05)
    pipeline = make_pipeline(circuit_breaker=breakers)
    assert await pipeline.health("s") is HealthState.HEALTHY
    with pytest.raises(ServerConnectionError):
        await pipeline.run(context(), raising(ServerConnectionError("down")))
    assert await pipeline.health("s") is HealthState.UNHEALTHY
    await asyncio.sleep(0.06)
    assert await pipeline.health("s") is HealthState.RECOVERING

    trial_started = asyncio.Event()
    release = asyncio.Event()

    async def trial() -> str:
        trial_started.set()
        await release.wait()
        return "ok"

    running = asyncio.create_task(pipeline.run(context(), trial))
    await trial_started.wait()
    assert await pipeline.health("s") is HealthState.RECOVERING
    release.set()
    assert await running == "ok"
    assert await pipeline.health("s") is HealthState.HEALTHY


async def test_interceptors_run_in_order_with_the_context() -> None:
    seen: list[str] = []

    def interceptor(label: str) -> Any:
        async def intercept(ctx: OperationContext, call_next: Callable[[], Awaitable[Any]]) -> Any:
            seen.append(f"{label}:{ctx.operation}")
            result = await call_next()
            seen.append(f"{label}:done")
            return result

        return intercept

    class ShortCircuit(Interceptor):
        async def __call__(self, ctx: OperationContext, call_next: CallNext, /) -> Any:
            return "cached"

    pipeline = make_pipeline(interceptors=[interceptor("outer"), interceptor("inner")])
    assert await pipeline.run(context(), ok) == "ok"
    assert seen == ["outer:call_tool", "inner:call_tool", "inner:done", "outer:done"]
    cached = make_pipeline(interceptors=[ShortCircuit()])
    assert await cached.run(context(), raising(ValueError("never"))) == "cached"


async def test_retries_are_counted_and_errors_are_always_re_raised() -> None:
    metrics = InMemoryMetrics()
    attempts = {"count": 0}

    async def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ServerConnectionError("transient")
        return "ok"

    pipeline = make_pipeline(retry=retrying(3, reraise=False), metrics_sink=metrics)
    assert await pipeline.run(context(), flaky) == "ok"
    counters, _ = metrics.snapshot()
    assert counters["mcp_capability_router.retries{operation=call_tool,server_id=s}"] == 2

    with pytest.raises(ServerConnectionError):
        await pipeline.run(context(), raising(ServerConnectionError("down")))

    calls = {"count": 0}

    async def rejected() -> None:
        calls["count"] += 1
        raise ToolExecutionError("bad input")

    with pytest.raises(ToolExecutionError):
        await pipeline.run(context(), rejected)
    assert calls["count"] == 1


async def test_rate_limit_applies_to_every_attempt() -> None:
    acquired: list[float] = []

    class CountingLimiter(AsyncLimiter):
        async def acquire(self, amount: float = 1) -> None:
            acquired.append(amount)
            await super().acquire(amount)

    pipeline = make_pipeline(retry=retrying(3), rate_limiter=CountingLimiter(1000, time_period=1))
    with pytest.raises(ServerConnectionError):
        await pipeline.run(context(), raising(ServerConnectionError("down")))
    assert acquired == [1, 1, 1]


async def test_timeouts_apply_per_attempt_and_explain_themselves() -> None:
    pipeline = make_pipeline(operation_timeout=0.01)

    async def slow() -> None:
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError) as raised:
        await pipeline.run(context(), slow)
    assert "exceeded the operation timeout" in "".join(raised.value.__notes__)

    with pytest.raises(TimeoutError) as own:
        await pipeline.run(context(), raising(TimeoutError("server said so")))
    assert not getattr(own.value, "__notes__", [])
    assert await pipeline.run(context(), ok) == "ok"


async def test_cancellation_is_recorded_and_propagated() -> None:
    metrics = InMemoryMetrics()
    pipeline = make_pipeline(metrics_sink=metrics)
    started = asyncio.Event()

    async def wait_forever() -> None:
        started.set()
        await asyncio.sleep(10)

    task = asyncio.create_task(pipeline.run(context(), wait_forever))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    counters, _ = metrics.snapshot()
    assert (
        counters[
            "mcp_capability_router.operations{operation=call_tool,outcome=cancelled,server_id=s}"
        ]
        == 1
    )


async def test_concurrency_is_bounded() -> None:
    pipeline = make_pipeline(max_concurrency=2)
    active = peak = 0

    async def tracked() -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    await asyncio.gather(*(pipeline.run(context(), tracked) for _ in range(6)))
    assert peak == 2


async def test_shared_breakers_detach_on_close_and_removed_servers_still_run() -> None:
    breakers = AsyncCircuitBreakerFactory()
    pipeline = make_pipeline(circuit_breaker=breakers)
    pipeline.add_server("t", None)
    assert len(breakers.listeners) == 1
    pipeline.remove_server("t")
    assert len(breakers.listeners) == 1
    pipeline.remove_server("missing")
    await pipeline.aclose()
    await pipeline.aclose()
    assert breakers.listeners == {}

    private = make_pipeline()
    private.remove_server("s")
    assert await private.run(context(), ok) == "ok"
    assert await private.health("s") is HealthState.HEALTHY


async def test_breaker_factories_are_initialized_once_while_in_use() -> None:
    class CountingFactory(AsyncCircuitBreakerFactory):
        initialized = 0

        async def initialize(self) -> None:
            await asyncio.sleep(0.01)
            self.initialized += 1

    breakers = CountingFactory()
    pipeline = make_pipeline(circuit_breaker=breakers)
    await asyncio.gather(*(pipeline.run(context(), ok) for _ in range(3)))
    await pipeline.run(context(Operation.DISCOVER), ok)
    assert breakers.initialized == 1

    pipeline.remove_server("s")
    pipeline.add_server("s", None)
    await pipeline.run(context(), ok)
    assert breakers.initialized == 2
    await pipeline.aclose()


async def test_unknown_circuit_states_are_reported_verbatim() -> None:
    metrics = InMemoryMetrics()
    pipeline = make_pipeline(metrics_sink=metrics)
    pipeline._on_circuit_event("s:call_tool", "failed", SimpleNamespace())
    pipeline._on_circuit_event("s:call_tool", "state_changed", SimpleNamespace(state="odd"))
    pipeline._on_circuit_event("other:call_tool", "state_changed", SimpleNamespace(state="odd"))
    await pipeline.aclose()
    counters, _ = metrics.snapshot()
    assert counters == {
        "mcp_capability_router.circuit.transitions{operation=call_tool,server_id=s,state=odd}": 1
    }


async def test_unsafe_tool_calls_are_attempted_once_unless_allowed() -> None:
    attempts = {"count": 0}

    async def flaky() -> str:
        attempts["count"] += 1
        raise ServerConnectionError("transient")

    pipeline = make_pipeline(retry=retrying(3))
    with pytest.raises(ServerConnectionError):
        await pipeline.run(context(idempotent=False), flaky)
    assert attempts["count"] == 1
    with pytest.raises(ServerConnectionError):
        await pipeline.run(context(Operation.READ_RESOURCE), flaky)
    assert attempts["count"] == 4

    unsafe = make_pipeline(retry=retrying(3), retry_unsafe_tools=True)
    with pytest.raises(ServerConnectionError):
        await unsafe.run(context(idempotent=False), flaky)
    assert attempts["count"] == 7


async def test_servers_can_have_their_own_policies() -> None:
    pipeline = make_pipeline()
    strict = ResiliencePolicy(
        operation_timeout=0.01,
        circuit_breaker=AsyncCircuitBreakerFactory(default_threshold=1),
    )
    pipeline.add_server("strict", strict)

    async def slow() -> str:
        await asyncio.sleep(0.05)
        return "slow"

    strict_context = OperationContext(server_id="strict", operation=Operation.DISCOVER)
    with pytest.raises(TimeoutError):
        await pipeline.run(strict_context, slow)
    assert await pipeline.health("strict") is HealthState.UNHEALTHY
    assert await pipeline.run(context(Operation.DISCOVER), slow) == "slow"
    assert await pipeline.health("s") is HealthState.HEALTHY
    assert pipeline.policy == ResiliencePolicy()


async def test_per_server_concurrency_is_bounded() -> None:
    pipeline = make_pipeline(max_concurrency=1)
    pipeline.add_server("t", None)
    active = {"s": 0, "t": 0}
    peak = {"s": 0, "t": 0}

    def tracked(server_id: str) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            active[server_id] += 1
            peak[server_id] = max(peak[server_id], active[server_id])
            await asyncio.sleep(0.01)
            active[server_id] -= 1

        return run

    contexts = {
        name: OperationContext(server_id=name, operation=Operation.DISCOVER) for name in active
    }
    wide = OperationPipeline(
        max_concurrency=10,
        policy=ResiliencePolicy(max_concurrency=2),
        interceptors=(),
        metrics_sink=None,
    )
    wide.add_server("s", None)
    wide.add_server("t", ResiliencePolicy())
    await asyncio.gather(
        *(wide.run(contexts[name], tracked(name)) for name in ("s", "t") for _ in range(6))
    )
    assert peak["s"] == 2
    assert peak["t"] > 2
    await pipeline.aclose()
    await wide.aclose()
