"""Properties of the resilience pipeline: retries and circuit breaking."""

from __future__ import annotations

import asyncio

from hypothesis import given
from hypothesis import strategies as st
from purgatory import AsyncCircuitBreakerFactory
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from mcp_capability_router import (
    CircuitOpenError,
    InvalidRequestError,
    Operation,
    OperationContext,
    ServerUnavailableError,
    is_retryable,
)
from mcp_capability_router._internal.pipeline import OperationPipeline

CONTEXT = OperationContext(server_id="s", operation=Operation.CALL_TOOL)


def pipeline(**options: object) -> OperationPipeline:
    settings: dict[str, object] = {
        "max_concurrency": 4,
        "operation_timeout": None,
        "retry": None,
        "rate_limiter": None,
        "circuit_breaker": None,
        "interceptors": (),
        "metrics_sink": None,
    }
    settings.update(options)
    instance = OperationPipeline(**settings)  # type: ignore[arg-type]
    instance.add_server("s")
    return instance


@given(
    failures=st.integers(min_value=0, max_value=6),
    attempts=st.integers(min_value=1, max_value=6),
)
def test_retries_succeed_exactly_when_attempts_suffice(
    failures: int, attempts: int
) -> None:
    calls = {"count": 0}

    async def flaky() -> str:
        calls["count"] += 1
        if calls["count"] <= failures:
            raise ServerUnavailableError("busy")
        return "ok"

    retry = AsyncRetrying(
        stop=stop_after_attempt(attempts), retry=retry_if_exception(is_retryable)
    )

    async def scenario() -> bool:
        try:
            await pipeline(retry=retry).run(CONTEXT, flaky)
        except ServerUnavailableError:
            return False
        return True

    assert asyncio.run(scenario()) is (failures < attempts)
    assert calls["count"] == min(failures + 1, attempts)


OUTCOMES = st.lists(st.sampled_from(["ok", "server", "client"]), max_size=20)


@given(OUTCOMES, st.integers(min_value=1, max_value=4))
def test_circuit_opens_after_consecutive_server_failures(
    outcomes: list[str], threshold: int
) -> None:
    async def scenario() -> list[str]:
        breakers = AsyncCircuitBreakerFactory(
            default_threshold=threshold, default_ttl=600
        )
        instance = pipeline(circuit_breaker=breakers)
        observed = []
        for outcome in outcomes:

            async def action(outcome: str = outcome) -> None:
                if outcome == "server":
                    raise ServerUnavailableError("down")
                if outcome == "client":
                    raise InvalidRequestError("bad request")

            try:
                await instance.run(CONTEXT, action)
                observed.append("ok")
            except CircuitOpenError:
                observed.append("rejected")
            except (ServerUnavailableError, InvalidRequestError):
                observed.append("failed")
        return observed

    expected = []
    streak = 0
    is_open = False
    for outcome in outcomes:
        if is_open:
            expected.append("rejected")
            continue
        expected.append("ok" if outcome == "ok" else "failed")
        streak = streak + 1 if outcome == "server" else 0
        is_open = streak >= threshold
    assert asyncio.run(scenario()) == expected
