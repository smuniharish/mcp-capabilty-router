from __future__ import annotations

import asyncio
from typing import Any

from .errors import LoadingError
from .models import Capability, CapabilityType
from .server import ServerHandle


class CapabilityLoader:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def load(self, capability: Capability, server: ServerHandle) -> Any:
        if capability.capability_id in self._cache:
            return self._cache[capability.capability_id]
        async with self._guard:
            lock = self._locks.setdefault(capability.capability_id, asyncio.Lock())
        async with lock:
            if capability.capability_id in self._cache:
                return self._cache[capability.capability_id]
            try:
                adapter = await server.connect()
                if capability.type == CapabilityType.TOOL:
                    loaded = getattr(adapter, "get_tool", lambda name: name)(capability.name)
                elif capability.type == CapabilityType.RESOURCE:
                    loaded = getattr(capability, "uri", None) or capability.name
                else:
                    loaded = capability.name
                if asyncio.iscoroutine(loaded):
                    loaded = await loaded
                self._cache[capability.capability_id] = loaded
                return loaded
            except Exception as exc:
                raise LoadingError(f"Could not load {capability.capability_id}") from exc

    async def invalidate_server(self, server_id: str) -> None:
        self._cache = {
            key: value for key, value in self._cache.items() if not key.startswith(f"{server_id}:")
        }

    async def close(self) -> None:
        self._cache.clear()
        self._locks.clear()
