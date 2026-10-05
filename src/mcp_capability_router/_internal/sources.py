"""Adapters between capability discovery and refresh-engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from refresh_engine import (
    DiscoveryResult,
    PlanAction,
    RefreshRequest,
    Resource,
    ResourceSnapshot,
)

from ..contracts import CapabilityRegistry
from ..models import Capability

CAPABILITY_KEY = "capability"
"""Key of the discovered `Capability` in the metadata of a refresh-engine resource."""


class CapabilitySource:
    """Exposes the capabilities of one server as refresh-engine resources.

    Each resource carries its capability in its metadata, along with the `type`
    and `tags` that selectors such as `refresh_engine.TagSelector` read.

    The first successful discovery also prunes the registry of capabilities that
    the server no longer offers, which an earlier registration may have stored.
    """

    def __init__(
        self,
        discover: Callable[[], Awaitable[Sequence[Capability]]],
        prune: Callable[[frozenset[str]], Awaitable[None]],
    ) -> None:
        """Create a source that lists capabilities with `discover`."""
        self._discover = discover
        self._prune = prune
        self._pruned = False
        self._error: Exception | None = None

    async def discover(self) -> DiscoveryResult:
        """List the capabilities of the server."""
        try:
            capabilities = await self._discover()
            if not self._pruned:
                await self._prune(
                    frozenset(capability.capability_id for capability in capabilities)
                )
                self._pruned = True
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
        return ResourceSnapshot(
            resource.resource_id, content=resource.metadata[CAPABILITY_KEY]
        )

    def take_error(self) -> Exception | None:
        """Return and clear the error of the last failed discovery."""
        error, self._error = self._error, None
        return error


class RegistryOperation:
    """Applies refresh-engine plans to a capability registry."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        """Create an operation that writes to `registry`."""
        self._registry = registry

    async def __call__(
        self,
        resource: Resource,
        snapshot: ResourceSnapshot | None,
        action: PlanAction,
        request: RefreshRequest,
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
