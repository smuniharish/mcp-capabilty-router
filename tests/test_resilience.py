import asyncio

import pytest

from mcp_capability_router.errors import (
    AuthenticationError,
    CircuitOpenError,
    TimeoutError,
    ToolExecutionError,
)
from mcp_capability_router.resilience import (
    AsyncBulkhead,
    CircuitBreaker,
    CircuitState,
    FailureCategory,
    categorize_failure,
    classify_failure,
    semantic_classifier,
    with_fallback,
    with_timeout,
)


@pytest.mark.asyncio
async def test_timeout_raises_on_slow_operation():
    with pytest.raises(TimeoutError):
        await with_timeout(asyncio.sleep(1), 0.001)


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_bulkhead_limits():
    breaker = CircuitBreaker(failure_threshold=1)

    async def failing():
        raise ValueError("down")

    with pytest.raises(ValueError):
        await breaker.call(failing)
    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.call(failing)

    active = 0
    maximum = 0
    bulkhead = AsyncBulkhead(1)

    async def operation():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1

    await asyncio.gather(*(bulkhead.run(operation) for _ in range(4)))
    assert maximum == 1


@pytest.mark.asyncio
async def test_fallback_runs_only_on_failure():
    async def succeeds():
        return "primary"

    async def fallback(_error):
        return "fallback"

    assert await with_fallback(succeeds, fallback) == "primary"

    async def fails():
        raise ToolExecutionError("tool blew up")

    assert await with_fallback(fails, fallback) == "fallback"


@pytest.mark.asyncio
async def test_fallback_never_swallows_cancellation():
    async def cancelled():
        raise asyncio.CancelledError()

    async def fallback(_error):
        return "should not run"

    with pytest.raises(asyncio.CancelledError):
        await with_fallback(cancelled, fallback)


def test_categorize_failure_maps_semantic_errors():
    assert categorize_failure(AuthenticationError("bad token")) == (
        FailureCategory.AUTHENTICATION_FAILURE
    )
    assert categorize_failure(ToolExecutionError("boom")) == FailureCategory.TOOL_EXECUTION_FAILURE
    assert categorize_failure(ValueError("plain")) == FailureCategory.UNKNOWN


def test_classify_failure_marks_authentication_as_non_retryable():
    classification = classify_failure(AuthenticationError("bad token"))
    assert classification.retryable is False
    assert classification.category == FailureCategory.AUTHENTICATION_FAILURE


def test_semantic_classifier_never_retries_authentication_but_retries_unknown():
    assert semantic_classifier(AuthenticationError("bad token")) is False
    assert semantic_classifier(ValueError("transient")) is True
    assert semantic_classifier(asyncio.CancelledError()) is False
