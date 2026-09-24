from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from .metrics import MetricsHook, emit

T = TypeVar("T")
Operation = Callable[[], Awaitable[T]]
FallbackHandler = Callable[[BaseException], Awaitable[T]]

_UNRECOVERABLE = (KeyboardInterrupt, SystemExit)


async def with_fallback(
    operation: Operation[T],
    fallback: FallbackHandler[T],
    *,
    metrics: MetricsHook | None = None,
) -> T:
    """Run ``operation``; on a recoverable failure, run ``fallback(error)`` instead.

    ``fallback`` receives the triggering exception so it can decide on a degraded
    response (a cached value, a default, a synthetic result) rather than propagate
    the failure. Cancellation and process-control exceptions are never swallowed.
    """
    try:
        return await operation()
    except _UNRECOVERABLE:
        raise
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            raise
        await emit(metrics, "fallback.triggered", attributes={"error": type(error).__name__})
        return await fallback(error)


class FallbackPolicy[T]:
    """Reusable, configuration-holding wrapper around :func:`with_fallback`."""

    def __init__(self, fallback: FallbackHandler[T], *, metrics: MetricsHook | None = None) -> None:
        self._fallback = fallback
        self._metrics = metrics

    async def run(self, operation: Operation[T]) -> T:
        return await with_fallback(operation, self._fallback, metrics=self._metrics)
