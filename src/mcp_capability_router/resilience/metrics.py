from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Protocol


class MetricsHook(Protocol):
    async def record(
        self, event: str, *, attributes: Mapping[str, object] | None = None
    ) -> None: ...


class MetricsHookBase(ABC):
    """Optional abstract base class for a custom :class:`MetricsHook`.

    ``MCPRuntime``/``OperationPipeline`` only require the *structural* ``record(...)`` shape
    defined by the :class:`MetricsHook` protocol above; any object with a matching async method
    works, with or without inheriting from anything. Subclassing this base class instead is not
    required, but gives implementers a concrete, discoverable template: ``record`` is enforced
    as abstract, so a subclass that forgets to implement it fails loudly at instantiation time
    instead of silently no-op-ing on every pipeline event (a real risk when subclassing the
    :class:`MetricsHook` protocol directly, since ``Protocol`` method bodies are live no-op code,
    not enforced stubs). See ``examples/metrics_prometheus.py`` for a real implementation.
    """

    @abstractmethod
    async def record(self, event: str, *, attributes: Mapping[str, object] | None = None) -> None:
        """Record one pipeline event (for example ``operation.start``/``.success``/``.failure``,
        ``retry``/``retry.success``/``retry.failure``, ``circuit.open``/``.half_open``/
        ``.closed``, or ``fallback.triggered``), with the attributes the pipeline attached to
        it."""


class NullMetrics:
    async def record(self, event: str, *, attributes: Mapping[str, object] | None = None) -> None:
        return None


async def emit(
    hook: MetricsHook | None, event: str, *, attributes: Mapping[str, object] | None = None
) -> None:
    if hook is not None:
        await hook.record(event, attributes=attributes)
