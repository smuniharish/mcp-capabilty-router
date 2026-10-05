from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from aiolimiter import AsyncLimiter
from purgatory import AsyncCircuitBreakerFactory
from refresh_engine import InMemoryMetrics
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from mcp_capability_router import (
    CircuitOpenError,
    ConfigurationError,
    HealthState,
    Operation,
    OperationContext,
    RateLimitError,
    ServerConnectionError,
    ToolExecutionError,
    is_retryable,
)
from mcp_capability_router._internal.pipeline import OperationPipeline


def make_pipeline(**overrides: Any) -> OperationPipeline:
    options: dict[str, Any] = {
        "max_concurrency": 4,
        "operation_timeout": None,
        "retry": None,
        "rate_limiter": None,
        "circuit_breaker": None,
        "interceptors": (),
        "metrics_sink": None,
    }
    options.update(overrides)
    pipeline = OperationPipeline(**options)
    pipeline.add_server("s")
    return pipeline


def context(operation: Operation = Operation.CALL_TOOL) -> OperationContext:
    return OperationContext(server_id="s", operation=operation)


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
        ({"operation_timeout": 0}, "operation_timeout"),
        ({"retry": object()}, "tenacity.AsyncRetrying"),
        ({"rate_limiter": object()}, "aiolimiter.AsyncLimiter"),
        ({"circuit_breaker": object()}, "purgatory.AsyncCircuitBreakerFactory"),
        ({"interceptors": [42]}, "not callable"),
    ],
)
def test_invalid_configuration_is_rejected(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        make_pipeline(**overrides)


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
    counters, _ = metrics.snapshot()
    assert (
        counters[
            "mcp_capability_router.circuit.transitions"
            "{operation=call_tool,server_id=s,state=open}"
        ]
        == 1
    )
    assert (
        counters[
            "mcp_capability_router.operations"
            "{operation=call_tool,outcome=rejected,server_id=s}"
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
        async def intercept(
            ctx: OperationContext, call_next: Callable[[], Awaitable[Any]]
        ) -> Any:
            seen.append(f"{label}:{ctx.operation}")
            result = await call_next()
            seen.append(f"{label}:done")
            return result

        return intercept

    async def short_circuit(
        ctx: OperationContext, call_next: Callable[[], Awaitable[Any]]
    ) -> Any:
        return "cached"

    pipeline = make_pipeline(interceptors=[interceptor("outer"), interceptor("inner")])
    assert await pipeline.run(context(), ok) == "ok"
    assert seen == ["outer:call_tool", "inner:call_tool", "inner:done", "outer:done"]
    cached = make_pipeline(interceptors=[short_circuit])
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
    assert (
        counters["mcp_capability_router.retries{operation=call_tool,server_id=s}"] == 2
    )

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

    pipeline = make_pipeline(
        retry=retrying(3), rate_limiter=CountingLimiter(1000, time_period=1)
    )
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
            "mcp_capability_router.operations"
            "{operation=call_tool,outcome=cancelled,server_id=s}"
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
    assert len(breakers.listeners) == 1
    pipeline.close()
    pipeline.close()
    assert breakers.listeners == {}

    private = make_pipeline()
    private.remove_server("s")
    assert await private.run(context(), ok) == "ok"
    assert await private.health("s") is HealthState.HEALTHY


def test_unknown_circuit_states_are_reported_verbatim() -> None:
    metrics = InMemoryMetrics()
    pipeline = make_pipeline(metrics_sink=metrics)
    pipeline._on_circuit_event("s:call_tool", "failed", SimpleNamespace())
    pipeline._on_circuit_event(
        "s:call_tool", "state_changed", SimpleNamespace(state="odd")
    )
    counters, _ = metrics.snapshot()
    assert counters == {
        "mcp_capability_router.circuit.transitions"
        "{operation=call_tool,server_id=s,state=odd}": 1
    }
