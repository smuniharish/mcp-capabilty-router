from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")
Interceptor = Callable[[Callable[[], Awaitable[T]]], Awaitable[T]]


def compose(*interceptors: Interceptor[T]) -> Interceptor[T]:
    async def invoke(operation: Callable[[], Awaitable[T]]) -> T:
        async def call(index: int) -> T:
            if index == len(interceptors):
                return await operation()
            return await interceptors[index](lambda: call(index + 1))

        return await call(0)

    return invoke


class InterceptorChain:
    def __init__(self, interceptors: Sequence[Interceptor[Any]] = ()) -> None:
        self._interceptors = tuple(interceptors)

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        return await compose(*self._interceptors)(operation)
