"""Share circuit state and cached tool results between processes through Redis.

Two runtimes stand in for two processes of the same service:

- Circuit breakers come from purgatory; with `AsyncRedisUnitOfWork` their state
  lives in Redis, so when one process sees a server fail, the circuit opens for
  every process and none of them keeps calling the failing server.
- `ToolResultCache` caches the results of read-only tools in a
  `ResultCacheStore`; `RedisResultCacheStore` below keeps them in Redis, so a
  result fetched by one process serves the identical calls of every other.

Requires the `redis` extra and a Redis server:

    MCP_ROUTER_EXAMPLE_REDIS_URL=redis://localhost:6379/0
"""

import asyncio
import os
from collections.abc import Mapping
from contextlib import AsyncExitStack
from typing import Any

from common import crm_server
from langchain_core.messages import ToolMessage
from purgatory import AsyncCircuitBreakerFactory, AsyncRedisUnitOfWork
from purgatory.service._async.repository import AsyncRedisRepository
from redis.asyncio import Redis

from mcp_capability_router import (
    CircuitOpenError,
    FastMCPAdapter,
    MCPRuntime,
    RefreshPolicy,
    ResiliencePolicy,
    ResultCacheStore,
    ServerUnavailableError,
    ToolResultCache,
)

NAMESPACE = "mcp-capability-router-example:"


class RedisResultCacheStore(ResultCacheStore):
    """Cached tool results in Redis, expired by Redis itself."""

    def __init__(self, client: Redis, namespace: str = NAMESPACE) -> None:
        self._client = client
        self._namespace = namespace

    async def get(self, key: str) -> Any | None:
        document = await self._client.get(self._namespace + key)
        return None if document is None else ToolMessage.model_validate_json(document)

    async def set(self, key: str, value: Any, ttl: float) -> None:
        if not isinstance(value, ToolMessage):
            msg = "this example store accepts only ToolMessage values"
            raise TypeError(msg)
        await self._client.set(
            self._namespace + key, value.model_dump_json(), px=max(1, round(ttl * 1000))
        )

    async def clear(self, prefix: str = "") -> None:
        keys = [key async for key in self._client.scan_iter(match=f"{self._namespace}{prefix}*")]
        if keys:
            await self._client.delete(*keys)


class CountingAdapter(FastMCPAdapter):
    """Counts the tool calls that reach the server, and fails them while it is down."""

    def __init__(self, name: str) -> None:
        super().__init__(crm_server())
        self.name = name
        self.down = False

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        print(f"  {self.name} calls the server: {name}")
        if self.down:
            msg = "crm is down"
            raise ServerUnavailableError(msg)
        return await super().call_tool(name, arguments)


async def main() -> None:
    url = os.environ["MCP_ROUTER_EXAMPLE_REDIS_URL"]
    resources = AsyncExitStack()
    client = await resources.enter_async_context(Redis.from_url(url))
    cache = RedisResultCacheStore(client)

    async def reset() -> None:
        await cache.clear()
        breakers = [key async for key in client.scan_iter(match="cbr::crm:*")]
        if breakers:
            await client.delete(*breakers)

    def process(name: str) -> tuple[MCPRuntime, CountingAdapter]:
        adapter = CountingAdapter(name)
        unit = AsyncRedisUnitOfWork(url)
        repository = unit.contexts
        if not isinstance(repository, AsyncRedisRepository):
            msg = "the Redis unit of work must own a Redis repository"
            raise TypeError(msg)
        resources.push_async_callback(repository.redis.aclose)
        breakers = AsyncCircuitBreakerFactory(default_threshold=2, default_ttl=60, uow=unit)
        runtime = MCPRuntime(
            resilience=ResiliencePolicy(circuit_breaker=breakers),
            interceptors=[ToolResultCache(ttl=60, store=cache)],
        )
        return runtime, adapter

    async with resources:
        await reset()
        first, first_crm = process("first")
        second, second_crm = process("second")
        await resources.enter_async_context(first)
        await resources.enter_async_context(second)
        policy = RefreshPolicy(on_register=True)
        await first.register_server("crm", lambda: first_crm, refresh=policy)
        await second.register_server("crm", lambda: second_crm, refresh=policy)

        print("a read-only result is cached once for every process:")
        for runtime in (first, second):
            message = await runtime.execute("crm:tool:search_customers", {"query": "acme"})
            print(f"  -> {message.artifact['structured_content']['result'][0]['name']}")

        print("\na failing server opens the circuit for every process:")
        first_crm.down = True
        arguments = {"customer_id": "c-001", "email": "ada@example.com"}
        for runtime in (first, first, second):
            try:
                await runtime.execute("crm:tool:update_customer_email", arguments)
            except (ServerUnavailableError, CircuitOpenError) as error:
                print(f"  {type(error).__name__}: {error}")
        print(f"health in the second process: {await second.health('crm')}")

        await reset()


if __name__ == "__main__":
    asyncio.run(main())
