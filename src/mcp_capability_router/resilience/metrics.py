from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class MetricsHook(Protocol):
    async def record(
        self, event: str, *, attributes: Mapping[str, object] | None = None
    ) -> None: ...


class NullMetrics:
    async def record(self, event: str, *, attributes: Mapping[str, object] | None = None) -> None:
        return None


async def emit(
    hook: MetricsHook | None, event: str, *, attributes: Mapping[str, object] | None = None
) -> None:
    if hook is not None:
        await hook.record(event, attributes=attributes)
