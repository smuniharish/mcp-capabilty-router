from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AsyncBulkhead:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._semaphore:
            return await operation()

    async def __aenter__(self) -> AsyncBulkhead:
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._semaphore.release()


Bulkhead = AsyncBulkhead
