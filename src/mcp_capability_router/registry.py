"""The default, in-process capability registry."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import Capability, CapabilityType


class InMemoryRegistry:
    """Keeps capability metadata in process memory.

    Lookups by ID take constant time, and listing the capabilities of one server
    takes time proportional to that server's capabilities. Every method completes
    without suspending, so concurrent coroutines always observe a consistent
    registry without locking.

    Each runtime owns its registry: closing the runtime clears it.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._items: dict[str, Capability] = {}
        self._by_server: dict[str, dict[str, Capability]] = {}

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        """Insert or replace `capabilities`, keyed by `capability_id`."""
        for capability in capabilities:
            self._discard(capability.capability_id)
            self._items[capability.capability_id] = capability
            self._by_server.setdefault(capability.server_id, {})[
                capability.capability_id
            ] = capability

    async def remove(self, capability_id: str) -> None:
        """Remove one capability; do nothing if it is not stored."""
        self._discard(capability_id)

    async def remove_server(self, server_id: str) -> None:
        """Remove every capability of the server `server_id`."""
        for capability_id in self._by_server.pop(server_id, {}):
            del self._items[capability_id]

    async def get(self, capability_id: str) -> Capability | None:
        """Return the capability `capability_id`, or `None` if it is not stored."""
        return self._items.get(capability_id)

    async def list(
        self,
        *,
        server_id: str | None = None,
        type: CapabilityType | None = None,
    ) -> Sequence[Capability]:
        """Return the stored capabilities, optionally filtered by server and type."""
        source = (
            self._items.values()
            if server_id is None
            else self._by_server.get(server_id, {}).values()
        )
        if type is None:
            return list(source)
        return [capability for capability in source if capability.type == type]

    async def close(self) -> None:
        """Remove every capability."""
        self._items.clear()
        self._by_server.clear()

    def _discard(self, capability_id: str) -> None:
        previous = self._items.pop(capability_id, None)
        if previous is not None:
            server = self._by_server[previous.server_id]
            del server[capability_id]
            if not server:
                del self._by_server[previous.server_id]
