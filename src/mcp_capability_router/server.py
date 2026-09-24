from __future__ import annotations

import asyncio
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
