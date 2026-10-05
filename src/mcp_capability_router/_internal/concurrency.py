"""Concurrency helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any


async def gather_or_cancel(*awaitables: Awaitable[Any]) -> list[Any]:
    """Await `awaitables` concurrently and return their results in order.

    If one of them raises, the others are cancelled and awaited before the first
    exception propagates unchanged, with its traceback and cause chain intact.
    """
    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
