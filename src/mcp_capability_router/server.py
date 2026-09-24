from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"


class MCPAdapter(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def list_tools(self) -> list[Any]: ...
    async def list_resources(self) -> list[Any]: ...
    async def list_prompts(self) -> list[Any]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...
    async def read_resource(self, uri: str) -> Any: ...
    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class MCPAdapterBase(ABC):
    """Optional abstract base class for a custom :class:`MCPAdapter`.

    ``MCPRuntime.register_server`` only requires the *structural* shape defined by the
    :class:`MCPAdapter` protocol above -- any object produced by the registered factory with
    matching async methods works, with or without inheriting from anything (see
    ``examples/public_api_overrides.py`` for adapters implemented via structural typing only).
    Subclassing this base class instead is not required, but gives implementers a concrete,
    discoverable template: every server operation is enforced as abstract, so a subclass that
    forgets to implement one fails loudly at instantiation time instead of silently no-op-ing
    the first time the runtime calls it.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Open the underlying MCP transport. Called at most once per connection attempt."""

    @abstractmethod
    async def close(self) -> None:
        """Release the underlying MCP transport and any connection-scoped resources."""

    @abstractmethod
    async def list_tools(self) -> list[Any]:
        """Return this server's current tools, in the adapter's own raw representation."""

    @abstractmethod
    async def list_resources(self) -> list[Any]:
        """Return this server's current resources, in the adapter's own raw representation."""

    @abstractmethod
    async def list_prompts(self) -> list[Any]:
        """Return this server's current prompts, in the adapter's own raw representation."""

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke one tool by name with the given arguments and return its raw result."""

    @abstractmethod
    async def read_resource(self, uri: str) -> Any:
        """Read one resource by URI and return its raw content."""

    @abstractmethod
    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Render one prompt by name with the given arguments and return its raw content."""


AdapterFactory = Any


@dataclass
class ServerHandle:
    server_id: str
    factory: AdapterFactory
    metadata: dict[str, Any] = field(default_factory=dict)
    adapter: MCPAdapter | None = None
    health: HealthState = HealthState.HEALTHY
    _connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def connect(self) -> MCPAdapter:
        if self.adapter is not None:
            return self.adapter
        async with self._connect_lock:
            if self.adapter is None:
                adapter = self.factory() if callable(self.factory) else self.factory
                await adapter.connect()
                self.adapter = adapter
        return self.adapter

    async def close(self) -> None:
        if self.adapter is not None:
            await self.adapter.close()
            self.adapter = None
