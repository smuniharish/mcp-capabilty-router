"""Regression tests for the tenacity/aiolimiter-backed OperationPipeline.

Exercises the public ``retry=``/``rate_limiter=`` tenacity/aiolimiter surface that
``OperationPipeline``/``MCPRuntime`` expose, including the pipeline's default retry
behavior when no ``retry=`` is supplied.
"""

from __future__ import annotations

import asyncio

import pytest
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
)

from mcp_capability_router.errors import AuthenticationError
from mcp_capability_router.pipeline import OperationPipeline
from mcp_capability_router.resilience import semantic_classifier


class RecordingMetrics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def record(self, event, *, attributes=None):
        self.events.append((event, dict(attributes or {})))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


def _flaky(failures: int, result: object = "ok"):
    calls = {"count": 0}

    async def action():
        calls["count"] += 1
        if calls["count"] <= failures:
            raise RuntimeError("transient")
        return result

    return action, calls


def _retrying(attempts: int) -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )


@pytest.mark.asyncio
async def test_custom_tenacity_async_retrying_is_used_directly():
    action, calls = _flaky(failures=2)
    custom_retry = AsyncRetrying(
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RuntimeError),
        reraise=True,
    )
    pipeline = OperationPipeline(retry=custom_retry)
    result = await pipeline.run("s", "call_tool", action)
    assert result == "ok"
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_non_retryable_category_never_retries_through_the_pipeline():
    calls = {"count": 0}

    async def always_auth_failure():
        calls["count"] += 1
        raise AuthenticationError("bad credentials")

    pipeline = OperationPipeline(retry=_retrying(5))
    with pytest.raises(AuthenticationError):
        await pipeline.run("s", "call_tool", always_auth_failure)
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_without_being_retried_or_rate_limited():
    calls = {"count": 0}

    async def cancels():
        calls["count"] += 1
        raise asyncio.CancelledError()

    pipeline = OperationPipeline(retry=_retrying(5), rate_limiter=AsyncLimiter(1000, time_period=1))
    with pytest.raises(asyncio.CancelledError):
        await pipeline.run("s", "call_tool", cancels)
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_retry_metrics_events_fire_with_the_same_names_and_attributes():
    from mcp_capability_router.pipeline import _default_retry

    metrics = RecordingMetrics()
    action, _ = _flaky(failures=1)
    pipeline = OperationPipeline(retry=_default_retry(2, metrics), metrics=metrics)
    await pipeline.run("s", "call_tool", action)
    names = metrics.names()
    assert "retry" in names
    assert "retry.success" in names
    retry_event = next(attrs for name, attrs in metrics.events if name == "retry")
    assert retry_event["attempt"] == 1
    assert "delay" in retry_event


@pytest.mark.asyncio
async def test_retry_failure_metrics_event_fires_when_retries_are_exhausted():
    metrics = RecordingMetrics()

    async def always_fails():
        raise RuntimeError("boom")

    pipeline = OperationPipeline(retry=_retrying(2), metrics=metrics)
    with pytest.raises(RuntimeError):
        await pipeline.run("s", "call_tool", always_fails)
    assert "retry.failure" in metrics.names()


@pytest.mark.asyncio
async def test_custom_aiolimiter_async_limiter_is_used_directly():
    calls: list[float] = []

    class TrackingLimiter(AsyncLimiter):
        async def acquire(self, amount: float = 1) -> None:
            calls.append(amount)
            await super().acquire(amount)

    limiter = TrackingLimiter(1000, time_period=1)
    pipeline = OperationPipeline(rate_limiter=limiter)

    async def action():
        return "ok"

    result = await pipeline.run("s", "call_tool", action)
    assert result == "ok"
    assert calls == [1]


@pytest.mark.asyncio
async def test_no_retry_configured_means_a_single_attempt():
    action, calls = _flaky(failures=1)
    pipeline = OperationPipeline()
    with pytest.raises(RuntimeError):
        await pipeline.run("s", "call_tool", action)
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_no_rate_limiter_configured_means_no_throttling():
    pipeline = OperationPipeline()
    assert pipeline._rate_limiter is None

    async def action():
        return "ok"

    assert await pipeline.run("s", "call_tool", action) == "ok"
