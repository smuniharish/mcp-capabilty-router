from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

from ..errors import CircuitOpenError
from .classification import Classifier
from .metrics import MetricsHook, emit

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        classifier: Classifier | None = None,
        metrics: MetricsHook | None = None,
    ) -> None:
        if failure_threshold < 1 or recovery_timeout <= 0:
            raise ValueError("failure_threshold must be >= 1 and recovery_timeout positive")
        self.failure_threshold, self.recovery_timeout = failure_threshold, recovery_timeout
        self.classifier, self.metrics = classifier, metrics
        self._state, self._failures, self._opened_at = CircuitState.CLOSED, 0, 0.0
        self._probe = asyncio.Lock()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        probe = await self._before_call()
        try:
            result = await operation()
        except BaseException as error:
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            if self.classifier is None or self.classifier(error):
                await self._record_failure()
            if probe:
                self._probe.release()
            raise
        else:
            await self._record_success()
            if probe:
                self._probe.release()
            return result

    async def _before_call(self) -> bool:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if asyncio.get_running_loop().time() - self._opened_at < self.recovery_timeout:
                    raise CircuitOpenError("Circuit breaker is open")
                self._state = CircuitState.HALF_OPEN
                await emit(self.metrics, "circuit.half_open")
        if self._state == CircuitState.HALF_OPEN:
            if self._probe.locked():
                raise CircuitOpenError("Circuit breaker recovery probe is in progress")
            await self._probe.acquire()
            return True
        return False

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = asyncio.get_running_loop().time()
                await emit(self.metrics, "circuit.open")

    async def _record_success(self) -> None:
        async with self._lock:
            was_half_open = self._state == CircuitState.HALF_OPEN
            self._failures, self._state = 0, CircuitState.CLOSED
            if was_half_open:
                await emit(self.metrics, "circuit.closed")
