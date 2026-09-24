from __future__ import annotations

import asyncio
import builtins
from collections.abc import Awaitable
from types import TracebackType
from typing import TypeVar

from ..errors import TimeoutError

T = TypeVar("T")


async def with_timeout(operation: Awaitable[T], timeout: float, *, message: str | None = None) -> T:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    try:
        async with asyncio.timeout(timeout):
            return await operation
    except TimeoutError:
        raise
    except builtins.TimeoutError as error:
        raise TimeoutError(message or f"Operation timed out after {timeout:.3f}s") from error


class AsyncTimeout:
    def __init__(self, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout

    async def __aenter__(self) -> AsyncTimeout:
        self._context = asyncio.timeout(self.timeout)
        await self._context.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        try:
            return await self._context.__aexit__(exc_type, exc, tb)
        except builtins.TimeoutError as error:
            raise TimeoutError(f"Operation timed out after {self.timeout:.3f}s") from error


TimeoutPolicy = AsyncTimeout
