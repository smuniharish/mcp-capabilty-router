"""Adapters between capability discovery and refresh-engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from refresh_engine import (
    DiscoveryResult,
    PlanAction,
    RefreshOperation,
    RefreshRequest,
    Resource,
    ResourceSnapshot,
    ResourceSource,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ..contracts import CapabilityRegistry
    from ..models import Capability

CAPABILITY_KEY = "capability"
"""Key of the discovered `Capability` in the metadata of a refresh-engine resource."""


class CapabilitySource(ResourceSource):
    """Exposes the capabilities of one server as refresh-engine resources.

    Each resource carries its capability in its metadata, along with the `type`
    and `tags` that selectors such as `refresh_engine.TagSelector` read.

    The first successful discovery also reconciles the registry with the server:
    it removes capabilities that the server no longer offers, which an earlier
    registration may have stored, and, with a durable state store, it stores the
    capabilities that the state store records but the registry lacks.
    """

    def __init__(
        self,
        discover: Callable[[], Awaitable[Sequence[Capability]]],
        reconcile: Callable[[Sequence[Capability]], Awaitable[None]],
    ) -> None:
        """Create a source that lists capabilities with `discover`."""
        self._discover = discover
        self._reconcile = reconcile
        self._reconciled = False
        self._error: Exception | None = None

    async def discover(self) -> DiscoveryResult:
        """List the capabilities of the server."""
        try:
            capabilities = await self._discover()
            if not self._reconciled:
                await self._reconcile(capabilities)
                self._reconciled = True
        except Exception as error:
            self._error = error
            raise
        self._error = None
        return DiscoveryResult(
            [
                Resource(
                    capability.capability_id,
                    metadata={
                        CAPABILITY_KEY: capability,
                        "type": str(capability.type),
                        "tags": tuple(sorted(capability.tags)),
                    },
                    dependencies=capability.depends_on or None,
                )
                for capability in capabilities
            ]
        )

    async def snapshot(self, resource: Resource, /) -> ResourceSnapshot:
        """Return the capability that discovery attached to `resource`."""
        return ResourceSnapshot(resource.resource_id, content=resource.metadata[CAPABILITY_KEY])

    def take_error(self) -> Exception | None:
        """Return and clear the error of the last failed discovery."""
        error, self._error = self._error, None
        return error


class RegistryOperation(RefreshOperation):
    """Applies refresh-engine plans to a capability registry."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        """Create an operation that writes to `registry`."""
        self._registry = registry

    async def __call__(
        self,
        resource: Resource,
        snapshot: ResourceSnapshot | None,
        action: PlanAction,
        _request: RefreshRequest,
        /,
    ) -> None:
        """Store or remove the capability of `resource`."""
        if action is PlanAction.DELETE:
            await self._registry.remove(resource.resource_id)
            return
        if snapshot is None:
            msg = f"refresh of {resource.resource_id!r} received no snapshot"
            raise RuntimeError(msg)
        await self._registry.upsert_many((snapshot.content,))
