from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

from refresh_engine import (
    DiscoveryResult,
    PlanAction,
    RefreshConfig,
    RefreshEngine,
    RefreshMode,
    RefreshRequest,
    ResourceSnapshot,
    StateStore,
)
from refresh_engine import Resource as EngineResource

from .discovery import discover_server
from .models import Capability
from .registry import CapabilityRegistry
from .server import ServerHandle

RefreshEventSource = asyncio.Queue[object] | AsyncIterable[object]


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Automatic refresh triggers owned by ``MCPRuntime`` for one server.

    ``on_register`` performs initial discovery before registration returns.
    ``on_query_miss`` makes ordinary ``runtime.query(...)`` calls refresh this
    server after a cache miss. ``interval`` schedules periodic reconciliation,
    and every item emitted by ``change_events`` triggers event-driven refresh.

    ``mode`` is the ``refresh_engine.RefreshMode`` used by these automatic triggers
    (``FULL`` by default, matching this project's historical discover-then-reconcile
    behavior). ``config``/``store`` are passed straight through to the underlying
    ``refresh_engine.RefreshEngine`` for this server; leaving either as ``None`` means
    refresh-engine's own recommended defaults apply unmodified (``RefreshConfig()``'s
    ``max_concurrency=10``, ``OverlapPolicy.COALESCE``, ``FailurePolicy.BEST_EFFORT``,
    and its own retry/timeout defaults, and an ``InMemoryStateStore()``).
    """

    on_register: bool = False
    on_query_miss: bool = False
    interval: float | None = None
    change_events: RefreshEventSource | None = None
    mode: RefreshMode = RefreshMode.FULL
    config: RefreshConfig | None = None
    store: StateStore | None = None

    def __post_init__(self) -> None:
        if self.interval is not None and self.interval <= 0:
            raise ValueError("RefreshPolicy.interval must be greater than zero")


class _CapabilitySource:
    """Adapts :func:`discover_server` to the ``refresh_engine.ResourceSource`` protocol."""

    def __init__(self, handle: ServerHandle) -> None:
        self._handle = handle
        self._by_id: dict[str, Capability] = {}

    async def discover(self) -> DiscoveryResult:
        capabilities = await discover_server(self._handle)
        self._by_id = {c.capability_id: c for c in capabilities}
        return DiscoveryResult(resources=self._iter_resources(capabilities))

    async def _iter_resources(
        self, capabilities: list[Capability]
    ) -> AsyncIterator[EngineResource]:
        for capability in capabilities:
            yield EngineResource(
                resource_id=capability.capability_id,
                dependencies=frozenset(capability.depends_on),
            )

    async def snapshot(self, resource: EngineResource) -> ResourceSnapshot:
        capability = self._by_id[resource.resource_id]
        return ResourceSnapshot(
            resource_id=capability.capability_id,
            content=capability,
            dependencies=frozenset(capability.depends_on),
        )


class _CapabilityOperation:
    """Adapts :class:`CapabilityRegistry` writes to the ``refresh_engine.RefreshOperation``
    protocol: ``REFRESH`` actions upsert the discovered capability, ``DELETE`` actions
    remove a single stale one -- replacing the hand-rolled full-registry reconciliation
    this project used to perform on every refresh.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    async def __call__(
        self,
        resource: EngineResource | None,
        snapshot: ResourceSnapshot | None,
        action: PlanAction,
        request: RefreshRequest,
    ) -> None:
        if action is PlanAction.DELETE:
            assert resource is not None
            await self._registry.remove(resource.resource_id)
            return
        assert snapshot is not None and isinstance(snapshot.content, Capability)
        await self._registry.upsert_many([snapshot.content])


def build_refresh_engine(
    handle: ServerHandle, registry: CapabilityRegistry, policy: RefreshPolicy
) -> RefreshEngine:
    """Build the per-server ``RefreshEngine`` backing ``MCPRuntime``'s refresh machinery."""
    return RefreshEngine(
        _CapabilitySource(handle),
        _CapabilityOperation(registry),
        config=policy.config,
        store=policy.store,
    )
