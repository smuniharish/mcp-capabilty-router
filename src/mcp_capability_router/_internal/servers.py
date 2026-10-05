"""Lifecycle of the adapter of one registered server."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..contracts import MCPAdapter
from ..errors import ConfigurationError, ServerNotFoundError


class ServerHandle:
    """Owns the adapter of one server and serializes its connection changes.

    The adapter is created by the registered factory and connected on first use.
    Concurrent callers share one connection attempt. Once closed, the handle never
    connects again, so operations that were still queued cannot leak connections.
    """

    def __init__(self, server_id: str, factory: Callable[[], MCPAdapter]) -> None:
        """Create a handle that connects lazily."""
        self.server_id = server_id
        self._factory = factory
        self._adapter: MCPAdapter | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def adapter(self) -> MCPAdapter:
        """Return the connected adapter, connecting first if needed.

        Raises:
            ServerNotFoundError: If the handle is closed.
        """
        adapter = self._adapter
        if adapter is not None:
            return adapter
        async with self._lock:
            self._ensure_open()
            if self._adapter is None:
                self._adapter = await self._open()
            return self._adapter

    async def connect(self) -> None:
        """Connect if not connected yet."""
        await self.adapter()

    async def reconnect(self) -> None:
        """Close the current adapter, if any, and connect a new one."""
        async with self._lock:
            self._ensure_open()
            await self._close_adapter()
            self._adapter = await self._open()

    async def discard(self, adapter: MCPAdapter) -> None:
        """Close `adapter` if it is still current, so the next use reconnects."""
        async with self._lock:
            if self._adapter is adapter:
                await self._close_adapter()

    async def close(self) -> None:
        """Close the current adapter, if any, and refuse to connect again."""
        async with self._lock:
            self._closed = True
            await self._close_adapter()

    def _ensure_open(self) -> None:
        if self._closed:
            msg = f"server {self.server_id!r} is closed"
            raise ServerNotFoundError(msg)

    async def _open(self) -> MCPAdapter:
        adapter = self._factory()
        if not isinstance(adapter, MCPAdapter):
            msg = (
                f"the adapter factory of server {self.server_id!r} returned "
                f"{type(adapter).__name__}, which does not implement MCPAdapter"
            )
            raise ConfigurationError(msg)
        await adapter.connect()
        return adapter

    async def _close_adapter(self) -> None:
        adapter, self._adapter = self._adapter, None
        if adapter is not None:
            await adapter.close()
