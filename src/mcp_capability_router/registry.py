from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Protocol

from .models import Capability, CapabilityType


class CapabilityRegistry(Protocol):
    async def upsert_many(self, capabilities: Iterable[Capability]) -> None: ...
    async def remove_missing(self, server_id: str, current_ids: set[str]) -> None: ...
    async def remove(self, capability_id: str) -> None: ...
    async def get(self, capability_id: str) -> Capability | None: ...
    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> list[Capability]: ...
    async def close(self) -> None: ...


class CapabilityRegistryBase(ABC):
    """Optional abstract base class for a custom :class:`CapabilityRegistry`.

    ``MCPRuntime`` only requires the *structural* shape defined by the
    :class:`CapabilityRegistry` protocol above -- any object with matching async methods
    works, with or without inheriting from anything. Subclassing this base class is not
    required, but gives implementers a concrete template: the five storage methods are
    enforced as abstract, and ``close()`` already defaults to a no-op for registries that
    do not own a connection or pool to release.
    """

    @abstractmethod
    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        """Insert or update the given capabilities, keyed by ``capability_id``."""

    @abstractmethod
    async def remove_missing(self, server_id: str, current_ids: set[str]) -> None:
        """Remove previously stored capabilities for ``server_id`` not in ``current_ids``."""

    @abstractmethod
    async def remove(self, capability_id: str) -> None:
        """Remove a single stored capability, used by incremental/dependency-aware refresh."""

    @abstractmethod
    async def get(self, capability_id: str) -> Capability | None:
        """Return the stored capability for ``capability_id``, or ``None`` if absent."""

    @abstractmethod
    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> list[Capability]:
        """Return stored capabilities, optionally filtered by server and/or type."""

    async def close(self) -> None:
        """Release owned resources. Override when the backing store needs cleanup."""
        return None


class InMemoryRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}
        self._lock = asyncio.Lock()

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        async with self._lock:
            for capability in capabilities:
                self._items[capability.capability_id] = capability

    async def remove_missing(self, server_id: str, current_ids: set[str]) -> None:
        async with self._lock:
            stale = [
                key
                for key, value in self._items.items()
                if value.server_id == server_id and key not in current_ids
            ]
            for key in stale:
                del self._items[key]

    async def remove(self, capability_id: str) -> None:
        async with self._lock:
            self._items.pop(capability_id, None)

    async def get(self, capability_id: str) -> Capability | None:
        async with self._lock:
            return self._items.get(capability_id)

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> list[Capability]:
        async with self._lock:
            return [
                value
                for value in self._items.values()
                if (server_id is None or value.server_id == server_id)
                and (type is None or value.type == type)
            ]

    async def close(self) -> None:
        return None
